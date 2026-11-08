"""Propose -> validate -> judge, per episode.

usage: python src/pipeline.py 50        (one episode)
       python src/pipeline.py 1 50      (range, inclusive)
"""
import json, sys
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
        res[str(s.get("clip"))] = sc
    return res


def run_episode(n, log):
    ep = load(n)
    user = f"EPISODE {n} LOGLINE: {ep['logline']}\n\nBEATS (id start-end | content):\n{episode_text(ep)}"
    raw = chat_json(PROPOSE, user).get("promos", [])
    cands = []
    for k, p in enumerate(raw):
        entry = {"episode": n, "k": k, "proposed": p}
        try:
            c = span(ep, p["start_beat"], p["end_beat"])
        except (KeyError, ValueError) as e:
            entry["issue"] = f"rejected: {e}"; log.append(entry); continue
        if not c["valid"]:
            before = c["dur"]
            c, _ = fit(ep, c)
            entry["issue"] = f"duration {before:.1f}s out of range -> refit to {c['dur']:.1f}s"
            if not c["valid"]:
                entry["issue"] += " (still invalid, dropped)"; log.append(entry); continue
        if "issue" in entry:
            log.append(entry)
        c.update(hook=p.get("hook", ""), cliffhanger=p.get("cliffhanger", ""), why=p.get("why", ""))
        cands.append(c)
    # drop exact duplicates
    seen, uniq = set(), []
    for c in cands:
        if (c["first"], c["last"]) not in seen:
            seen.add((c["first"], c["last"])); uniq.append(c)
    if uniq:
        scores = judge([(ep, c, f"P{i}") for i, c in enumerate(uniq)])
        for i, c in enumerate(uniq):
            s = scores.get(f"P{i}")
            if s is None:
                log.append({"episode": n, "issue": f"judge skipped clip P{i}"}); continue
            c["judge"] = s; c["score"] = s["score"]
        uniq = [c for c in uniq if "score" in c]
    for c in uniq:
        c["segments"] = [{"episode": n, "start": c["start"], "end": c["end"]}]
        c["opening_line"] = first_seconds(ep, c["start"])[0]["text"] if first_seconds(ep, c["start"]) else ""
        c["closing_line"] = clip_beats(ep, c)[-1]["text"]
        c["model"] = default_model()
    return uniq


def main():
    a = int(sys.argv[1]); b = int(sys.argv[2]) if len(sys.argv) > 2 else a
    OUT.mkdir(exist_ok=True)
    log, allc = [], []
    for n in range(a, b + 1):
        try:
            cs = run_episode(n, log)
        except Exception as e:
            print(f"ep{n:>2}: FAILED {type(e).__name__}: {str(e)[:300]}"); log.append({"episode": n, "issue": f"failed: {e}"})
            continue
        allc += cs
        best = max((c["score"] for c in cs), default=0)
        print(f"ep{n:>2}: {len(cs)} promos, best {best:.1f}")
    tag = f"{a}-{b}"
    (OUT / f"candidates_{tag}.json").write_text(json.dumps(allc, indent=1))
    with open(OUT / f"validation_log_{tag}.jsonl", "w") as f:
        for e in log:
            f.write(json.dumps(e) + "\n")
    print(f"\n{len(allc)} promos -> outputs/candidates_{tag}.json; {len(log)} validation issues logged")


if __name__ == "__main__":
    main()
