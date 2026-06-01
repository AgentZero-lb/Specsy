from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client
from api.deps import get_supabase

router = APIRouter()


class ShopOut(BaseModel):
    slug: str
    name: str
    url: str


class ListingOut(BaseModel):
    id: str
    raw_name: str
    sku: Optional[str]
    price_usd: Optional[float]
    price_raw: Optional[float]
    currency: str
    in_stock: bool
    product_url: str
    image_url: Optional[str]
    category_slug: Optional[str]
    shop: ShopOut


class ListingsPage(BaseModel):
    items: list[ListingOut]
    total: int
    page: int
    pages: int


class CategoryCount(BaseModel):
    slug: str
    name: str
    count: int


@router.get("", response_model=ListingsPage)
def list_listings(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    in_stock: Optional[bool] = Query(None, description="Filter by stock status"),
    has_price: Optional[bool] = Query(None, description="True = priced only, False = Request Price only"),
    q: Optional[str] = Query(None, description="Search by name (case-insensitive)"),
    page: int = Query(1, ge=1),
    limit: int = Query(48, ge=1, le=200),
    sb: Client = Depends(get_supabase),
):
    offset = (page - 1) * limit

    query = (
        sb.table("listings")
        .select("id, raw_name, sku, price_usd, price_raw, currency, in_stock, product_url, image_url, category_slug, shops(slug, name, url)", count="exact")
    )

    if category:
        query = query.eq("category_slug", category)
    if in_stock is not None:
        query = query.eq("in_stock", in_stock)
    if has_price is True:
        query = query.not_.is_("price_raw", "null")
    elif has_price is False:
        query = query.is_("price_raw", "null")
    if q:
        query = query.ilike("raw_name", f"%{q}%")

    result = query.order("raw_name").range(offset, offset + limit - 1).execute()

    items = []
    for row in result.data:
        shop_data = row.pop("shops")
        items.append(ListingOut(**row, shop=ShopOut(**shop_data)))

    total = result.count or 0
    pages = max(1, (total + limit - 1) // limit)

    return ListingsPage(items=items, total=total, page=page, pages=pages)


@router.get("/categories", response_model=list[CategoryCount])
def list_categories(sb: Client = Depends(get_supabase)):
    cats_result = sb.table("categories").select("slug, name").execute()
    cats = {c["slug"]: c["name"] for c in cats_result.data}

    counts_result = sb.rpc("get_category_counts", {}).execute()

    return [
        CategoryCount(
            slug=row["category_slug"],
            name=cats.get(row["category_slug"], row["category_slug"]),
            count=row["count"],
        )
        for row in counts_result.data
    ]


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: str, sb: Client = Depends(get_supabase)):
    result = (
        sb.table("listings")
        .select("id, raw_name, sku, price_usd, price_raw, currency, in_stock, product_url, image_url, category_slug, shops(slug, name, url)")
        .eq("id", listing_id)
        .maybe_single()
        .execute()
    )

    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Listing not found")

    row = result.data
    shop_data = row.pop("shops")
    return ListingOut(**row, shop=ShopOut(**shop_data))
