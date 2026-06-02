import { Suspense } from "react";
import type { Metadata } from "next";
import { getCategories } from "@/lib/api";
import { ProductCardSkeleton } from "@/components/product-card-skeleton";
import { BrowseClient } from "./browse-client";

export const metadata: Metadata = {
  title: "Browse parts — Specsy",
  description: "Filter and compare PC parts and tech products from Lebanese shops.",
};

export default async function BrowsePage() {
  const categories = await getCategories();

  return (
    <Suspense fallback={<BrowseFallback />}>
      <BrowseClient categories={categories} />
    </Suspense>
  );
}

function BrowseFallback() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[280px_1fr]">
        <div className="hidden lg:block" />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <ProductCardSkeleton key={i} />
          ))}
        </div>
      </div>
    </div>
  );
}
