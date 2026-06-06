// Admin/QA review of middle-band fuzzy candidates. No auth, intentionally plain.
export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface CandListing {
  shop: string;
  raw_name: string;
  price_usd: number | null;
}
interface QueueItem {
  queue_id: string;
  score: number | null;
  listing: {
    shop: string;
    raw_name: string | null;
    price_usd: number | null;
    in_stock: boolean;
    product_url: string;
    category: string | null;
  };
  candidate: {
    name: string | null;
    category: string | null;
    listings: CandListing[];
  };
}
interface QueueResponse {
  stats: { pending: number };
  count: number;
  items: QueueItem[];
}

async function getQueue(): Promise<QueueResponse> {
  const res = await fetch(`${API}/admin/match-queue?limit=500`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export default async function MatchQueuePage() {
  let data: QueueResponse;
  try {
    data = await getQueue();
  } catch (e) {
    return (
      <div className="p-8 font-mono text-sm text-warning">
        Failed to load queue from {API}: {String(e)}
      </div>
    );
  }

  const { stats, items } = data;

  return (
    <div className="mx-auto max-w-5xl p-6 font-mono text-sm">
      <h1 className="mb-1 text-xl font-bold text-foreground">
        Match queue — review ({stats.pending} pending)
      </h1>
      <p className="mb-5 text-faint">
        Middle-band fuzzy candidates: an unmatched listing vs the product it may belong to.
      </p>

      {items.length === 0 ? (
        <div className="rounded-card border border-hairline bg-surface p-6 text-faint">
          Nothing pending. Run the vector matcher with a middle band to populate this.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {items.map((it) => (
            <div
              key={it.queue_id}
              className="rounded-card border border-hairline bg-surface p-4"
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs uppercase tracking-wide text-faint">
                  {it.listing.category ?? "—"}
                </span>
                <span className="rounded border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent-soft">
                  cos {it.score?.toFixed(3) ?? "—"}
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {/* unmatched listing */}
                <div>
                  <div className="mb-1 text-xs text-faint">unmatched listing</div>
                  <a
                    href={it.listing.product_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-foreground hover:text-accent-soft"
                  >
                    {it.listing.raw_name}
                  </a>
                  <div className="mt-1 text-muted">
                    {it.listing.shop} ·{" "}
                    {it.listing.price_usd != null ? `$${it.listing.price_usd}` : "—"} ·{" "}
                    {it.listing.in_stock ? "in stock" : "out"}
                  </div>
                </div>

                {/* candidate product */}
                <div className="border-t border-hairline pt-3 md:border-l md:border-t-0 md:pl-4 md:pt-0">
                  <div className="mb-1 text-xs text-faint">
                    candidate product → {it.candidate.name}
                  </div>
                  {it.candidate.listings.map((c, i) => (
                    <div key={i} className="text-muted">
                      {c.shop} ·{" "}
                      {c.price_usd != null ? `$${c.price_usd}` : "—"} · {c.raw_name}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
