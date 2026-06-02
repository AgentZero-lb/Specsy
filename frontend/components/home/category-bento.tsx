"use client";

import Link from "next/link";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { CategoryCount } from "@/lib/types";
import { CategoryIcon } from "@/components/category-icon";
import { cn } from "@/lib/utils";

// Asymmetric layout: marquee categories get the big tiles.
const BENTO: { slug: string; span: string; big?: boolean }[] = [
  { slug: "gpu", span: "col-span-2 row-span-2", big: true },
  { slug: "cpu", span: "col-span-2" },
  { slug: "laptop", span: "" },
  { slug: "monitor", span: "" },
  { slug: "ram", span: "" },
  { slug: "storage", span: "" },
  { slug: "psu", span: "" },
  { slug: "cooling", span: "" },
];

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};
const item: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4 } },
};

export function CategoryBento({ categories }: { categories: CategoryCount[] }) {
  const reduce = useReducedMotion();
  const bySlug = new Map(categories.map((c) => [c.slug, c]));

  const tiles = BENTO.map((t) => ({ ...t, cat: bySlug.get(t.slug) })).filter(
    (t) => t.cat,
  );

  return (
    <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
      <div className="mb-8 flex items-end justify-between gap-4">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Shop by category
        </h2>
        <Link
          href="/browse"
          className="shrink-0 text-sm font-medium text-accent-soft transition-colors hover:text-accent"
        >
          All 24 categories →
        </Link>
      </div>

      <motion.div
        className="grid auto-rows-[150px] grid-cols-2 gap-4 md:grid-cols-4"
        variants={reduce ? undefined : container}
        initial={reduce ? undefined : "hidden"}
        whileInView={reduce ? undefined : "show"}
        viewport={{ once: true, margin: "-80px" }}
      >
        {tiles.map(({ slug, span, big, cat }) => (
          <motion.div
            key={slug}
            variants={reduce ? undefined : item}
            className={cn("min-h-0", span)}
          >
            <Link
              href={`/browse?category=${slug}`}
              className="group relative flex h-full w-full flex-col justify-between overflow-hidden rounded-card border border-hairline bg-surface p-5 transition-all duration-200 hover:-translate-y-1 hover:border-accent/40 hover:shadow-[0_16px_40px_-12px_rgba(0,0,0,0.7)]"
            >
              <div
                className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                style={{
                  background:
                    "radial-gradient(100% 100% at 0% 0%, rgba(99,102,241,0.14), transparent 55%)",
                }}
              />
              <CategoryIcon
                slug={slug}
                className={cn(
                  "text-muted transition-colors group-hover:text-accent-soft",
                  big ? "h-9 w-9" : "h-6 w-6",
                )}
              />
              <div className="relative">
                <p
                  className={cn(
                    "font-medium text-foreground",
                    big ? "text-xl" : "text-sm",
                  )}
                >
                  {cat!.name}
                </p>
                <p className="font-mono text-xs text-faint">
                  {cat!.count} items
                </p>
              </div>
            </Link>
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}
