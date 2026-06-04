"""One-off: null out the category_slug of already-stored listings whose title is
out of scope (CCTV coax, electrical, fire-safety, safes, etc. mis-filed into real
categories like camera/networking).

Setting category_slug = NULL — rather than deleting — keeps the row id and price
history intact and lets the API's "hide NULL category" filter suppress it. Fully
reversible by re-scraping (the scrapers now apply the same filter).

    python -m scraper.cleanup_scope            # dry run: report only
    python -m scraper.cleanup_scope --apply    # write category_slug = NULL
"""
import sys
from collections import Counter
from scraper.db import get_client
from scraper.scope import title_out_of_scope

apply = "--apply" in sys.argv
sb = get_client()
shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}

# pull all currently-categorised listings (NULLs are already hidden — skip them)
rows, page, PAGE = [], 0, 1000
while True:
    chunk = (
        sb.table("listings")
        .select("id, raw_name, category_slug, shop_id")
        .not_.is_("category_slug", "null")
        .range(page * PAGE, page * PAGE + PAGE - 1)
        .execute()
        .data
    )
    if not chunk:
        break
    rows.extend(chunk)
    if len(chunk) < PAGE:
        break
    page += 1

hits = [r for r in rows if title_out_of_scope(r["raw_name"])]

print(f"Scanned {len(rows)} categorised listings.")
print(f"Out-of-scope by title: {len(hits)}\n")

by_cat = Counter((shops.get(r["shop_id"], "?"), r["category_slug"]) for r in hits)
for (shop, cat), n in by_cat.most_common():
    print(f"  {shop:<14} {cat:<12} {n}")

print("\nSample:")
for r in hits[:40]:
    print(f"  [{shops.get(r['shop_id'],'?')[:4]}] {r['category_slug']:<10} {r['raw_name'][:60]}")

if not apply:
    print(f"\nDRY RUN — re-run with --apply to NULL these {len(hits)} listings.")
    sys.exit(0)

ids = [r["id"] for r in hits]
BATCH = 200
for i in range(0, len(ids), BATCH):
    batch = ids[i : i + BATCH]
    sb.table("listings").update({"category_slug": None}).in_("id", batch).execute()
print(f"\nApplied: set category_slug = NULL on {len(ids)} listings.")
