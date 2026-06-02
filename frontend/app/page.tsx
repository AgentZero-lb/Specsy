import type { Metadata } from "next";
import { getCategories, getListings } from "@/lib/api";
import { Hero } from "@/components/home/hero";
import { Showcase } from "@/components/home/showcase";
import { CategoryBento } from "@/components/home/category-bento";
import { Featured } from "@/components/home/featured";

export const metadata: Metadata = {
  title: "Specsy — Lebanon's PC parts, compared",
  description:
    "Real prices from Lebanese shops, compared in one place. No tab-switching.",
};

// Catalog refreshes every 12h, so cache homepage data for the same window.
const CACHE: RequestInit = { next: { revalidate: 43_200 } };

export default async function Home() {
  const [categories, premium, featured] = await Promise.all([
    getCategories().catch(() => []),
    getListings(
      { in_stock: true, has_price: true, sort: "price_desc", limit: 4 },
      CACHE,
    )
      .then((d) => d.items)
      .catch(() => []),
    getListings(
      { in_stock: true, has_price: true, sort: "price_asc", limit: 6 },
      CACHE,
    )
      .then((d) => d.items)
      .catch(() => []),
  ]);

  const showcase = premium[0] ?? null;
  const heroPreview = premium.slice(1, 4);

  return (
    <>
      <Hero preview={heroPreview} />
      <Showcase listing={showcase} />
      <CategoryBento categories={categories} />
      <Featured listings={featured} />
    </>
  );
}
