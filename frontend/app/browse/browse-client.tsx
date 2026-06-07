"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SlidersHorizontal, X, Search, PackageOpen } from "lucide-react";
import { getListings } from "@/lib/api";
import type { CategoryCount, Listing, ListingQuery, SortOrder } from "@/lib/types";
import { ProductCard } from "@/components/product-card";
import { ProductCardSkeleton } from "@/components/product-card-skeleton";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

const LIMIT = 48;

const SORTS: { value: SortOrder; label: string }[] = [
  { value: "name", label: "Name (A–Z)" },
  { value: "price_asc", label: "Price: Low to High" },
  { value: "price_desc", label: "Price: High to Low" },
];

export function BrowseClient({ categories }: { categories: CategoryCount[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const sortedCategories = useMemo(
    () => [...categories].sort((a, b) => a.name.localeCompare(b.name)),
    [categories],
  );

  // URL is the source of truth for server-affecting filters
  const category = searchParams.get("category");
  const inStock = searchParams.get("in_stock") === "true";
  const hasPrice = searchParams.get("has_price") === "true";
  const q = searchParams.get("q") ?? "";
  const sort = (searchParams.get("sort") as SortOrder) ?? "name";

  const query = useMemo<ListingQuery>(
    () => ({
      category: category ?? undefined,
      in_stock: inStock || undefined,
      has_price: hasPrice || undefined,
      q: q || undefined,
      sort,
    }),
    [category, inStock, hasPrice, q, sort],
  );

  const [items, setItems] = useState<Listing[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);

  const [searchText, setSearchText] = useState(q);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const loadingMoreRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  function updateParams(updates: Record<string, string | null>) {
    const sp = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") sp.delete(k);
      else sp.set(k, v);
    }
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  // Keep the search box in sync with the URL (back/forward navigation)
  useEffect(() => {
    // URL navigation is an external state source, so the input must follow it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSearchText(q);
  }, [q]);

  // Debounce search input → URL
  useEffect(() => {
    const t = setTimeout(() => {
      const current = searchParams.get("q") ?? "";
      if (searchText !== current) updateParams({ q: searchText || null });
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  // Fetch page 1 whenever a server-affecting filter changes
  useEffect(() => {
    let ignore = false;
    // This reset intentionally happens at the start of each network request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(false);
    getListings({ ...query, page: 1, limit: LIMIT })
      .then((data) => {
        if (ignore) return;
        setItems(data.items);
        setPages(data.pages);
        setTotal(data.total);
        setPage(1);
      })
      .catch(() => !ignore && setError(true))
      .finally(() => !ignore && setLoading(false));
    return () => {
      ignore = true;
    };
  }, [query]);

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || page >= pages) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await getListings({ ...query, page: next, limit: LIMIT });
      setItems((prev) => [...prev, ...data.items]);
      setPage(next);
      setPages(data.pages);
    } catch {
      /* keep what we have */
    } finally {
      setLoadingMore(false);
      loadingMoreRef.current = false;
    }
  }, [page, pages, query]);

  // Infinite scroll
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => entries[0]?.isIntersecting && loadMore(),
      { rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  const activeFilterCount =
    (category ? 1 : 0) + (inStock ? 1 : 0) + (hasPrice ? 1 : 0);

  const filters = (
    <div className="flex flex-col gap-6 pb-8">
      {/* Search */}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
        <Input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search parts…"
          className="pl-9"
          aria-label="Search parts"
        />
      </div>

      {/* Sort */}
      <div className="flex flex-col gap-2">
        <Label>Sort</Label>
        <select
          value={sort}
          onChange={(e) =>
            updateParams({
              sort: e.target.value === "name" ? null : e.target.value,
            })
          }
          className="h-10 w-full rounded-btn border border-hairline bg-base px-3 text-sm text-foreground focus-visible:border-accent focus-visible:outline-none"
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value} className="bg-surface">
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* Toggles */}
      <div className="flex flex-col gap-3">
        <ToggleRow
          label="In stock only"
          checked={inStock}
          onChange={(v) => updateParams({ in_stock: v ? "true" : null })}
        />
        <ToggleRow
          label="Hide Request-Price"
          checked={hasPrice}
          onChange={(v) => updateParams({ has_price: v ? "true" : null })}
        />
      </div>

      {/* Categories */}
      <div className="flex flex-col gap-1">
        <Label className="mb-1">Category</Label>
        <CategoryButton
          label="All categories"
          active={!category}
          onClick={() => updateParams({ category: null })}
        />
        {sortedCategories.map((c) => (
          <CategoryButton
            key={c.slug}
            label={c.name}
            count={c.count}
            active={category === c.slug}
            onClick={() =>
              updateParams({ category: category === c.slug ? null : c.slug })
            }
          />
        ))}
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Heading */}
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {category
              ? categories.find((c) => c.slug === category)?.name ?? "Browse"
              : "All parts"}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {loading ? "Loading…" : `${total.toLocaleString()} listings`}
          </p>
        </div>

        {/* Mobile filter trigger */}
        <button
          onClick={() => setFiltersOpen(true)}
          className="inline-flex items-center gap-2 rounded-btn border border-hairline bg-surface px-3 py-2 text-sm text-foreground lg:hidden"
        >
          <SlidersHorizontal className="h-4 w-4" />
          Filters
          {activeFilterCount > 0 && (
            <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-xs text-accent-foreground">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[280px_1fr]">
        {/* Desktop rail */}
        <aside className="hidden lg:sticky lg:top-24 lg:block lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
          {filters}
        </aside>

        {/* Results */}
        <div>
          {error ? (
            <EmptyState
              title="Couldn't reach the catalog"
              body="The API didn't respond. Make sure the backend is running on port 8000, then retry."
            />
          ) : loading ? (
            <Grid>
              {Array.from({ length: 9 }).map((_, i) => (
                <ProductCardSkeleton key={i} />
              ))}
            </Grid>
          ) : items.length === 0 ? (
            <EmptyState
              title="No matching parts"
              body="Try another search or clear a filter."
            />
          ) : (
            <>
              <Grid>
                {items.map((l) => (
                  <ProductCard key={l.id} listing={l} />
                ))}
              </Grid>
              {loadingMore && (
                <Grid className="mt-5">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <ProductCardSkeleton key={i} />
                  ))}
                </Grid>
              )}
              <div ref={sentinelRef} className="h-10" />
            </>
          )}
        </div>
      </div>

      {/* Mobile bottom sheet */}
      {filtersOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setFiltersOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-hero border-t border-hairline bg-surface p-5 pb-8">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-foreground">Filters</h2>
              <button
                onClick={() => setFiltersOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-btn text-muted hover:bg-elevated hover:text-foreground"
                aria-label="Close filters"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            {filters}
            <button
              onClick={() => setFiltersOpen(false)}
              className="mt-6 h-11 w-full rounded-btn bg-accent font-medium text-accent-foreground"
            >
              Show {total.toLocaleString()} results
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Grid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

function Label({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "text-xs font-semibold uppercase tracking-wide text-faint",
        className,
      )}
    >
      {children}
    </span>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between">
      <span className="text-sm text-foreground">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}

function CategoryButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center justify-between rounded-btn px-3 py-2 text-left text-sm transition-colors",
        active
          ? "bg-accent/10 text-accent-soft"
          : "text-muted hover:bg-elevated hover:text-foreground",
      )}
    >
      <span className="truncate">{label}</span>
      {count !== undefined && (
        <span className="ml-2 shrink-0 font-mono text-xs text-faint">
          {count}
        </span>
      )}
    </button>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-hairline bg-surface py-24 text-center">
      <PackageOpen className="h-10 w-10 text-faint" />
      <h3 className="text-lg font-medium text-foreground">{title}</h3>
      <p className="max-w-sm text-sm text-muted">{body}</p>
    </div>
  );
}
