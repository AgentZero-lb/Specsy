"""
Usage:
    python scraper/runner.py              # dry-run: fetch + print stats, no DB writes
    python scraper/runner.py --save       # fetch + upsert to Supabase (needs .env)
"""

import argparse
import sys
from scraper.shops.pcandparts import fetch_all, SHOP_META


def run_dry():
    print("=== DRY RUN - PCandParts ===\n")
    listings = fetch_all(verbose=True)

    if not listings:
        print("\nABORTED: 0 products returned. Not safe to overwrite DB.")
        sys.exit(1)

    priced      = [l for l in listings if l.price_raw is not None]
    req_price   = [l for l in listings if l.price_raw is None]
    in_stock    = [l for l in listings if l.in_stock]
    no_sku      = [l for l in listings if l.sku is None]
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


def run_save():
    from scraper.db import (
        get_client,
        ensure_shop,
        start_scrape_run,
        finish_scrape_run,
        upsert_listings,
        get_today_rate,
    )

    print("=== SCRAPE + SAVE - PCandParts ===\n")
    sb = get_client()

    shop_id = ensure_shop(sb, SHOP_META)
    run_id  = start_scrape_run(sb, shop_id)
    print(f"Shop ID   : {shop_id}")
    print(f"Run ID    : {run_id}\n")

    try:
        listings = fetch_all(verbose=True)
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

    rows = []
    for l in listings:
        price_usd = None
        if l.price_raw is not None:
            if l.currency == "USD":
                price_usd = l.price_raw
            elif l.currency == "LBP" and rate:
                price_usd = round(l.price_raw / rate, 2)

        rows.append({
            "shop_id":       shop_id,
            "scrape_run_id": run_id,
            "product_id":    None,
            "raw_name":      l.raw_name,
            "sku":           l.sku,
            "price_raw":     l.price_raw,
            "currency":      l.currency,
            "price_usd":     price_usd,
            "in_stock":      l.in_stock,
            "product_url":   l.product_url,
            "image_url":     l.image_url,
            "category_slug": l.category_slug,
            "last_seen_at":  "now()",
        })

    upserted = upsert_listings(sb, shop_id, rows)

    # write price snapshot for every listing this run
    from scraper.db import upsert_price_snapshots
    upsert_price_snapshots(sb, run_id, rows)

    finish_scrape_run(sb, run_id, "ok",
                      products_found=len(listings),
                      products_upserted=upserted)

    print(f"\nDone. {len(listings)} fetched, {upserted} upserted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true",
                        help="Write results to Supabase (requires .env)")
    args = parser.parse_args()

    if args.save:
        run_save()
    else:
        run_dry()
