import Link from "next/link";
import type { Listing } from "@/lib/types";
import { ProductCard } from "@/components/product-card";
import { CategoryIcon } from "@/components/category-icon";
import { Reveal } from "@/components/reveal";

interface FeaturedItem {
  slug: string;
  label: string;
  listing: Listing | null;
}

export function Featured({ items }: { items: FeaturedItem[] }) {
  const visible = items.filter((i) => i.listing !== null);
  if (visible.length === 0) return null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Lowest price per category
          </h2>
          <p className="mt-1 text-muted">
            Cheapest in-stock item available right now, by category.
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
          {visible.map(({ slug, label, listing }) => (
            <div key={slug} className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5 px-1">
                <CategoryIcon slug={slug} className="h-3.5 w-3.5 text-faint" />
                <span className="text-xs font-semibold uppercase tracking-widest text-faint">
                  {label}
                </span>
              </div>
              <ProductCard listing={listing!} />
            </div>
          ))}
        </div>
      </Reveal>
    </section>
  );
}
