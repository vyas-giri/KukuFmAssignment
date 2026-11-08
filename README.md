# Kuku promo finder

Reads microdrama screenplays and finds 20–60s promo clips (hook in the first 3s, cliffhanger at the cut, makes sense on its own), then ranks them.

## How it works
1. `src/parse.py`: turns screenplay files into numbered **beats** (dialogue/action) with start/end seconds. Pure code, no AI.
2. `src/pipeline.py`: per episode:
   - **Propose** (1 LLM call): the model reads the beats and returns up to 3 promos as *beat IDs*. It never writes timestamps.
   - **Validate** (code): unknown IDs get rejected and out-of-range durations get refit by whole beats. Every issue goes to `outputs/validation_log_*.jsonl`.
   - **Judge** (1 LLM call): a separate, harsher prompt scores each real clip 1–10 on hook (it sees only the first 3s), cliffhanger (last beat) and standalone clarity.
3. `src/rank.py`: score = 0.35·hook + 0.35·cliff + 0.30·standalone (weights set in code). Removes overlapping duplicates and allows at most 2 per episode in the top 10.
4. `src/eval.py`: random 20–60s windows go through the same judge (baseline), plus a blind sheet of tool picks mixed with random clips that a human labels 1/0.

LLM responses are cached in `.cache/llm`, so reruns are free.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your key; any OpenAI-compatible endpoint works
python src/parse.py data/episodes        # folder containing episode-*.txt
python src/pipeline.py 1 50
python src/rank.py               # -> outputs/promos_ranked.md / .json
python src/eval.py baseline 30
python src/eval.py sheet 15      # label eval/labels.csv blind
python src/eval.py score         # -> outputs/eval_report.md
```
To swap the model, change `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` in `.env`.

## Limits
- Single continuous segments only. The output already uses a `segments` list, so cross-episode stitching can be added without changing the format.
- It reads only the screenplay and judges hooks from the text, so visual-only hooks are underrated.
- The judge is an LLM; its agreement with human labels is reported in `eval_report.md`.
