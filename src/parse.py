import json, re, sys
from pathlib import Path

HEAD = re.compile(r"^\*\*(.+?):\*\*\s*$")
TIME = re.compile(r"Start:\s*\((\d+):(\d+(?:\.\d+)?)\)\s*\|\s*End:\s*\((\d+):(\d+(?:\.\d+)?)\)")
SCENE_TS = re.compile(r"Scene (start|end):\s*(\d+):(\d+(?:\.\d+)?)")
NONSPEECH = {"CAMERA", "ACTION", "SOUND FX", "SFX", "MUSIC"}


def _sec(m, s):
    return int(m) * 60 + float(s)


def parse_episode(path):
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text = "\n".join(lines)
    m = re.search(r"EPISODE NUMBER:\s*Episode\s*(\d+)", text)
    num = int(m.group(1)) if m else int(re.search(r"episode-(\d+)", path.name).group(1))
    ep = {"file": path.name, "episode": num, "logline": "", "continuity": "",
          "scenes": [], "blocks": [], "warnings": []}

    scene, cur = None, None

    def flush():
        nonlocal cur
        if cur is not None:
            if cur["start"] is None:
                ep["warnings"].append(f"block without timestamp: {cur['label']}")
            else:
                cur["text"] = " ".join(cur.pop("_t")).strip()
                ep["blocks"].append(cur)
        cur = None

    for raw in lines:
        line = raw.strip()
        if line.startswith("EPISODE LOGLINE:"):
            ep["logline"] = line.split(":", 1)[1].strip(); continue
        if line.startswith("CONTINUITY NOTES:"):
            ep["continuity"] = line.split(":", 1)[1].strip(); continue
        sm = re.match(r"SCENE\s+(\d+)\s*$", line)
        if sm:
            flush(); scene = int(sm.group(1))
            ep["scenes"].append({"scene": scene, "heading": "", "start": None, "end": None}); continue
        if scene is not None and line.startswith("Scene heading:"):
            ep["scenes"][-1]["heading"] = line.split(":", 1)[1].strip(); continue
        st = SCENE_TS.match(line)
        if st and scene is not None:
            ep["scenes"][-1][st.group(1)] = _sec(st.group(2), st.group(3)); continue
        h = HEAD.match(line)
        if h:
            flush()
            cur = {"scene": scene, "label": h.group(1), "start": None, "end": None, "_t": []}
            continue
        if cur is None or not line or line.startswith("---"):
            continue
        t = TIME.search(line)
        if t and cur["start"] is None:
            cur["start"], cur["end"] = _sec(t.group(1), t.group(2)), _sec(t.group(3), t.group(4))
            if cur["end"] < cur["start"]:
                ep["warnings"].append(f"end<start in {cur['label']} @ {cur['start']}")
            continue
        cur["_t"].append(line)
    flush()

    # classify + build numbered beats (camera shots stay in blocks only)
    beats = []
    for b in sorted(ep["blocks"], key=lambda b: (b["start"], b["end"])):
        label = b["label"]
        base = re.sub(r"\s*\(.*$", "", label).strip()
        parens = [p for p in re.findall(r"\(([^()]*)\)", label) if p not in ("O.S.", "V.O.", "O.C.")]
        if base.upper() in NONSPEECH:
            kind, speaker, emo = base.lower().replace(" ", "_"), None, None
        else:
            kind, speaker, emo = "dialogue", base, (parens[-1] if parens else None)
        b.update(kind=kind, speaker=speaker, emotion=emo, text=b["text"].strip('"\u201c\u201d '))
        if kind != "camera":
            beats.append({"kind": kind, "speaker": speaker, "emotion": emo, "text": b["text"],
                          "start": b["start"], "end": b["end"], "scene": b["scene"]})
    beats.sort(key=lambda x: (x["start"], x["end"]))
    for i, bt in enumerate(beats, 1):
        bt["id"] = f"E{num:02d}-B{i:03d}"
    ep["beats"] = beats
    ep["duration"] = max([b["end"] for b in ep["blocks"]] + [s["end"] or 0 for s in ep["scenes"]])
    return ep


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    out = Path("data/parsed"); out.mkdir(parents=True, exist_ok=True)
    files = sorted(src.rglob("episode-*.txt"))
    print(f"found {len(files)} files")
    print("ep  dur(s)  dialog beats scenes  warnings")
    for f in files:
        ep = parse_episode(f)
        (out / f"ep{ep['episode']:02d}.json").write_text(json.dumps(ep, indent=1))
        nd = sum(b["kind"] == "dialogue" for b in ep["beats"])
        print(f"{ep['episode']:>2}  {ep['duration']:>6.1f}  {nd:>6} {len(ep['beats']):>5} {len(ep['scenes']):>6}  {len(ep['warnings'])}")