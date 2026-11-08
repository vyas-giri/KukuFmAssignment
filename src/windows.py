import json, random
from pathlib import Path

MIN_D, MAX_D = 20.0, 60.0


def load(n, root="data/parsed"):
    return json.loads(Path(root, f"ep{n:02d}.json").read_text())


def beat_line(b):
    who = f"{b['speaker']} ({b['emotion']}): " if b["kind"] == "dialogue" and b["emotion"] else \
          f"{b['speaker']}: " if b["kind"] == "dialogue" else f"[{b['kind']}] "
    txt = f'"{b["text"]}"' if b["kind"] == "dialogue" else b["text"]
    return f"{b['id']} {b['start']:.1f}-{b['end']:.1f}s | {who}{txt}"


def episode_text(ep):
    """What the LLM reads: numbered beats only. It answers with beat IDs, never timestamps."""
    return "\n".join(beat_line(b) for b in ep["beats"])


def span(ep, first_id, last_id):
    """Convert an LLM's (start_beat, end_beat) into real timestamps. Raises on hallucinated IDs."""
    idx = {b["id"]: i for i, b in enumerate(ep["beats"])}
    for x in (first_id, last_id):
        if x not in idx:
            raise ValueError(f"unknown beat id {x}")
    if idx[first_id] > idx[last_id]:
        raise ValueError("start beat after end beat")
    s = ep["beats"][idx[first_id]]["start"]
    e = max(b["end"] for b in ep["beats"][idx[first_id]:idx[last_id] + 1])
    d = e - s
    return {"episode": ep["episode"], "start": s, "end": e, "dur": round(d, 2),
            "valid": MIN_D <= d <= MAX_D, "first": first_id, "last": last_id}


def first_seconds(ep, start, n=3.0):
    """Beats inside the first n seconds of a clip: what the hook is judged on."""
    return [b for b in ep["beats"] if start <= b["start"] < start + n]


def all_windows(ep, min_d=MIN_D, max_d=MAX_D):
    """Every valid 20-60s window starting/ending on a dialogue or action beat. Used for the random baseline."""
    core = [b for b in ep["beats"] if b["kind"] in ("dialogue", "action")]
    out = []
    for i, s in enumerate(core):
        for e in core[i:]:
            if min_d <= e["end"] - s["start"] <= max_d:
                out.append(span(ep, s["id"], e["id"]))
    return out


def random_window(ep, rng=random):
    w = all_windows(ep)
    return rng.choice(w) if w else None


if __name__ == "__main__":
    for n in (1, 25, 50):
        ep = load(n)
        print(f"ep{n}: {len(ep['beats'])} beats, {len(all_windows(ep))} valid windows")
    ep = load(50)
    print(episode_text(ep)[:900])