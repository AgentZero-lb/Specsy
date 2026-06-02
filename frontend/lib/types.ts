// Mirrors the FastAPI response models (backend/api/routers/listings.py).
// Keep in sync if the API contract changes.

export interface Shop {
  slug: string;
  name: string;
  url: string;
}

export interface Listing {
  id: string;
  raw_name: string; // NOTE: the listing's display name is `raw_name`, not `name`
  sku: string | null;
  price_usd: number | null; // null = "Request Price"
  price_raw: number | null; // null = "Request Price"
  currency: string; // "USD" | "LBP" (all "USD" for the only live shop)
  in_stock: boolean;
  last_seen_at: string | null; // ISO timestamp — listing freshness
  product_url: string;
  image_url: string | null;
  category_slug: string | null;
  shop: Shop;
}

export interface ListingsPage {
  items: Listing[];
  total: number;
  page: number;
  pages: number;
}

export interface CategoryCount {
  slug: string;
  name: string;
  count: number; // total listings in the category (incl. Request-Price + out-of-stock)
}

export type SortOrder = "name" | "price_asc" | "price_desc";

export interface ListingQuery {
  category?: string;
  in_stock?: boolean;
  has_price?: boolean; // true = priced only · false = Request-Price only
  q?: string;
  sort?: SortOrder; // pair price_* with has_price: true
  page?: number;
  limit?: number;
}
