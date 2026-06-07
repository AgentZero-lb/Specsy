import type {
  CategoryCount,
  Listing,
  ListingQuery,
  ListingsPage,
  ProductDetail,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function buildQuery(params: ListingQuery): string {
  const sp = new URLSearchParams();
  if (params.category) sp.set("category", params.category);
  if (params.in_stock !== undefined) sp.set("in_stock", String(params.in_stock));
  if (params.has_price !== undefined)
    sp.set("has_price", String(params.has_price));
  if (params.q) sp.set("q", params.q);
  if (params.sort) sp.set("sort", params.sort);
  if (params.page) sp.set("page", String(params.page));
  if (params.limit) sp.set("limit", String(params.limit));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** GET /listings — paginated, filterable, sortable. */
export async function getListings(
  params: ListingQuery = {},
  init?: RequestInit,
): Promise<ListingsPage> {
  const res = await fetch(`${API_URL}/listings${buildQuery(params)}`, init);
  if (!res.ok) throw new Error(`getListings ${res.status}`);
  return res.json();
}

/** GET /listings/{id} — returns null on 404. */
export async function getListing(
  id: string,
  init?: RequestInit,
): Promise<Listing | null> {
  const res = await fetch(`${API_URL}/listings/${id}`, init);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`getListing ${res.status}`);
  return res.json();
}

/**
 * GET /products/{id}/listings — a canonical product + all linked shop listings,
 * ranked cheapest first. Returns null on 404 (product gone / not matched).
 */
export async function getProductListings(
  productId: string,
  init?: RequestInit,
): Promise<ProductDetail | null> {
  const res = await fetch(`${API_URL}/products/${productId}/listings`, init);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`getProductListings ${res.status}`);
  return res.json();
}

/**
 * GET /listings/categories — 24 categories with counts.
 * Backed by a slow Supabase RPC, so cache for 12h (data refreshes every 12h).
 */
export async function getCategories(
  init?: RequestInit,
): Promise<CategoryCount[]> {
  const res = await fetch(
    `${API_URL}/listings/categories`,
    init ?? { next: { revalidate: 43_200 } },
  );
  if (!res.ok) throw new Error(`getCategories ${res.status}`);
  return res.json();
}
