"""
Usage (run from the backend/ directory):
    python -m scraper.runner [shop]            # dry-run: fetch + print stats, no DB writes
    python -m scraper.runner [shop] --save     # fetch + upsert to Supabase (needs .env)

    [shop] defaults to 'pcandparts'.
    Available shops: pcandparts, macrotronics, ayoub
"""

import argparse
import importlib
import sys

# slug -> module path. Each module must expose `fetch_all()` and `SHOP_META`.
SHOPS = {
    "pcandparts":   "scraper.shops.pcandparts",
    "macrotronics": "scraper.shops.macrotronics",
    "ayoub":        "scraper.shops.ayoub",
}


def load_shop(slug: str):
    if slug not in SHOPS:
        print(f"Unknown shop '{slug}'. Available: {', '.join(SHOPS)}")
        sys.exit(2)
    return importlib.import_module(SHOPS[slug])


def run_dry(shop):
    name = shop.SHOP_META["name"]
    print(f"=== DRY RUN - {name} ===\n")
    listings = shop.fetch_all(verbose=True)

    if not listings:
        print("\nABORTED: 0 products returned. Not safe to overwrite DB.")
        sys.exit(1)

    priced       = [l for l in listings if l.price_raw is not None]
    req_price    = [l for l in listings if l.price_raw is None]
    in_stock     = [l for l in listings if l.in_stock]
    no_sku       = [l for l in listings if l.sku is None]
    out_of_scope = [l for l in listings if l.category_slug is None]

    cats: dict[str, int] = {}
    for l in listings:
        key = l.category_slug or "(out of scope)"
        cats[key] = cats.get(key, 0) + 1

    print(f"\n{'-'*40}")
    print(f"  Total products   : {len(listings)}")
    print(f"  Has price        : {len(priced)}")
    print(f"  Request Price    : {len(req_price)}")
    print(f"  In stock         : {len(in_stock)}")
    print(f"  Missing SKU      : {len(no_sku)}")
    print(f"  Out of scope     : {len(out_of_scope)}")
    print(f"\n  Categories:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat:<20} {count}")
    print(f"{'-'*40}")
    print("\nDry run complete. Run with --save to write to DB.")


def run_save(shop):
    from scraper.db import (
        get_client,
        ensure_shop,
        start_scrape_run,
        finish_scrape_run,
        upsert_listings,
        get_today_rate,
        mark_missing_listings_unavailable,
        upsert_price_snapshots,
    )

    name = shop.SHOP_META["name"]
    print(f"=== SCRAPE + SAVE - {name} ===\n")
    sb = get_client()

    shop_id = ensure_shop(sb, shop.SHOP_META)
    run_id  = start_scrape_run(sb, shop_id)
    print(f"Shop ID   : {shop_id}")
    print(f"Run ID    : {run_id}\n")

    try:
        listings = shop.fetch_all(verbose=True)
    except Exception as e:
        finish_scrape_run(sb, run_id, "failed", error=str(e))
        print(f"\nERROR: {e}")
        sys.exit(1)

    if not listings:
        finish_scrape_run(sb, run_id, "aborted", products_found=0,
                          error="scraper returned 0 products")
        print("\nABORTED: 0 products — existing DB data preserved.")
        sys.exit(1)

    rate = get_today_rate(sb)

    # Drop out-of-scope listings (category_slug is None): cables, toners, adapters,
    # software, etc. We never show them, so don't store them or snapshot their prices.
    in_scope = [l for l in listings if l.category_slug is not None]
    skipped = len(listings) - len(in_scope)

    rows = []
    for l in in_scope:
        price_usd = None
        if l.price_raw is not None:
            if l.currency == "USD":
                price_usd = l.price_raw
            elif l.currency == "LBP" and rate:
                price_usd = round(l.price_raw / rate, 2)

        rows.append({
            "shop_id":       shop_id,
            "scrape_run_id": run_id,
            # NB: do NOT write product_id here. On upsert-conflict PostgREST only updates
            # the columns we send, so omitting it PRESERVES matches across re-scrapes
            # (new listings still default to NULL). Writing None would wipe matching every run.
            "raw_name":      l.raw_name,
            "sku":           l.sku,
            "price_raw":     l.price_raw,
            "currency":      l.currency,
            "price_usd":     price_usd,
            "in_stock":      l.in_stock,
            "product_url":   l.product_url,
            "image_url":     l.image_url,
            "category_slug": l.category_slug,
            # only Ayoub's Listing carries specs; other shops default to {}
            "raw_specs":     getattr(l, "raw_specs", None) or {},
            "last_seen_at":  "now()",
        })

    upserted_rows = upsert_listings(sb, shop_id, rows)

    # one price snapshot per listing, using ids from the upsert (no row cap)
    snapshots = upsert_price_snapshots(sb, run_id, upserted_rows)
    unavailable = mark_missing_listings_unavailable(
        sb, shop_id, {row["id"] for row in upserted_rows}
    )

    finish_scrape_run(sb, run_id, "ok",
                      products_found=len(listings),
                      products_upserted=len(upserted_rows))

    print(f"\nDone. {len(listings)} fetched, {skipped} out-of-scope skipped, "
          f"{len(upserted_rows)} upserted, {snapshots} snapshots, "
          f"{unavailable} missing listings marked out of stock.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("shop", nargs="?", default="pcandparts",
                        help="Shop slug: " + ", ".join(SHOPS))
    parser.add_argument("--save", action="store_true",
                        help="Write results to Supabase (requires .env)")
    args = parser.parse_args()

    shop = load_shop(args.shop)
    if args.save:
        run_save(shop)
    else:
        run_dry(shop)
