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


def upsert_listings(sb: Client, shop_id: str, listings: list[dict]) -> int:
    """Upsert in batches of 500, return total rows upserted."""
    BATCH = 500
    total = 0
    for i in range(0, len(listings), BATCH):
        batch = listings[i : i + BATCH]
        result = (
            sb.table("listings")
            .upsert(batch, on_conflict="shop_id,product_url")
            .execute()
        )
        total += len(result.data)
    return total


def upsert_price_snapshots(sb: Client, run_id: str, listing_rows: list[dict]):
    """After upserting listings, fetch their IDs and write price_snapshots."""
    # fetch listing IDs for this run
    result = (
        sb.table("listings")
        .select("id, product_url, price_raw, currency, price_usd, in_stock")
        .eq("scrape_run_id", run_id)
        .execute()
    )
    listing_map = {r["product_url"]: r for r in result.data}

    snapshots = []
    for row in listing_rows:
        listing = listing_map.get(row["product_url"])
        if not listing:
            continue
        snapshots.append({
            "listing_id":    listing["id"],
            "scrape_run_id": run_id,
            "price_raw":     listing["price_raw"],
            "currency":      listing["currency"],
            "price_usd":     listing["price_usd"],
            "in_stock":      listing["in_stock"],
        })

    BATCH = 500
    for i in range(0, len(snapshots), BATCH):
        sb.table("price_snapshots").insert(snapshots[i : i + BATCH]).execute()


def get_today_rate(sb: Client) -> Optional[float]:
    result = (
        sb.table("exchange_rates")
        .select("usd_to_lbp")
        .eq("date", date.today().isoformat())
        .maybe_single()
        .execute()
    )
    return result.data["usd_to_lbp"] if result and result.data else None
