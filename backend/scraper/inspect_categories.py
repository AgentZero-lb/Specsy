"""One-shot script: print all WooCommerce category slugs + counts across full catalog."""
import html
import httpx
from collections import Counter

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
API = "https://pcandparts.com/wp-json/wc/store/v1/products"

cats: Counter = Counter()
page = 1

with httpx.Client(headers=HEADERS, timeout=20) as client:
    while True:
        resp = client.get(API, params={"per_page": 100, "page": page})
        if resp.status_code != 200 or not resp.content:
            break
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            for c in p.get("categories", []):
                cats[(c["slug"], html.unescape(c["name"]))] += 1
        print(f"  page {page}: {len(batch)} products", flush=True)
        if len(batch) < 100:
            break
        page += 1

print()
print(f"{'Slug':<45} {'Name':<35} {'Count':>5}")
print("-" * 87)
for (slug, name), count in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"{slug:<45} {name:<35} {count:>5}")
