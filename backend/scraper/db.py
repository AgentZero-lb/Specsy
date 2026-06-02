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


def upsert_listings(sb: Client, shop_id: str, listings: list[dict]) -> list[dict]:
    """Upsert in batches of 500; return the upserted rows (each incl. its `id`)."""
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


def get_today_rate(sb: Client) -> Optional[float]:
    result = (
        sb.table("exchange_rates")
        .select("usd_to_lbp")
        .eq("date", date.today().isoformat())
        .maybe_single()
        .execute()
    )
    return result.data["usd_to_lbp"] if result and result.data else None
