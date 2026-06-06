"""One-off: inspect SKU + raw_name data to design product matching.

    python -m scraper.diag_match     (run from backend/)
"""
from collections import defaultdict
from scraper.db import get_client

sb = get_client()
shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}

# load in-scope listings (category_slug not null), paginated past the 1000-row cap
rows, page, PAGE = [], 0, 1000
while True:
    chunk = (
        sb.table("listings")
        .select("id, shop_id, sku, raw_name, category_slug, product_id")
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

print(f"in-scope listings: {len(rows)}")

by_shop = defaultdict(list)
for r in rows:
    by_shop[shops.get(r["shop_id"], "?")].append(r)

for shop, lst in by_shop.items():
    have_sku = sum(1 for r in lst if (r["sku"] or "").strip())
    pct = 100 * have_sku // max(len(lst), 1)
    print(f"\n=== {shop}: {len(lst)} listings, {have_sku} with sku ({pct}%) ===")
    print("  sample raw_name:")
    for r in lst[:10]:
        print("   -", (r["raw_name"] or "")[:72])
    print("  sample sku:")
    shown = 0
    for r in lst:
        s = (r["sku"] or "").strip()
        if s:
            print(f"   - {s!r}  ({(r['raw_name'] or '')[:40]})")
            shown += 1
        if shown >= 8:
            break

# cross-shop SKU overlap (exact)
sku_shops = defaultdict(set)
sku_names = defaultdict(list)
for r in rows:
    s = (r["sku"] or "").strip()
    if s:
        shop = shops.get(r["shop_id"], "?")
        sku_shops[s].add(shop)
        sku_names[s].append((shop, (r["raw_name"] or "")[:38]))

cross = {k: v for k, v in sku_shops.items() if len(v) >= 2}
print(f"\n=== SKUs present in >=2 shops (exact): {len(cross)} ===")
for k in list(cross)[:20]:
    print(f"  sku={k!r} shops={sorted(cross[k])}")
    for shop, nm in sku_names[k][:4]:
        print(f"        [{shop[:4]}] {nm}")

matched = sum(1 for r in rows if r["product_id"])
print(f"\nlistings already matched (product_id set): {matched}")
