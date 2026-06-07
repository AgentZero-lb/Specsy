"""Public product endpoints — a canonical product and every shop listing linked to it.

This is what the listing detail page calls once it knows a listing is matched
(`listings.product_id` is set). The single canonical product is shown once, then
its listings are ranked so the cheapest in-stock deal is first.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client
from api.deps import get_supabase
from api.routers.listings import ShopOut

router = APIRouter()


class ProductInfo(BaseModel):
    id: str
    name: str
    brand: Optional[str]          # often null — _ensure_product doesn't set it yet
    category_slug: Optional[str]
    category_name: Optional[str]
    image_url: Optional[str]      # best image found across the product's listings (products store none)


class ProductListingOut(BaseModel):
    id: str
    raw_name: str
    sku: Optional[str]
    price_usd: Optional[float]
    price_raw: Optional[float]
    currency: str
    in_stock: bool
    product_url: str
    image_url: Optional[str]
    last_seen_at: Optional[str]
    shop: ShopOut


class ProductDetailOut(BaseModel):
    product: ProductInfo
    listings: list[ProductListingOut]


def _rank_key(row: dict):
    """Cheapest in-stock deal first, then out-of-stock priced, then Request-Price (null) last."""
    return (row["price_usd"] is None, not row["in_stock"], row["price_usd"] or 0)


@router.get("/{product_id}/listings", response_model=ProductDetailOut)
def get_product_listings(product_id: str, sb: Client = Depends(get_supabase)):
    prod = (
        sb.table("products")
        .select("id, name, brand, category_id, categories(slug, name)")
        .eq("id", product_id)
        .maybe_single()
        .execute()
    )
    if not prod or not prod.data:
        raise HTTPException(status_code=404, detail="Product not found")

    cat = prod.data.get("categories") or {}

    rows = (
        sb.table("listings")
        .select(
            "id, raw_name, sku, price_usd, price_raw, currency, in_stock, "
            "product_url, image_url, last_seen_at, shops(slug, name, url)"
        )
        .eq("product_id", product_id)
        .execute()
        .data
    )
    rows.sort(key=_rank_key)

    listings, best_image = [], None
    for row in rows:
        shop_data = row.pop("shops")
        if best_image is None and row.get("image_url"):
            best_image = row["image_url"]
        listings.append(ProductListingOut(**row, shop=ShopOut(**shop_data)))

    product = ProductInfo(
        id=prod.data["id"],
        name=prod.data["name"],
        brand=prod.data.get("brand"),
        category_slug=cat.get("slug"),
        category_name=cat.get("name"),
        image_url=best_image,
    )
    return ProductDetailOut(product=product, listings=listings)
