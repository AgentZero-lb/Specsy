"""Safely reverse match decisions — DRY RUN by default.

Undo a bad merge without losing data: un-links the affected listings (product_id -> NULL)
and stamps the match_decisions rows as reversed (status='reversed', reversed_at, reviewer,
note). It NEVER deletes listings, price_snapshots, scrape_runs, products, or the decision
history. Orphaned products are kept and reported.

Safety:
  * dry run unless --apply.
  * --product reverses every ACTIVE decision for that product; --decision reverses one.
  * A listing is only un-linked if it CURRENTLY points to the product being reversed —
    unrelated/newer links are preserved.

    cd backend && python scripts/unmatch.py --product <uuid>            # dry run
    cd backend && python scripts/unmatch.py --product <uuid> --apply --reviewer you --reason "bad merge"
    cd backend && python scripts/unmatch.py --decision <uuid> --apply
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.db import get_client   # noqa: E402

DECISIONS_TABLE = "match_decisions"


def plan_reversal(active_decisions: list, listing_product: dict) -> tuple[list, list, list]:
    """Pure planner. Given active decision rows [{id, listing_id, product_id}] and the
    CURRENT listing_id->product_id map, return:
      reverse_ids   : decision ids to mark reversed (all of them)
      unlink_ids    : listing ids to set product_id=NULL (only those still pointing here)
      preserved     : (listing_id, current_product) skipped because re-linked elsewhere
    """
    reverse_ids, unlink_ids, preserved = [], [], []
    for d in active_decisions:
        reverse_ids.append(d["id"])
        cur = listing_product.get(d["listing_id"], "__missing__")
        if cur == d["product_id"]:
            unlink_ids.append(d["listing_id"])
        elif cur not in (None, "__missing__"):
            preserved.append((d["listing_id"], cur))
    return reverse_ids, unlink_ids, preserved


def _fetch_active(sb, product_id, decision_id):
    q = sb.table(DECISIONS_TABLE).select("id, listing_id, product_id").eq("status", "active")
    if decision_id:
        q = q.eq("id", decision_id)
    else:
        q = q.eq("product_id", product_id)
    return q.execute().data or []


def _listing_products(sb, listing_ids):
    out = {}
    for k in range(0, len(listing_ids), 200):
        chunk = listing_ids[k:k + 200]
        rows = sb.table("listings").select("id, product_id").in_("id", chunk).execute().data or []
        for r in rows:
            out[r["id"]] = r["product_id"]
    return out


def run(product_id, decision_id, apply, reviewer, reason):
    if not product_id and not decision_id:
        raise SystemExit("specify --product <uuid> or --decision <uuid>")
    if apply and (not reviewer or not reason):
        raise SystemExit("applied unmatch requires --reviewer and --reason (provenance)")
    sb = get_client()

    active = _fetch_active(sb, product_id, decision_id)
    if not active:
        print("no ACTIVE decisions match the target — nothing to reverse.")
        return
    listing_ids = [d["listing_id"] for d in active]
    listing_product = _listing_products(sb, listing_ids)
    reverse_ids, unlink_ids, preserved = plan_reversal(active, listing_product)

    products = {d["product_id"] for d in active}
    print(f"target: {'decision ' + decision_id if decision_id else 'product ' + product_id}")
    print(f"active decisions to reverse : {len(reverse_ids)}")
    print(f"listings to un-link         : {len(unlink_ids)}")
    print(f"links preserved (re-linked elsewhere): {len(preserved)}")
    for lid, cur in preserved[:10]:
        print(f"    keep listing {lid} -> {cur}")

    if not apply:
        print("\nDRY RUN — no writes. Re-run with --apply to reverse.")
        return

    now = datetime.now(timezone.utc).isoformat()
    note = (reason or "manual unmatch")
    # 1) un-link listings (NEVER delete listing/price rows)
    for k in range(0, len(unlink_ids), 200):
        sb.table("listings").update({"product_id": None}).in_(
            "id", unlink_ids[k:k + 200]).execute()
    # 2) stamp decision provenance (history kept, status flipped)
    for k in range(0, len(reverse_ids), 200):
        sb.table(DECISIONS_TABLE).update({
            "status": "reversed", "reversed_at": now,
            "reviewed_at": now, "reviewer": reviewer, "note": note,
        }).in_("id", reverse_ids[k:k + 200]).execute()

    # report orphaned products (kept, not deleted)
    for pid in products:
        remaining = (sb.table("listings").select("id", count="exact")
                     .eq("product_id", pid).limit(1).execute().count) or 0
        flag = "  <- ORPHANED (kept)" if remaining == 0 else ""
        print(f"product {pid}: {remaining} listings remain{flag}")
    print(f"\nReversed {len(reverse_ids)} decisions, un-linked {len(unlink_ids)} listings. "
          f"No listing/price/product rows deleted.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", help="reverse all active decisions for this product uuid")
    ap.add_argument("--decision", help="reverse a single decision uuid")
    ap.add_argument("--apply", action="store_true", help="perform the reversal (default: dry run)")
    ap.add_argument("--reviewer", default=None, help="who is reversing (provenance)")
    ap.add_argument("--reason", default=None, help="why (provenance note)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.product, args.decision, args.apply, args.reviewer, args.reason)
