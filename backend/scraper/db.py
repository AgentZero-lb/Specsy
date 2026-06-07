import os
from datetime import date
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def ensure_shop(sb: Client, meta: dict) -> str:
    """Upsert shop row, return its UUID."""
    result = (
        sb.table("shops")
        .upsert(meta, on_conflict="slug")
        .execute()
    )
    return result.data[0]["id"]


def start_scrape_run(sb: Client, shop_id: str) -> str:
    result = (
        sb.table("scrape_runs")
        .insert({"shop_id": shop_id, "status": "running"})
        .execute()
    )
    return result.data[0]["id"]


def finish_scrape_run(
    sb: Client,
    run_id: str,
    status: str,
    products_found: int = 0,
    products_upserted: int = 0,
    error: Optional[str] = None,
):
    sb.table("scrape_runs").update(
        {
            "status": status,
            "products_found": products_found,
            "products_upserted": products_upserted,
            "error": error,
            "finished_at": "now()",
        }
    ).eq("id", run_id).execute()


def _has_column(sb: Client, table: str, col: str) -> bool:
    """Cheap probe: PostgREST errors on selecting an unknown column."""
    try:
        sb.table(table).select(col).limit(1).execute()
        return True
    except Exception:
        return False


def upsert_listings(sb: Client, shop_id: str, listings: list[dict]) -> list[dict]:
    """Upsert in batches of 500; return the upserted rows (each incl. its `id`).

    Forward-compatible with the `raw_specs` column: if the migration hasn't been
    applied yet, we strip the field so saves don't hard-fail (never overwrite on error).
    """
    if listings and "raw_specs" in listings[0] and not _has_column(sb, "listings", "raw_specs"):
        print("  note: listings.raw_specs column not found — run migration 002; "
              "saving without specs for now.")
        listings = [{k: v for k, v in r.items() if k != "raw_specs"} for r in listings]

    BATCH = 500
    rows: list[dict] = []
    for i in range(0, len(listings), BATCH):
        batch = listings[i : i + BATCH]
        result = (
            sb.table("listings")
            .upsert(batch, on_conflict="shop_id,product_url")
            .execute()
        )
        rows.extend(result.data)
    return rows


def upsert_price_snapshots(sb: Client, run_id: str, upserted_rows: list[dict]) -> int:
    """Write one price_snapshot per upserted listing; return the count.

    Builds snapshots from the rows returned by upsert_listings (which already
    carry their `id`), so it is NOT subject to PostgREST's default ~1000-row
    cap that a re-fetch by scrape_run_id would silently hit.
    """
    snapshots = [
        {
            "listing_id":    r["id"],
            "scrape_run_id": run_id,
            "price_raw":     r["price_raw"],
            "currency":      r["currency"],
            "price_usd":     r["price_usd"],
            "in_stock":      r["in_stock"],
        }
        for r in upserted_rows
    ]

    BATCH = 500
    for i in range(0, len(snapshots), BATCH):
        sb.table("price_snapshots").insert(snapshots[i : i + BATCH]).execute()
    return len(snapshots)


def plan_missing_listings(
    existing_ids: set[str],
    seen_ids: set[str],
    minimum_coverage: float = 0.8,
) -> list[str]:
    """Return stored listings absent from a healthy full-catalog scrape.

    The coverage guard prevents a partial-but-nonzero scrape from marking most of
    a shop unavailable. Callers keep every row and mapping; only stock is changed.
    """
    if not existing_ids:
        return []
    coverage = len(existing_ids & seen_ids) / len(existing_ids)
    if coverage < minimum_coverage:
        return []
    return sorted(existing_ids - seen_ids)


def mark_missing_listings_unavailable(
    sb: Client,
    shop_id: str,
    seen_ids: set[str],
    minimum_coverage: float = 0.8,
) -> int:
    """Mark listings absent from a successful full scrape out of stock.

    Rows, prices, history, and product_id mappings are preserved. Only in-scope
    rows are considered; scope cleanup owns category_slug=NULL records.
    """
    existing_ids: set[str] = set()
    page, page_size = 0, 1000
    while True:
        rows = (
            sb.table("listings")
            .select("id")
            .eq("shop_id", shop_id)
            .not_.is_("category_slug", "null")
            .range(page * page_size, page * page_size + page_size - 1)
            .execute()
            .data
            or []
        )
        existing_ids.update(row["id"] for row in rows)
        if len(rows) < page_size:
            break
        page += 1

    missing_ids = plan_missing_listings(existing_ids, seen_ids, minimum_coverage)
    for start in range(0, len(missing_ids), 200):
        sb.table("listings").update({"in_stock": False}).in_(
            "id", missing_ids[start:start + 200]
        ).execute()
    return len(missing_ids)


def get_today_rate(sb: Client) -> Optional[float]:
    result = (
        sb.table("exchange_rates")
        .select("usd_to_lbp")
        .eq("date", date.today().isoformat())
        .maybe_single()
        .execute()
    )
    return result.data["usd_to_lbp"] if result and result.data else None
