import { notFound } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import { ChevronRight, ExternalLink, MessageCircle } from "lucide-react";
import { getCategories, getListing, getProductListings } from "@/lib/api";
import type { ProductDetail, ProductListing } from "@/lib/types";
import { formatRelativeTime, formatUSD, isRequestPrice } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { CategoryIcon } from "@/components/category-icon";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const listing = await getListing(id);
  return {
    title: listing ? `${listing.raw_name} — Specsy` : "Listing — Specsy",
  };
}

export default async function ListingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [listing, categories] = await Promise.all([
    getListing(id),
    getCategories().catch(() => []),
  ]);

  if (!listing) notFound();

  // A matched listing links to a canonical product carried by 1+ shops. Fetch the
  // bundle so we can show the product once and rank every shop beneath it. Keep it
  // as a single nullable const so TypeScript narrows it across the branches below.
  const rawDetail = listing.product_id
    ? await getProductListings(listing.product_id).catch(() => null)
    : null;
  const detail =
    rawDetail && rawDetail.listings.length > 0 ? rawDetail : null;

  const categorySlug = detail
    ? detail.product.category_slug
    : listing.category_slug;
  const categoryName =
    detail?.product.category_name ??
    categories.find((c) => c.slug === categorySlug)?.name ??
    categorySlug ??
    "All parts";
  const title = detail ? detail.product.name : listing.raw_name;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb
        categorySlug={categorySlug}
        categoryName={categoryName}
        title={title}
      />

      {detail ? (
        <ProductView
          detail={detail}
          categorySlug={categorySlug}
          categoryName={categoryName}
        />
      ) : (
        // Graceful degradation: unmatched / single-shop. No comparison, no save —
        // just a clean detail view of the one listing we have.
        <SingleListingView
          listing={listing as ProductListing}
          categorySlug={listing.category_slug}
          categoryName={categoryName}
          sku={listing.sku}
        />
      )}
    </div>
  );
}

/* ─────────────────────────── Matched: product + all shops ─────────────────────── */

function ProductView({
  detail,
  categorySlug,
  categoryName,
}: {
  detail: ProductDetail;
  categorySlug: string | null;
  categoryName: string;
}) {
  const { product, listings } = detail;
  // PCPartPicker-style: one row per shop (that shop's best offer for this product),
  // not one row per listing — a shop can carry several listings of the same product.
  const rows = collapseByShop(listings);
  const stats = priceStats(rows);

  return (
    <>
      {/* Hero — product shown once: image + identity + price summary */}
      <div className="grid gap-10 lg:grid-cols-2">
        <HeroImage
          src={product.image_url}
          alt={product.name}
          categorySlug={categorySlug}
        />

        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="accent" className="w-fit">
                <CategoryIcon slug={categorySlug} className="h-3 w-3" />
                {categoryName}
              </Badge>
              {product.brand && (
                <Badge variant="outline" className="w-fit">
                  {product.brand}
                </Badge>
              )}
            </div>
            <h1 className="text-2xl font-semibold leading-snug tracking-tight text-foreground sm:text-3xl">
              {product.name}
            </h1>
            <p className="text-sm text-muted">
              Available at {rows.length} {rows.length === 1 ? "shop" : "shops"} in
              Lebanon
            </p>
          </div>

          <PriceSummary stats={stats} />
        </div>
      </div>

      {/* Where to buy — every shop, cheapest first */}
      <section className="mt-14">
        <div className="mb-4 flex items-end justify-between gap-4">
          <h2 className="text-lg font-semibold text-foreground">Where to buy</h2>
          <span className="text-xs text-faint">Ranked cheapest first</span>
        </div>
        <div className="divide-y divide-hairline overflow-hidden rounded-card border border-hairline bg-surface">
          {rows.map((l) => (
            <ShopDealRow
              key={l.id}
              listing={l}
              best={stats.winner?.id === l.id}
            />
          ))}
        </div>
        <p className="mt-3 text-xs text-faint">
          Prices and stock update automatically. &ldquo;Updated&rdquo; shows when
          each shop was last checked.
        </p>
      </section>

      <OverviewTable
        rows={[
          ["Category", categoryName],
          ...(product.brand ? ([["Brand", product.brand]] as Row[]) : []),
          ["Shops carrying it", String(rows.length)],
          ["Price range", priceRangeLabel(rows)],
        ]}
      />
    </>
  );
}

/* ───────────────────────── Unmatched: single-shop detail ──────────────────────── */

function SingleListingView({
  listing,
  categorySlug,
  categoryName,
  sku,
}: {
  listing: ProductListing;
  categorySlug: string | null;
  categoryName: string;
  sku: string | null;
}) {
  return (
    <>
      <div className="grid gap-10 lg:grid-cols-2">
        <HeroImage
          src={listing.image_url}
          alt={listing.raw_name}
          categorySlug={categorySlug}
        />

        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <Badge variant="accent" className="w-fit">
              <CategoryIcon slug={categorySlug} className="h-3 w-3" />
              {categoryName}
            </Badge>
            <h1 className="text-2xl font-semibold leading-snug tracking-tight text-foreground sm:text-3xl">
              {listing.raw_name}
            </h1>
            {sku && (
              <p className="font-mono text-sm text-faint">SKU {sku}</p>
            )}
          </div>

          <div className="overflow-hidden rounded-card border border-hairline bg-surface">
            <div className="border-b border-hairline px-5 py-3 text-sm font-medium text-foreground">
              Where to buy
            </div>
            <ShopDealRow listing={listing} primaryCta />
          </div>

          <p className="text-xs text-faint">
            Only one shop carries this so far. We add more shops as products are
            matched across stores.
          </p>
        </div>
      </div>

      <OverviewTable
        rows={[
          ["SKU", sku ?? "—"],
          ["Category", categoryName],
          ["Availability", listing.in_stock ? "In stock" : "Out of stock"],
          [
            "Price",
            isRequestPrice(listing)
              ? "Request Price"
              : formatUSD(listing.price_usd, { decimals: true }),
          ],
          ["Shop", listing.shop.name],
          ["Last seen", formatRelativeTime(listing.last_seen_at)],
        ]}
      />
    </>
  );
}

/* ──────────────────────────────── Shared pieces ───────────────────────────────── */

function Breadcrumb({
  categorySlug,
  categoryName,
  title,
}: {
  categorySlug: string | null;
  categoryName: string;
  title: string;
}) {
  return (
    <nav className="mb-8 flex flex-wrap items-center gap-1.5 text-sm text-muted">
      <Link href="/" className="transition-colors hover:text-foreground">
        Home
      </Link>
      <ChevronRight className="h-4 w-4 text-faint" />
      {categorySlug ? (
        <Link
          href={`/browse?category=${categorySlug}`}
          className="transition-colors hover:text-foreground"
        >
          {categoryName}
        </Link>
      ) : (
        <span>{categoryName}</span>
      )}
      <ChevronRight className="h-4 w-4 text-faint" />
      <span className="max-w-[60vw] truncate text-foreground sm:max-w-xs">
        {title}
      </span>
    </nav>
  );
}

function HeroImage({
  src,
  alt,
  categorySlug,
}: {
  src: string | null;
  alt: string;
  categorySlug: string | null;
}) {
  return (
    <div className="relative aspect-square overflow-hidden rounded-hero border border-hairline bg-surface">
      {src ? (
        <Image
          src={src}
          alt={alt}
          fill
          sizes="(max-width: 1024px) 90vw, 45vw"
          className="object-contain p-8"
          priority
        />
      ) : (
        <div className="grid h-full w-full place-items-center">
          <CategoryIcon slug={categorySlug} className="h-24 w-24 text-faint" />
        </div>
      )}
    </div>
  );
}

function PriceSummary({ stats }: { stats: PriceStats }) {
  if (stats.from == null || !stats.winner) {
    return (
      <div className="rounded-card border border-hairline bg-surface p-5">
        <p className="text-sm font-medium text-foreground">Pricing on request</p>
        <p className="mt-1 text-xs text-faint">
          No public price yet — contact a shop below for a quote.
        </p>
      </div>
    );
  }

  const showSave = stats.pricedCount >= 2 && stats.save > 0;

  return (
    <div className="flex flex-col gap-4 rounded-card border border-hairline bg-surface p-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wider text-faint">From</p>
          <p className="font-mono text-3xl font-semibold text-foreground">
            {formatUSD(stats.from, { decimals: true })}
          </p>
        </div>
        {showSave && (
          <p className="pb-1 text-sm font-medium text-success">
            Save up to {formatUSD(stats.save)}
          </p>
        )}
      </div>
      {showSave && (
        <p className="-mt-2 text-xs text-muted">vs. the most expensive shop</p>
      )}
      <a
        href={stats.winner.product_url}
        target="_blank"
        rel="noopener noreferrer"
        className={buttonVariants({ variant: "primary", className: "w-full" })}
      >
        View best deal at {stats.winner.shop.name}
        <ExternalLink className="h-4 w-4" />
      </a>
    </div>
  );
}

function ShopDealRow({
  listing,
  best,
  primaryCta,
}: {
  listing: ProductListing;
  best?: boolean; // comparison winner → "Cheapest" badge + indigo tint (multi-shop only)
  primaryCta?: boolean; // render the filled CTA (defaults to the winner)
}) {
  const requestPrice = isRequestPrice(listing);
  const isWinner = Boolean(best) && !requestPrice;
  const primary = primaryCta ?? isWinner;

  return (
    <div
      className={cn(
        "flex flex-col gap-4 p-5 transition-colors sm:flex-row sm:items-center sm:justify-between",
        isWinner && "border-l-2 border-accent bg-accent/6",
        !listing.in_stock && "opacity-60",
      )}
    >
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-btn border border-hairline bg-base text-sm font-semibold text-muted">
          {listing.shop.name.slice(0, 2).toUpperCase()}
        </span>
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-foreground">
              {listing.shop.name}
            </p>
            {isWinner && <Badge variant="accent">Cheapest</Badge>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <span
              className={cn(
                "flex items-center gap-1 text-xs",
                listing.in_stock ? "text-success" : "text-faint",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  listing.in_stock ? "bg-success" : "bg-faint",
                )}
              />
              {listing.in_stock ? "In stock" : "Out of stock"}
            </span>
            <span className="text-xs text-faint">
              Updated {formatRelativeTime(listing.last_seen_at)}
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 sm:justify-end">
        {requestPrice ? (
          <Badge variant="warning">Request Price</Badge>
        ) : (
          <span className="font-mono text-2xl font-semibold text-foreground">
            {formatUSD(listing.price_usd, { decimals: true })}
          </span>
        )}
        {requestPrice ? (
          // No public price → let the user open the product page to see it
          // ("View product"), plus the existing "Request Price" action.
          <div className="flex items-center gap-2">
            <a
              href={listing.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: primary ? "primary" : "outline" })}
            >
              View product
              <ExternalLink className="h-4 w-4" />
            </a>
            <a
              href={listing.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "subtle" })}
            >
              <MessageCircle className="h-4 w-4" />
              Request Price
            </a>
          </div>
        ) : (
          <a
            href={listing.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ variant: primary ? "primary" : "outline" })}
          >
            View Deal
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>
    </div>
  );
}

type Row = [string, string];

function OverviewTable({ rows }: { rows: Row[] }) {
  return (
    <section className="mt-14">
      <h2 className="mb-4 text-lg font-semibold text-foreground">Details</h2>
      <div className="overflow-hidden rounded-card border border-hairline">
        <table className="w-full text-sm">
          <tbody>
            {rows.map(([k, v], i) => (
              <tr key={k} className={cn(i % 2 ? "bg-surface" : "bg-base")}>
                <td className="w-1/3 px-5 py-3 align-top text-muted">{k}</td>
                <td className="px-5 py-3 font-medium text-foreground">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-faint">
        Full technical specs are coming soon as products are matched across shops.
      </p>
    </section>
  );
}

/* ──────────────────────────────── Pricing logic ───────────────────────────────── */

type PricedListing = ProductListing & { price_usd: number };

interface PriceStats {
  from: number | null; // cheapest in-stock price (fallback: cheapest priced)
  save: number; // max priced − from
  pricedCount: number;
  winner: PricedListing | null; // the row that earns the "Cheapest" highlight
}

/** Rank key: priced before Request-Price, in-stock before out-of-stock, then cheapest. */
function rankKey(l: ProductListing): [number, number, number] {
  return [l.price_usd == null ? 1 : 0, l.in_stock ? 0 : 1, l.price_usd ?? 0];
}

function cmpRank(a: ProductListing, b: ProductListing): number {
  const ka = rankKey(a);
  const kb = rankKey(b);
  return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2];
}

/** Collapse to one row per shop (that shop's best offer), then rank cheapest first. */
function collapseByShop(listings: ProductListing[]): ProductListing[] {
  const best = new Map<string, ProductListing>();
  for (const l of listings) {
    const cur = best.get(l.shop.slug);
    if (!cur || cmpRank(l, cur) < 0) best.set(l.shop.slug, l);
  }
  return [...best.values()].sort(cmpRank);
}

function priceStats(listings: ProductListing[]): PriceStats {
  const priced = listings.filter(
    (l): l is PricedListing => l.price_usd != null,
  );
  if (priced.length === 0) {
    return { from: null, save: 0, pricedCount: 0, winner: null };
  }

  const inStock = priced.filter((l) => l.in_stock);
  const pool = inStock.length ? inStock : priced;
  const winner = pool.reduce((a, b) => (b.price_usd < a.price_usd ? b : a));
  // Compare against the most expensive offer in the same buyable pool, so "Save"
  // never advertises a saving versus a price you can't actually act on.
  const max = Math.max(...pool.map((l) => l.price_usd));

  return {
    from: winner.price_usd,
    save: Math.max(0, max - winner.price_usd),
    pricedCount: priced.length,
    winner,
  };
}

function priceRangeLabel(listings: ProductListing[]): string {
  const priced = listings
    .map((l) => l.price_usd)
    .filter((p): p is number => p != null);
  if (priced.length === 0) return "Request Price";
  const min = Math.min(...priced);
  const max = Math.max(...priced);
  return min === max
    ? formatUSD(min, { decimals: true })
    : `${formatUSD(min, { decimals: true })} – ${formatUSD(max, { decimals: true })}`;
}
