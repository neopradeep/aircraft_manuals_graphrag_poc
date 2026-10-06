"""Shared config + thin Neo4j / OpenAI helpers (lazy imports so --dry-run needs only beautifulsoup4)."""
import os, json, hashlib, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
CHAT_MODEL = os.getenv("LLM_CHAT_MODEL") or os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("LLM_EMBED_MODEL") or os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))

VARIANTS = {
    "B737": {"A": "737-700", "B": "737-800", "C": "737-MAX8"},
    "A320": {"A": "A320ceo", "B": "A320neo", "C": "A321neo"},
}
PN_RE = re.compile(r"\b(?:\d{2,3}-\d{5}-\d{2}|D\d{9}00)\b")
CACHE = ROOT / "cache"


def get_driver():
    from neo4j import GraphDatabase
    if not NEO4J_PASSWORD:
        raise SystemExit("Set NEO4J_PASSWORD (env var or .env).")
    d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    d.verify_connectivity()
    return d


def _client():
    """Any OpenAI-compatible provider: set LLM_BASE_URL (+ LLM_API_KEY) for e.g. Fireworks; defaults to OpenAI."""
    from openai import OpenAI
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise SystemExit("Set LLM_API_KEY (or OPENAI_API_KEY) in .env.")
    return OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)


def _cfile(kind, payload):
    return CACHE / kind / (hashlib.sha256(payload.encode()).hexdigest() + ".json")


def _retry(fn, tries=4):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # rate limits / transient
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def embed(texts):
    out, todo = [None] * len(texts), []
    for i, t in enumerate(texts):
        f = _cfile("emb", EMBED_MODEL + "|" + t)
        if f.exists():
            out[i] = json.loads(f.read_text())
        else:
            todo.append(i)
    if todo:
        c = _client()
        for s in range(0, len(todo), 64):
            idx = todo[s:s + 64]
            r = _retry(lambda: c.embeddings.create(model=EMBED_MODEL, input=[texts[i] for i in idx]))
            for i, d in zip(idx, r.data):
                out[i] = d.embedding
                f = _cfile("emb", EMBED_MODEL + "|" + texts[i])
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(d.embedding))
    return out


def chat_json(system, user, cache=True):
    key = CHAT_MODEL + "|" + system + "|" + user
    f = _cfile("chat", key)
    if cache and f.exists():
        return json.loads(f.read_text())
    r = _retry(lambda: _client().chat.completions.create(
        model=CHAT_MODEL, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]))
    obj = json.loads(r.choices[0].message.content)
    if cache:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(obj))
    return obj
