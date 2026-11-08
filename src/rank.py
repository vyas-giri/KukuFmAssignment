"""Merge all candidates, dedupe overlaps, rank, write outputs/promos_ranked.{json,md}.

usage: python src/rank.py
"""
import glob, json
from pathlib import Path

OUT = Path("outputs")
MAX_PER_EP_TOP10 = 2   # keep the first posts varied across the story


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def overlap(a, b):
    if a["episode"] != b["episode"]:
        return 0
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / min(a["dur"], b["dur"])


def main():
    cands = []
    for f in sorted(glob.glob(str(OUT / "candidates_*.json"))):
        cands += json.loads(Path(f).read_text())
    # later files win on exact duplicates (reruns)
    by_key = {(c["episode"], c["first"], c["last"]): c for c in cands}
    cands = sorted(by_key.values(), key=lambda c: (-c["score"], c["episode"], c["start"]))

    kept = []
    for c in cands:
        if all(overlap(c, k) <= 0.5 for k in kept):
            kept.append(c)

    # posting order: by score, but no more than N from one episode in the first 10
    order, rest, per_ep = [], [], {}
    for c in kept:
        if len(order) < 10 and per_ep.get(c["episode"], 0) >= MAX_PER_EP_TOP10:
            rest.append(c); continue
        order.append(c); per_ep[c["episode"]] = per_ep.get(c["episode"], 0) + 1
    order += rest
    for i, c in enumerate(order, 1):
        c["rank"] = i

    (OUT / "promos_ranked.json").write_text(json.dumps(order, indent=1))
    L = ["# Ranked promos", "",
         f"{len(order)} promos from {len({c['episode'] for c in order})} episodes "
         f"(after removing {len(cands) - len(kept)} overlapping duplicates).",
         "Score = 0.35 hook + 0.35 cliffhanger + 0.30 standalone (judge, 1-10).", "",
         "| # | Ep | Segment(s) | Dur | Score | H/C/S | Hook | Cliffhanger | Why |",
         "|---|---|---|---|---|---|---|---|---|"]
    for c in order:
        j = c["judge"]
        seg = "; ".join(f"ep{s['episode']} {fmt(s['start'])}-{fmt(s['end'])}" for s in c["segments"])
        cell = lambda s: str(s).replace("|", "/").replace("\n", " ")
        L.append(f"| {c['rank']} | {c['episode']} | {seg} | {c['dur']:.0f}s | {c['score']:.1f} | "
                 f"{j['hook']:.0f}/{j['cliffhanger']:.0f}/{j['standalone']:.0f} | {cell(c['hook'])} | "
                 f"{cell(c['cliffhanger'])} | {cell(c['why'])} |")
    (OUT / "promos_ranked.md").write_text("\n".join(L) + "\n")
    print(f"{len(order)} promos ranked -> outputs/promos_ranked.md")
    for c in order[:10]:
        print(f"#{c['rank']:>2} ep{c['episode']:>2} {fmt(c['start'])}-{fmt(c['end'])} score {c['score']:.1f}  {c['hook'][:70]}")


if __name__ == "__main__":
    main()
