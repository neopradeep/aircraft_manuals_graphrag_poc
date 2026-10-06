"""List models visible to your key on the configured provider, plus a live check of the configured chat + embedding models.
  make models            # list (filter with: make models F=embed)
"""
import sys, time
from . import common as C

flt = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
c = C._client()
ids = sorted(m.id for m in c.models.list())
print(f"{len(ids)} models visible")
for i in ids:
    if flt in i.lower():
        print(" ", i)
print(f"\nConfigured chat model:  {C.CHAT_MODEL}")
print(f"Configured embed model: {C.EMBED_MODEL} (EMBED_DIM={C.EMBED_DIM})")
t0 = time.time()
try:
    r = c.chat.completions.create(model=C.CHAT_MODEL, response_format={"type": "json_object"},
                                  messages=[{"role": "user", "content": 'Reply with JSON {"ok": true}'}])
    print(f"chat + JSON mode: OK in {time.time()-t0:.1f}s ->", r.choices[0].message.content.strip(), "| completion tokens:", r.usage.completion_tokens)
except Exception as e:
    print("chat check FAILED:", str(e)[:300])
t0 = time.time()
try:
    d = c.embeddings.create(model=C.EMBED_MODEL, input=["test"]).data[0].embedding
    print(f"embeddings: OK in {time.time()-t0:.1f}s, returned {len(d)} dims", "(matches EMBED_DIM)" if len(d) == C.EMBED_DIM else f"(MISMATCH - set EMBED_DIM={len(d)})")
except Exception as e:
    print("embedding check FAILED:", str(e)[:300])
