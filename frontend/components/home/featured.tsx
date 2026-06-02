import Link from "next/link";
import type { Listing } from "@/lib/types";
import { ProductCard } from "@/components/product-card";
import { Reveal } from "@/components/reveal";

export function Featured({ listings }: { listings: Listing[] }) {
  if (listings.length === 0) return null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Best value right now
          </h2>
          <p className="mt-1 text-muted">
            In-stock parts with the lowest prices.
          </p>
        </div>
        <Link
          href="/browse?in_stock=true&has_price=true&sort=price_asc"
          className="hidden shrink-0 text-sm font-medium text-accent-soft transition-colors hover:text-accent sm:block"
        >
          View all →
        </Link>
      </div>

      <Reveal>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {listings.map((l) => (
            <ProductCard key={l.id} listing={l} />
          ))}
        </div>
      </Reveal>
    </section>
  );
}
