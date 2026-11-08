import hashlib, json, os, re, time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import openai

load_dotenv()
CACHE = Path(".cache/llm"); CACHE.mkdir(parents=True, exist_ok=True)
_client = None
_last = 0.0


def client():
    global _client
    if _client is None:
        _client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], timeout=120, max_retries=0)
    return _client


def default_model():
    return os.environ["LLM_MODEL"]


def _extract_json(s):
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip())
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return json.loads(re.search(r"\{.*\}", s, re.S).group(0))


def _transient(e):
    """Retry rate limits, timeouts and server errors; fail fast on bad model name / key / request."""
    return isinstance(e, (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError))


@retry(retry=retry_if_exception(_transient), stop=stop_after_attempt(6),
       wait=wait_exponential(multiplier=2, min=2, max=60), reraise=True)
def _call(model, messages, temperature):
    global _last
    gap = float(os.environ.get("LLM_MIN_INTERVAL", "0"))   # seconds between calls, for free-tier RPM limits
    if gap: time.sleep(max(0, _last + gap - time.time()))
    _last = time.time()
    r = client().chat.completions.create(model=model, messages=messages, temperature=temperature)
    return r.choices[0].message.content or ""


def chat_json(system, user, temperature=0.2, model=None):
    """Cached JSON chat. Same (model, prompt) is never paid for twice, so reruns are free and crashes lose nothing."""
    model = model or default_model()
    key = hashlib.sha256(json.dumps([model, system, user, temperature]).encode()).hexdigest()[:24]
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    msg, raw = user, ""
    for _ in range(3):
        raw = _call(model, [{"role": "system", "content": system}, {"role": "user", "content": msg}], temperature)
        try:
            out = _extract_json(raw)
            f.write_text(json.dumps(out))
            return out
        except Exception:
            msg = user + "\n\nReturn ONLY valid JSON, no prose, no code fences."
    raise ValueError(f"model never returned valid JSON: {raw[:200]}")