"""Probe Voyage rate/size limits so we can batch correctly.
    python -m scraper.diag_voyage   (run from backend/)
"""
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()
key = (os.environ.get("VOYAGE_API_KEY") or "").strip()
print("key present:", bool(key))
URL = "https://api.voyageai.com/v1/embeddings"
H = {"Authorization": f"Bearer {key}"}


def call(n):
    texts = [f"Test gaming laptop model {i} i7 16GB 512GB SSD RTX 4060" for i in range(n)]
    t0 = time.time()
    r = httpx.post(URL, headers=H, json={"input": texts, "model": "voyage-3", "input_type": "document"}, timeout=90)
    dt = time.time() - t0
    rl = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or "retry" in k.lower()}
    print(f"  n={n:<5} status={r.status_code}  {dt:.1f}s  ratelimit_hdrs={rl}")
    if r.status_code != 200:
        print(f"        body: {r.text[:200]}")
    else:
        print(f"        usage: {r.json().get('usage')}")
    return r.status_code


# size probe
for n in (128, 256):
    call(n)
    time.sleep(1)

# RPM probe: fire 4 quick small requests back to back
print("RPM probe (4 quick calls):")
for i in range(4):
    call(64)
