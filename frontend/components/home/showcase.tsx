"use client";

import { useRef } from "react";
import Image from "next/image";
import Link from "next/link";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { useReducedMotion } from "framer-motion";
import { Package2, BadgeCheck, Store, Clock } from "lucide-react";
import type { Listing } from "@/lib/types";
import { formatUSD, formatRelativeTime } from "@/lib/format";
import { buttonVariants } from "@/components/ui/button";
import { CategoryIcon } from "@/components/category-icon";

gsap.registerPlugin(ScrollTrigger);

export function Showcase({ listing }: { listing: Listing | null }) {
  const root = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useGSAP(
    () => {
      if (reduce || !listing) return;
      if (window.matchMedia("(max-width: 767px)").matches) return;

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: root.current,
          start: "top top",
          end: "+=1200",
          scrub: 0.5,
          pin: true,
        },
      });

      tl.to(".showcase-tint", { opacity: 1, ease: "none" }, 0)
        .from(
          ".showcase-image",
          { scale: 0.82, autoAlpha: 0.5, ease: "none" },
          0,
        )
        .from(
          ".showcase-callout",
          { xPercent: 18, autoAlpha: 0, stagger: 0.3, ease: "none" },
          0.05,
        )
        .from(".showcase-cta", { autoAlpha: 0, y: 20, ease: "none" }, 0.7);
    },
    { scope: root, dependencies: [reduce, listing?.id] },
  );

  if (!listing) return null;

  const callouts = [
    {
      icon: BadgeCheck,
      label: "Live price",
      value: formatUSD(listing.price_usd, { decimals: true }),
    },
    {
      icon: Package2,
      label: "Availability",
      value: listing.in_stock ? "In stock now" : "Out of stock",
    },
    { icon: Store, label: "Sold by", value: listing.shop.name },
    {
      icon: Clock,
      label: "Last checked",
      value: formatRelativeTime(listing.last_seen_at),
    },
  ];

  return (
    <section
      ref={root}
      className="relative flex min-h-screen items-center overflow-hidden border-y border-hairline bg-base"
    >
      {/* scroll-driven indigo wash */}
      <div
        aria-hidden
        className="showcase-tint pointer-events-none absolute inset-0 opacity-0"
        style={{
          background:
            "radial-gradient(80% 80% at 70% 50%, rgba(99,102,241,0.22), transparent 70%)",
        }}
      />

      <div className="relative mx-auto grid w-full max-w-7xl items-center gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2 lg:px-8">
        {/* product image */}
        <div className="showcase-image relative mx-auto aspect-square w-full max-w-md">
          <div className="absolute inset-0 rounded-hero border border-hairline bg-surface/40 backdrop-blur-sm" />
          {listing.image_url ? (
            <Image
              src={listing.image_url}
              alt={listing.raw_name}
              fill
              sizes="(max-width: 1024px) 90vw, 40vw"
              className="object-contain p-10"
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

        {/* copy + callouts */}
        <div className="flex flex-col gap-6">
          <span className="inline-flex w-fit items-center gap-2 rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs font-medium text-accent-soft">
            Featured listing
          </span>
          <h2 className="text-balance text-3xl font-semibold leading-tight tracking-tight text-foreground sm:text-4xl">
            {listing.raw_name}
          </h2>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {callouts.map((c) => (
              <div
                key={c.label}
                className="showcase-callout flex items-center gap-3 rounded-card border border-hairline bg-surface/60 p-4 backdrop-blur"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-btn bg-elevated text-accent-soft">
                  <c.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-xs text-faint">{c.label}</p>
                  <p className="truncate font-mono text-sm font-medium text-foreground">
                    {c.value}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <div className="showcase-cta flex flex-wrap gap-3 pt-2">
            <Link
              href={`/listing/${listing.id}`}
              className={buttonVariants({ variant: "primary", size: "lg" })}
            >
              View deal
            </Link>
            <a
              href={listing.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "outline", size: "lg" })}
            >
              Open at {listing.shop.name}
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
