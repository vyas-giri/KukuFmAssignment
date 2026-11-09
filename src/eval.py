"""Quality check: tool picks vs random 20-60s windows.

python src/eval.py baseline 30   # judge 30 random windows (same judge) -> outputs/baseline.json
python src/eval.py sheet 15      # blind sheet: top 15 tool + 15 random, shuffled -> eval/label_sheet.md, eval/labels.csv
                                 # fill the 'label' column with 1 (would post) or 0. Don't open eval/key.json.
python src/eval.py score         # -> outputs/eval_report.md
"""
import csv, json, random, statistics as st, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from windows import load, random_window, beat_line
from pipeline import judge, clip_beats

OUT, EV = Path("outputs"), Path("eval")
rng = random.Random(42)


def ranked():
    return json.loads((OUT / "promos_ranked.json").read_text())


def baseline(n):
    eps = sorted({c["episode"] for c in ranked()})
    picks = []
    while len(picks) < n:
        e = rng.choice(eps)
        w = random_window(load(e), rng)
        if w: picks.append(w)
    for i in range(0, n, 8):   # 8 clips per judge call
        batch = picks[i:i + 8]
        s = judge([(load(w["episode"]), w, f"R{i + k}") for k, w in enumerate(batch)])
        for k, w in enumerate(batch):
            if f"R{i + k}" in s:
                w["judge"] = s[f"R{i + k}"]; w["score"] = w["judge"]["score"]
    picks = [w for w in picks if "score" in w]
    (OUT / "baseline.json").write_text(json.dumps(picks, indent=1))
    print(f"random baseline: n={len(picks)} mean judge score {st.mean(w['score'] for w in picks):.2f}")


def sheet(n):
    EV.mkdir(exist_ok=True)
    tool = [dict(c, src="tool") for c in ranked()[:n]]
    base = [dict(w, src="random") for w in json.loads((OUT / "baseline.json").read_text())[:n]]
    items = tool + base
    rng.shuffle(items)
    key, L, rows = {}, ["# Blind label sheet", "For each clip: would you post it as a promo? Mark 1/0 in eval/labels.csv.", ""], []
    for i, c in enumerate(items, 1):
        cid = f"C{i:02d}"
        key[cid] = {"src": c["src"], "episode": c["episode"], "first": c["first"], "last": c["last"],
                    "score": c["score"]}
        L.append(f"## {cid}  (ep{c['episode']}, {c['dur']:.0f}s)")
        L += [beat_line(b) for b in clip_beats(load(c["episode"]), c)] + [""]
        rows.append({"clip": cid, "label": ""})
    (EV / "label_sheet.md").write_text("\n".join(L))
    (EV / "key.json").write_text(json.dumps(key, indent=1))
    with open(EV / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["clip", "label"]); w.writeheader(); w.writerows(rows)
    print(f"{len(items)} clips -> eval/label_sheet.md; label eval/labels.csv")


def score():
    key = json.loads((EV / "key.json").read_text())
    labels = {r["clip"]: r["label"].strip() for r in csv.DictReader(open(EV / "labels.csv"))}
    lab = {c: int(v) for c, v in labels.items() if v in ("0", "1")}
    tool = [lab[c] for c in lab if key[c]["src"] == "tool"]
    rand = [lab[c] for c in lab if key[c]["src"] == "random"]
    base = json.loads((OUT / "baseline.json").read_text())
    tj = [c["score"] for c in ranked()]
    # judge-human agreement: judge says "post" if score >= 6
    agree = [int(key[c]["score"] >= 6) == lab[c] for c in lab]
    R = ["# Evaluation report", "",
         "## Judge scores (automatic, all clips)",
         f"- Tool promos: n={len(tj)}, mean {st.mean(tj):.2f}, median {st.median(tj):.2f}",
         f"- Random 20-60s windows: n={len(base)}, mean {st.mean(c['score'] for c in base):.2f}, "
         f"median {st.median(c['score'] for c in base):.2f}", "",
         "## Blind human labels (would I post this? 1/0)",
         f"- Tool top picks: {sum(tool)}/{len(tool)} = {sum(tool) / max(1, len(tool)):.0%}",
         f"- Random windows: {sum(rand)}/{len(rand)} = {sum(rand) / max(1, len(rand)):.0%}",
         f"- Judge (score>=6) agrees with human on {sum(agree)}/{len(agree)} = {sum(agree) / max(1, len(agree)):.0%}", "",
         "## Disagreements (inspect these for failure modes)"]
    for c in sorted(lab):
        k = key[c]
        if int(k["score"] >= 6) != lab[c]:
            R.append(f"- {c}: {k['src']} ep{k['episode']} {k['first']}..{k['last']} judge {k['score']:.1f}, human {lab[c]}")
    (OUT / "eval_report.md").write_text("\n".join(R) + "\n")
    print("\n".join(R))


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"baseline": lambda: baseline(int(sys.argv[2]) if len(sys.argv) > 2 else 30),
     "sheet": lambda: sheet(int(sys.argv[2]) if len(sys.argv) > 2 else 15),
     "score": score}[cmd]()
