"""Admin/QA endpoints — no auth. Used to eyeball product-match quality."""
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from supabase import Client
from api.deps import get_supabase

router = APIRouter()


def _load_matched_listings(sb: Client) -> list[dict]:
    rows, page, PAGE = [], 0, 1000
    while True:
        chunk = (
            sb.table("listings")
            .select(
                "product_id, shop_id, raw_name, sku, price_usd, in_stock, product_url"
            )
            .not_.is_("product_id", "null")
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
    return rows


@router.get("/matches")
def list_matches(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sb: Client = Depends(get_supabase),
):
    cats = {c["id"]: c["name"] for c in sb.table("categories").select("id, name").execute().data}
    shops = {s["id"]: s["name"] for s in sb.table("shops").select("id, name").execute().data}
    prods = {
        p["id"]: p
        for p in sb.table("products").select("id, name, category_id").execute().data
    }

    rows = _load_matched_listings(sb)
    by_product: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_product[r["product_id"]].append(r)

    matches = []
    for pid, lst in by_product.items():
        prices = [r["price_usd"] for r in lst if r["price_usd"] is not None]
        prod = prods.get(pid, {})
        listings = sorted(
            (
                {
                    "shop": shops.get(r["shop_id"], "?"),
                    "raw_name": r["raw_name"],
                    "sku": r["sku"],
                    "price_usd": r["price_usd"],
                    "in_stock": r["in_stock"],
                    "product_url": r["product_url"],
                }
                for r in lst
            ),
            key=lambda x: (x["price_usd"] is None, x["price_usd"] or 0),
        )
        matches.append({
            "product_id": pid,
            "name": prod.get("name"),
            "category": cats.get(prod.get("category_id")),
            "shop_count": len({r["shop_id"] for r in lst}),
            "listing_count": len(lst),
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "listings": listings,
        })

    # most shops first, then most listings, then biggest price spread
    matches.sort(
        key=lambda m: (
            m["shop_count"],
            m["listing_count"],
            (m["max_price"] or 0) - (m["min_price"] or 0),
        ),
        reverse=True,
    )

    in_scope = (
        sb.table("listings")
        .select("id", count="exact")
        .not_.is_("category_slug", "null")
        .limit(1)
        .execute()
        .count
        or 0
    )

    return {
        "stats": {
            "matched_products": len(matches),
            "multi_shop_products": sum(1 for m in matches if m["shop_count"] >= 2),
            "matched_listings": len(rows),
            "in_scope_listings": in_scope,
            "coverage_pct": round(100 * len(rows) / in_scope, 1) if in_scope else 0,
        },
        "count": len(matches[offset : offset + limit]),
        "matches": matches[offset : offset + limit],
    }


@router.get("/match-queue")
def list_match_queue(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sb: Client = Depends(get_supabase),
):
    """Middle-band fuzzy candidates awaiting human confirm: the unmatched listing
    next to the existing product it might belong to, with the similarity score."""
    q = (
        sb.table("match_queue")
        .select("id, listing_id, candidate_product_id, similarity_score")
        .eq("status", "pending")
        .order("similarity_score", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
        .data
    )
    pending = (
        sb.table("match_queue").select("id", count="exact").eq("status", "pending").limit(1).execute().count
        or 0
    )
    if not q:
        return {"stats": {"pending": pending}, "count": 0, "items": []}

    shops = {s["id"]: s["name"] for s in sb.table("shops").select("id, name").execute().data}
    cat_names = {c["slug"]: c["name"] for c in sb.table("categories").select("slug, name").execute().data}
    cat_by_id = {c["id"]: c["name"] for c in sb.table("categories").select("id, name").execute().data}

    lids = [r["listing_id"] for r in q]
    pids = [r["candidate_product_id"] for r in q if r["candidate_product_id"]]

    lmap = {
        l["id"]: l
        for l in sb.table("listings")
        .select("id, raw_name, price_usd, in_stock, product_url, shop_id, category_slug")
        .in_("id", lids)
        .execute()
        .data
    }
    pmap = {
        p["id"]: p
        for p in sb.table("products").select("id, name, category_id").in_("id", pids).execute().data
    } if pids else {}
    plist: dict[str, list] = defaultdict(list)
    if pids:
        for l in (
            sb.table("listings")
            .select("raw_name, price_usd, shop_id, product_id")
            .in_("product_id", pids)
            .execute()
            .data
        ):
            plist[l["product_id"]].append(l)

    items = []
    for r in q:
        l = lmap.get(r["listing_id"], {})
        p = pmap.get(r["candidate_product_id"], {})
        items.append({
            "queue_id": r["id"],
            "score": r["similarity_score"],
            "listing": {
                "shop": shops.get(l.get("shop_id"), "?"),
                "raw_name": l.get("raw_name"),
                "price_usd": l.get("price_usd"),
                "in_stock": l.get("in_stock"),
                "product_url": l.get("product_url"),
                "category": cat_names.get(l.get("category_slug")),
            },
            "candidate": {
                "name": p.get("name"),
                "category": cat_by_id.get(p.get("category_id")),
                "listings": [
                    {
                        "shop": shops.get(x["shop_id"], "?"),
                        "raw_name": x["raw_name"],
                        "price_usd": x["price_usd"],
                    }
                    for x in plist.get(r["candidate_product_id"], [])
                ],
            },
        })

    return {"stats": {"pending": pending}, "count": len(items), "items": items}
