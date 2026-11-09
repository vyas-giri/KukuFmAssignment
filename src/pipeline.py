"""Propose -> validate -> judge, per episode.

usage: python src/pipeline.py 50        (one episode)
       python src/pipeline.py 1 50      (range, inclusive)
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from llm import chat_json, default_model
from prompts import PROPOSE, JUDGE
from windows import load, episode_text, span, first_seconds, beat_line, MIN_D, MAX_D

OUT = Path("outputs")
W = {"hook": 0.35, "cliffhanger": 0.35, "standalone": 0.30}   # code decides the weighting, not the LLM


def combined(s):
    return round(sum(W[k] * s[k] for k in W), 2)


def fit(ep, s):
    """If the model's arithmetic was off, extend/trim by whole beats. The judge re-scores the real clip anyway."""
    ids = [b["id"] for b in ep["beats"]]
    i, j, rep = ids.index(s["first"]), ids.index(s["last"]), False
    while s["dur"] < MIN_D and (j + 1 < len(ids) or i > 0):
        if j + 1 < len(ids): j += 1
        else: i -= 1   # already at the episode's end: keep that cliffhanger, add lead-in before it
        s = span(ep, ids[i], ids[j]); rep = True
    while s["dur"] > MAX_D and i < j:
        i += 1; s = span(ep, ids[i], ids[j]); rep = True
    return s, rep


def clip_beats(ep, c):
    ids = [b["id"] for b in ep["beats"]]
    return ep["beats"][ids.index(c["first"]): ids.index(c["last"]) + 1]


def clip_card(ep, c, cid):
    bs = clip_beats(ep, c)
    first3 = first_seconds(ep, c["start"]) or bs[:1]
    return (f"### CLIP {cid} ({c['dur']:.0f}s)\n"
            f"FIRST 3 SECONDS:\n" + "\n".join(beat_line(b) for b in first3) +
            "\nFULL CLIP:\n" + "\n".join(beat_line(b) for b in bs) +
            f"\nLAST BEAT:\n{beat_line(bs[-1])}\n")


def judge(items, model=None):
    """items: list of (ep, clip, clip_id). One call for all of them. Returns {clip_id: scores}."""
    user = "\n".join(clip_card(ep, c, cid) for ep, c, cid in items)
    out = chat_json(JUDGE, user, temperature=0.0, model=model)
    res = {}
    for s in out.get("scores", []):
        try:
            sc = {k: max(1, min(10, float(s[k]))) for k in W}
        except (KeyError, TypeError, ValueError):
            continue
        sc["problem"] = s.get("problem", "")
        sc["score"] = combined(sc)
        res[re.sub(r"^\s*CLIP\s+", "", str(s.get("clip")), flags=re.I).strip()] = sc   # model sometimes echoes "CLIP E4P8"
    return res


JUDGE_BATCH = 8   # clips per judge call; batching keeps free-tier request counts low


def propose(n, log):
    """1 LLM call: candidate promos for one episode, validated and refit by code."""
    ep = load(n)
    user = f"EPISODE {n} LOGLINE: {ep['logline']}\n\nBEATS (id start-end | content):\n{episode_text(ep)}"
    raw = chat_json(PROPOSE, user).get("promos", [])
    cands, seen = [], set()
    for k, p in enumerate(raw):
        entry = {"episode": n, "k": k, "proposed": p}
        try:
            c = span(ep, p["start_beat"], p["end_beat"])
        except (KeyError, ValueError, TypeError) as e:
            entry["issue"] = f"rejected: {e}"; log.append(entry); continue
        if not c["valid"]:
            before = c["dur"]
            c, _ = fit(ep, c)
            entry["issue"] = f"duration {before:.1f}s out of range -> refit to {c['dur']:.1f}s"
            if not c["valid"]:
                entry["issue"] += " (still invalid, dropped)"; log.append(entry); continue
        if "issue" in entry:
            log.append(entry)
        if (c["first"], c["last"]) in seen:
            continue
        seen.add((c["first"], c["last"]))
        fs = first_seconds(ep, c["start"])
        c.update(hook=p.get("hook", ""), cliffhanger=p.get("cliffhanger", ""), why=p.get("why", ""),
                 segments=[{"episode": n, "start": c["start"], "end": c["end"]}],
                 opening_line=fs[0]["text"] if fs else "", closing_line=clip_beats(ep, c)[-1]["text"],
                 model=default_model())
        cands.append(c)
    return cands


def judge_all(cands, log):
    """Score every candidate, JUDGE_BATCH clips per call. Clip ids are unique across episodes."""
    for i in range(0, len(cands), JUDGE_BATCH):
        batch = cands[i:i + JUDGE_BATCH]
        items = [(load(c["episode"]), c, f"E{c['episode']}P{i + k}") for k, c in enumerate(batch)]
        try:
            scores = judge(items)
        except Exception as e:
            print(f"judge batch {i // JUDGE_BATCH}: FAILED {type(e).__name__}: {str(e)[:200]}", flush=True)
            log.append({"issue": f"judge batch failed: {e}"}); continue
        for ep, c, cid in items:
            if cid in scores:
                c["judge"] = scores[cid]; c["score"] = scores[cid]["score"]
            else:
                log.append({"episode": c["episode"], "issue": f"judge skipped clip {cid}"})
        print(f"judged {min(i + JUDGE_BATCH, len(cands))}/{len(cands)}", flush=True)
    return [c for c in cands if "score" in c]


def main():
    a = int(sys.argv[1]); b = int(sys.argv[2]) if len(sys.argv) > 2 else a
    OUT.mkdir(exist_ok=True)
    log, allc, fails = [], [], 0
    for n in range(a, b + 1):
        try:
            cs = propose(n, log); fails = 0
        except Exception as e:
            print(f"ep{n:>2}: FAILED {type(e).__name__}: {str(e)[:300]}", flush=True)
            log.append({"episode": n, "issue": f"failed: {e}"}); fails += 1
            if fails >= 3:
                print("3 failures in a row (quota?) - stopping; rerun later, finished calls are cached", flush=True)
                break
            continue
        allc += cs
        print(f"ep{n:>2}: {len(cs)} candidates", flush=True)
    allc = judge_all(allc, log)
    tag = f"{a}-{b}"
    (OUT / f"candidates_{tag}.json").write_text(json.dumps(allc, indent=1))
    with open(OUT / f"validation_log_{tag}.jsonl", "w") as f:
        for e in log:
            f.write(json.dumps(e) + "\n")
    print(f"\n{len(allc)} promos from {len({c['episode'] for c in allc})} episodes -> outputs/candidates_{tag}.json; "
          f"{len(log)} validation issues logged", flush=True)


if __name__ == "__main__":
    main()
