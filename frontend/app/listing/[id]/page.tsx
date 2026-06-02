import { notFound } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import { ChevronRight, ExternalLink, MessageCircle } from "lucide-react";
import { getCategories, getListing } from "@/lib/api";
import type { Listing } from "@/lib/types";
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

  const categoryName =
    categories.find((c) => c.slug === listing.category_slug)?.name ??
    listing.category_slug ??
    "All parts";
  const requestPrice = isRequestPrice(listing);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Breadcrumb */}
      <nav className="mb-8 flex flex-wrap items-center gap-1.5 text-sm text-muted">
        <Link href="/" className="transition-colors hover:text-foreground">
          Home
        </Link>
        <ChevronRight className="h-4 w-4 text-faint" />
        {listing.category_slug ? (
          <Link
            href={`/browse?category=${listing.category_slug}`}
            className="transition-colors hover:text-foreground"
          >
            {categoryName}
          </Link>
        ) : (
          <span>{categoryName}</span>
        )}
        <ChevronRight className="h-4 w-4 text-faint" />
        <span className="max-w-[60vw] truncate text-foreground sm:max-w-xs">
          {listing.raw_name}
        </span>
      </nav>

      <div className="grid gap-10 lg:grid-cols-2">
        {/* Image */}
        <div className="relative aspect-square overflow-hidden rounded-hero border border-hairline bg-surface">
          {listing.image_url ? (
            <Image
              src={listing.image_url}
              alt={listing.raw_name}
              fill
              sizes="(max-width: 1024px) 90vw, 45vw"
              className="object-contain p-8"
              priority
            />
          ) : (
            <div className="grid h-full w-full place-items-center">
              <CategoryIcon
                slug={listing.category_slug}
                className="h-24 w-24 text-faint"
              />
            </div>
          )}
        </div>

        {/* Identity + price panel */}
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <Badge variant="accent" className="w-fit">
              <CategoryIcon slug={listing.category_slug} className="h-3 w-3" />
              {categoryName}
            </Badge>
            <h1 className="text-2xl font-semibold leading-snug tracking-tight text-foreground sm:text-3xl">
              {listing.raw_name}
            </h1>
            {listing.sku && (
              <p className="font-mono text-sm text-faint">SKU {listing.sku}</p>
            )}
          </div>

          {/* Price comparison panel — a list that scales to many shops */}
          <div className="rounded-card border border-hairline bg-surface">
            <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
              <span className="text-sm font-medium text-foreground">
                Price comparison
              </span>
              <span className="text-xs text-faint">1 shop</span>
            </div>
            <ShopRow listing={listing} requestPrice={requestPrice} best />
          </div>

          <p className="text-xs text-faint">
            Last updated {formatRelativeTime(listing.last_seen_at)} · more shops
            coming soon
          </p>
        </div>
      </div>

      {/* Details */}
      <section className="mt-14">
        <h2 className="mb-4 text-lg font-semibold text-foreground">Details</h2>
        <div className="overflow-hidden rounded-card border border-hairline">
          <DetailsTable listing={listing} categoryName={categoryName} />
        </div>
        <p className="mt-3 text-xs text-faint">
          Full technical specs are coming soon as products are matched across
          shops.
        </p>
      </section>
    </div>
  );
}

function ShopRow({
  listing,
  requestPrice,
  best,
}: {
  listing: Listing;
  requestPrice: boolean;
  best?: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-btn border border-hairline bg-base text-sm font-semibold text-muted">
          {listing.shop.name.slice(0, 2).toUpperCase()}
        </span>
        <div>
          <p className="text-sm font-medium text-foreground">
            {listing.shop.name}
          </p>
          <div className="mt-0.5 flex items-center gap-2">
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
            {best && !requestPrice && listing.in_stock && (
              <Badge variant="accent">Best price</Badge>
            )}
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
          <a
            href={listing.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ variant: "primary" })}
          >
            <MessageCircle className="h-4 w-4" />
            Request price
          </a>
        ) : (
          <a
            href={listing.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ variant: "outline" })}
          >
            View at shop
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>
    </div>
  );
}

function DetailsTable({
  listing,
  categoryName,
}: {
  listing: Listing;
  categoryName: string;
}) {
  const rows: [string, string][] = [
    ["SKU", listing.sku ?? "—"],
    ["Category", categoryName],
    ["Availability", listing.in_stock ? "In stock" : "Out of stock"],
    ["Currency", listing.currency],
    [
      "Listed price",
      listing.price_raw == null
        ? "Request Price"
        : formatUSD(listing.price_usd, { decimals: true }),
    ],
    ["Shop", listing.shop.name],
    ["Last seen", formatRelativeTime(listing.last_seen_at)],
  ];

  return (
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
  );
}
