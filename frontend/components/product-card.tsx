import Link from "next/link";
import type { Listing } from "@/lib/types";
import { formatUSD, isRequestPrice } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { CategoryIcon } from "@/components/category-icon";
import { ProductCardImage } from "@/components/product-card-image";
import { cn } from "@/lib/utils";

export function ProductCard({ listing }: { listing: Listing }) {
  const requestPrice = isRequestPrice(listing);

  return (
    <Link
      href={`/listing/${listing.id}`}
      className="group relative flex flex-col overflow-hidden rounded-card border border-hairline bg-surface transition-all duration-200 hover:-translate-y-1 hover:border-hairline-strong hover:shadow-[0_16px_40px_-12px_rgba(0,0,0,0.7)]"
    >
      <div className="relative aspect-square overflow-hidden bg-base">
        {listing.image_url ? (
          <ProductCardImage
            src={listing.image_url}
            alt={listing.raw_name}
            categorySlug={listing.category_slug}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <CategoryIcon
              slug={listing.category_slug}
              className="h-12 w-12 text-faint"
            />
          </div>
        )}
        <div
          className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{
            background:
              "radial-gradient(120% 80% at 50% 100%, rgba(99,102,241,0.12), transparent 60%)",
          }}
        />
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <h3 className="line-clamp-2 min-h-[2.5rem] text-sm font-medium leading-snug text-foreground">
          {listing.raw_name}
        </h3>

        <div className="mt-auto flex items-end justify-between gap-2">
          {requestPrice ? (
            <Badge variant="warning">Request Price</Badge>
          ) : (
            <span className="font-mono text-lg font-semibold text-foreground">
              {formatUSD(listing.price_usd)}
            </span>
          )}
          <div className="flex items-center gap-1.5 text-xs text-faint">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                listing.in_stock ? "bg-success" : "bg-faint",
              )}
            />
            {listing.in_stock ? "In stock" : "Out of stock"}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-hairline pt-3">
          <span className="text-xs text-muted">{listing.shop.name}</span>
          <span className="text-xs font-medium text-accent-soft opacity-0 transition-opacity duration-200 group-hover:opacity-100">
            View details →
          </span>
        </div>
      </div>
    </Link>
  );
}
