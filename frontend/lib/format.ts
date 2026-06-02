import type { Listing } from "./types";

const usd0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const usd2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Format a USD amount. `decimals: true` → $589.00, otherwise $589. Null → em dash. */
export function formatUSD(
  value: number | null | undefined,
  opts?: { decimals?: boolean },
): string {
  if (value == null) return "—";
  return (opts?.decimals ? usd2 : usd0).format(value);
}

/** A listing with no real price is a "Request Price" item — never hide it. */
export function isRequestPrice(l: Pick<Listing, "price_raw">): boolean {
  return l.price_raw == null;
}

/** "https://wa.me/..." style is shop-specific; this builds the listing's shop link CTA target. */
export function shopHref(l: Pick<Listing, "product_url">): string {
  return l.product_url;
}

/** Compact relative time from an ISO string, for "Last updated" trust signals. */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.round((Date.now() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
