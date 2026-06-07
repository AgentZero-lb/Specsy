// Admin/QA view of product matches. No auth, intentionally plain.
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface MatchListing {
  shop: string;
  raw_name: string;
  sku: string | null;
  price_usd: number | null;
  in_stock: boolean;
  product_url: string;
}
interface Match {
  product_id: string;
  name: string | null;
  category: string | null;
  shop_count: number;
  listing_count: number;
  min_price: number | null;
  max_price: number | null;
  listings: MatchListing[];
}
interface MatchesResponse {
  stats: {
    matched_products: number;
    multi_shop_products: number;
    matched_listings: number;
    in_scope_listings: number;
    coverage_pct: number;
  };
  count: number;
  matches: Match[];
}

async function getMatches(): Promise<MatchesResponse> {
  const res = await fetch(`${API}/admin/matches?limit=500`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-hairline bg-surface p-3">
      <div className="text-xs text-faint">{label}</div>
      <div className="text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

export default async function AdminMatchesPage() {
  if (process.env.ENABLE_ADMIN_UI !== "true") notFound();

  let data: MatchesResponse;
  try {
    data = await getMatches();
  } catch (e) {
    return (
      <div className="p-8 font-mono text-sm text-warning">
        Failed to load matches from {API}: {String(e)}
        <div className="mt-2 text-faint">Is the backend running on :8000?</div>
      </div>
    );
  }

  const { stats, matches } = data;

  return (
    <div className="mx-auto max-w-5xl p-6 font-mono text-sm">
      <h1 className="mb-1 text-xl font-bold text-foreground">Product matches — QA</h1>
      <p className="mb-5 text-faint">
        Deterministic cross-shop matches (SKU + model/name). Showing {matches.length}.
      </p>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Matched products" value={stats.matched_products} />
        <Stat label="Multi-shop" value={stats.multi_shop_products} />
        <Stat label="Matched listings" value={stats.matched_listings} />
        <Stat label="Coverage" value={`${stats.coverage_pct}%`} />
      </div>

      <div className="flex flex-col gap-4">
        {matches.map((m) => {
          const spread =
            m.min_price != null && m.max_price != null
              ? m.max_price - m.min_price
              : 0;
          return (
            <div
              key={m.product_id}
              className="rounded-card border border-hairline bg-surface p-4"
            >
              <div className="mb-2 flex items-start justify-between gap-4">
                <div>
                  <span className="text-xs uppercase tracking-wide text-faint">
                    {m.category ?? "—"}
                  </span>
                  <div className="font-medium text-foreground">{m.name}</div>
                </div>
                <div className="shrink-0 text-right text-xs text-faint">
                  {m.shop_count} shops · {m.listing_count} listings
                  {spread > 0 && (
                    <div className="text-success">
                      spread ${spread.toFixed(2)}
                    </div>
                  )}
                </div>
              </div>

              <table className="w-full border-collapse">
                <tbody>
                  {m.listings.map((l, i) => (
                    <tr key={i} className="border-t border-hairline/50 align-top">
                      <td className="w-16 py-1 pr-3 text-muted">{l.shop}</td>
                      <td className="w-20 py-1 pr-3 text-foreground">
                        {l.price_usd != null ? `$${l.price_usd}` : "—"}
                      </td>
                      <td className="w-6 py-1 pr-3">
                        {l.in_stock ? (
                          <span className="text-success">✓</span>
                        ) : (
                          <span className="text-faint">·</span>
                        )}
                      </td>
                      <td className="py-1">
                        <a
                          href={l.product_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-muted transition-colors hover:text-accent-soft"
                        >
                          {l.raw_name}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </div>
  );
}
