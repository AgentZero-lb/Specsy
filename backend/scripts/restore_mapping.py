"""Restore listing->product mappings from a backup CSV — DRY RUN by default.

Second recovery layer (after the atomic activate_rebuild): re-apply any mapping snapshot
written by scraper.match's export (backups/mapping_*.csv) — e.g. to roll back a rebuild.
Only updates listings.product_id; NEVER deletes listings, prices, or products.

    cd backend && python scripts/restore_mapping.py backups/mapping_<ts>.csv
    cd backend && python scripts/restore_mapping.py backups/mapping_<ts>.csv --apply
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.db import get_client   # noqa: E402


def read_mapping(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return [{"listing_id": r["listing_id"], "product_id": (r.get("product_id") or "").strip() or None}
                for r in csv.DictReader(f)]


def plan_restore(rows: list, current: dict) -> list:
    """Pure planner. rows: backup [{listing_id, product_id}]; current: live
    {listing_id->product_id}. Returns [(listing_id, target_product_id)] needing a change."""
    changes = []
    for r in rows:
        target = r["product_id"]
        cur = current.get(r["listing_id"], "__missing__")
        if cur != "__missing__" and cur != target:
            changes.append((r["listing_id"], target))
    return changes


def _current(sb, listing_ids):
    out = {}
    for k in range(0, len(listing_ids), 200):
        chunk = listing_ids[k:k + 200]
        rows = sb.table("listings").select("id, product_id").in_("id", chunk).execute().data or []
        for r in rows:
            out[r["id"]] = r["product_id"]
    return out


def run(path: str, apply: bool):
    rows = read_mapping(path)
    sb = get_client()
    current = _current(sb, [r["listing_id"] for r in rows])
    changes = plan_restore(rows, current)
    relink = sum(1 for _, t in changes if t)
    unlink = sum(1 for _, t in changes if not t)
    print(f"backup rows           : {len(rows)}")
    print(f"listings to change    : {len(changes)}  (relink {relink}, unlink {unlink})")
    if not apply:
        print("\nDRY RUN — no writes. Re-run with --apply to restore.")
        return
    by_target = {}
    for lid, t in changes:
        by_target.setdefault(t, []).append(lid)
    for target, ids in by_target.items():
        for k in range(0, len(ids), 200):
            sb.table("listings").update({"product_id": target}).in_(
                "id", ids[k:k + 200]).execute()
    print(f"Restored {len(changes)} listing mappings (no rows deleted).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="backups/mapping_<ts>.csv")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.csv_path, args.apply)
