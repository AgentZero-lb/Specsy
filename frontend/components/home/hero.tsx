"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useReducedMotion } from "framer-motion";
import type { Listing } from "@/lib/types";
import { formatUSD, isRequestPrice } from "@/lib/format";
import { buttonVariants } from "@/components/ui/button";
import { CategoryIcon } from "@/components/category-icon";

export function Hero({ preview }: { preview: Listing[] }) {
  const reduce = useReducedMotion();
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (reduce || window.innerWidth < 768) return;
    const onScroll = () => setOffset(window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [reduce]);

  return (
    <section className="relative overflow-hidden border-b border-hairline">
      {/* ambient blobs — used sparingly */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div
          className="absolute -left-40 -top-40 h-[460px] w-[460px] rounded-full bg-accent/20 blur-[130px]"
          style={{ transform: `translateY(${offset * 0.15}px)` }}
        />
        <div
          className="absolute right-[-12%] top-[18%] h-[380px] w-[380px] rounded-full bg-[#7c3aed]/15 blur-[130px]"
          style={{ transform: `translateY(${offset * 0.08}px)` }}
        />
      </div>
      <div className="bg-dot-grid absolute inset-0 opacity-40" aria-hidden />

      <div className="relative mx-auto grid max-w-7xl gap-12 px-4 py-24 sm:px-6 md:py-32 lg:grid-cols-2 lg:items-center lg:gap-8 lg:px-8">
        <div className="flex flex-col items-start gap-6">
          <span className="inline-flex items-center gap-2 rounded-full border border-hairline bg-surface/60 px-3 py-1 text-xs text-muted backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Live Lebanese shop prices
          </span>
          <h1 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-foreground sm:text-5xl md:text-6xl">
            Lebanon&apos;s PC parts,
            <br />
            compared.
          </h1>
          <p className="max-w-md text-lg text-muted">
            Real prices from Lebanese shops. No tab-switching.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/browse"
              className={buttonVariants({ variant: "primary", size: "lg" })}
            >
              Browse parts
            </Link>
            <Link
              href="/build"
              className={buttonVariants({ variant: "outline", size: "lg" })}
            >
              Build a PC
            </Link>
          </div>
        </div>

        <div
          className="relative"
          style={reduce ? undefined : { transform: `translateY(${offset * -0.04}px)` }}
        >
          <PreviewCard preview={preview} />
        </div>
      </div>
    </section>
  );
}

function HeroThumb({ listing: l }: { listing: Listing }) {
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");

  if (!l.image_url || status === "error") {
    return (
      <div className="grid h-full w-full place-items-center">
        <CategoryIcon slug={l.category_slug} className="h-5 w-5 text-faint" />
      </div>
    );
  }

  return (
    <>
      {status === "loading" && (
        <div className="absolute inset-0 animate-pulse bg-elevated" />
      )}
      <Image
        src={l.image_url}
        alt={l.raw_name}
        fill
        sizes="48px"
        className="object-contain p-1"
        onLoad={() => setStatus("loaded")}
        onError={() => setStatus("error")}
      />
    </>
  );
}

function PreviewCard({ preview }: { preview: Listing[] }) {
  if (preview.length === 0) return null;

  return (
    <div className="rounded-hero border border-hairline bg-surface/60 p-4 shadow-[0_24px_80px_-20px_rgba(0,0,0,0.85)] backdrop-blur-xl">
      <div className="mb-3 flex items-center justify-between px-2">
        <span className="text-sm font-medium text-foreground">
          Top picks in stock
        </span>
        <span className="font-mono text-xs text-faint">USD</span>
      </div>
      <div className="flex flex-col gap-2">
        {preview.map((l) => (
          <Link
            key={l.id}
            href={`/listing/${l.id}`}
            className="group flex items-center gap-3 rounded-card border border-hairline bg-base/60 p-3 transition-colors hover:border-hairline-strong"
          >
            <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-btn bg-base">
              <HeroThumb listing={l} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-foreground">{l.raw_name}</p>
              <p className="text-xs text-faint">{l.shop.name}</p>
            </div>
            <span className="font-mono text-sm font-semibold text-foreground">
              {isRequestPrice(l) ? "—" : formatUSD(l.price_usd)}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
