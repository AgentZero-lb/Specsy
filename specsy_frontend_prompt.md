# Specsy — Frontend Build Prompt (v2, ground-truthed)

Build the production frontend for **Specsy**, a PC-parts + tech-products price-comparison site for Lebanon. This is a real product, not a demo. A FastAPI backend is **already running and verified** at `http://localhost:8000`, and the `/frontend` Next.js app is **already scaffolded with the foundation described in "What's already done" below** — build on it, don't recreate it.

> The #1 rule of this codebase (see root `CLAUDE.md`): **never invent products, prices, specs, or stock.** Every value on screen must come from the API. If the data doesn't exist, show an honest empty/placeholder state — do not fabricate it.

---

## Ground truth — the real API contract

Base URL comes from `NEXT_PUBLIC_API_URL` (already set to `http://localhost:8000` in `.env.local`). A typed client already exists at `lib/api.ts` — **use it** (`getListings`, `getListing`, `getCategories`). Types live in `lib/types.ts`.

### `GET /listings`

Query params (all optional):

| param       | type                                   | notes |
|-------------|----------------------------------------|-------|
| `category`  | category slug (e.g. `gpu`)             | |
| `in_stock`  | `true` \| `false`                      | |
| `has_price` | `true` = priced only · `false` = Request-Price only | |
| `q`         | string                                 | case-insensitive name search |
| `sort`      | `name` (default) \| `price_asc` \| `price_desc` | **pair `price_*` with `has_price=true`** so Request-Price items don't sort to the top |
| `page`      | int ≥ 1 (default 1)                    | **pagination is page-based, NOT offset-based** |
| `limit`     | int 1–200 (default 48)                 | |

Response:

```json
{
  "items": [
    {
      "id": "2f03bae7-...",
      "raw_name": "Matrox M9138 1GB",
      "sku": "M9138 1GB",
      "price_usd": 479.0,
      "price_raw": 479.0,
      "currency": "USD",
      "in_stock": true,
      "last_seen_at": "2026-06-01T20:12:47.830358+00:00",
      "product_url": "https://pcandparts.com/product/matrox-m9138-1gb/",
      "image_url": "https://pcandparts.com/wp-content/uploads/...jpg",
      "category_slug": "gpu",
      "shop": { "slug": "pcandparts", "name": "PC and Parts", "url": "https://pcandparts.com" }
    }
  ],
  "total": 4, "page": 1, "pages": 2
}
```

### `GET /listings/{id}`
Returns a **single listing object with the exact same shape as one `items[]` entry** (404 → `getListing` returns `null`).

### `GET /listings/categories`
Returns `[{ "slug": "gpu", "name": "Graphics Cards", "count": 54 }, ...]` — 24 categories. **This endpoint is backed by a slow Supabase RPC** — `getCategories()` already caches it for 12h; never call it on a hot path without that cache.

### Field-name landmines (the old prompt got these wrong — don't repeat them)
- The display name is **`raw_name`**, not `name`.
- There is **NO `name`, `brand`, `model`, or `specs` field** on a listing. Canonical specs live on a separate `products` table that listings aren't matched to yet, so **specs are not available via the API.** Do not render a fabricated spec sheet.
- Money: `price_usd` and `price_raw` are numbers; **`price_raw == null` means "Request Price"** — show a WhatsApp/contact CTA, never hide the item, never show `$0`.
- Currency is `"USD"` for every current listing. **There is no LBP value and no exchange-rate endpoint yet — show USD only.** Do not compute or display LBP from a hardcoded rate (that would be inventing a price). LBP is a future feature.
- `last_seen_at` is the freshness signal for "Last updated".

---

## Data realities you must design around (real numbers, fetched today)

- Category counts (total, incl. Request-Price + out-of-stock): `laptop 500 · monitor 446 · storage 438 · networking 426 · cooling 381 · mouse 331 · keyboard 258 · headset 184 · case 153 · cpu 152 · motherboard 130 · psu 123 · ram 116 · camera 80 · ups 79 · desktop 75 · gaming-chair 58 · gpu 54 · speaker 36 · projector 33 · tablet 20 · microphone 19 · drawing-pad 17 · joystick 13`.
- **Only ~54% of listings have a real price**; the rest are Request-Price. **GPU has just 4 priced items**, and they're old Matrox workstation cards — the dearest in-stock priced GPU is **"Matrox M9138 1GB" at $479**, not an RTX. So:
  - The hero "live price preview" and the pinned showcase **will display real, sometimes unglamorous, hardware.** That's the honest product — lean into "real Lebanese shop inventory," don't imply flagship gaming cards.
  - For the homepage showcase, prefer the broadest pool that still looks good: e.g. most-expensive in-stock priced item **across all categories** (`?in_stock=true&has_price=true&sort=price_desc&limit=1`) rather than forcing GPU. GPU-specific is fine too if you want thematic consistency — just know what comes back.
- Many `image_url`s are real shop photos; some listings have `image_url: null` → render the dark category-icon placeholder.

---

## What's already done (build ON this — do not redo)

In `/frontend`:
- **Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4** — scaffolded.
- **`.env.local`** → `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- **`next.config.ts`** → `images.remotePatterns` already allows `pcandparts.com/wp-content/**`, so `next/image` works on shop photos out of the box. (Add a pattern when a new shop's image host appears.)
- **Fonts** — `Geist` + `Geist_Mono` are loaded via `next/font/google` in `app/layout.tsx` and exposed as `--font-geist-sans` / `--font-geist-mono`. **Geist is available — use it; do not add Inter or Plus Jakarta.**
- **Design tokens** — `app/globals.css` defines the dark token system in Tailwind v4 `@theme`. **There is NO `tailwind.config.ts`** (Tailwind v4 is CSS-configured). Available utilities:
  - Surfaces: `bg-base` `#050506` · `bg-surface` `#0a0a0c` · `bg-elevated` `#111114`
  - Borders: `border-hairline` `rgba(255,255,255,.06)` · `border-hairline-strong` `.10`
  - Text: `text-foreground` · `text-muted` · `text-faint`
  - Accent: `accent` `#6366f1` · `accent-soft` `#818cf8` · `accent-foreground` (use as `bg-accent` / `text-accent` / `border-accent` / `ring-accent`)
  - Semantic: `success` (in stock) · `warning` `#f59e0b` (Request Price)
  - Radii: `rounded-card` (12) · `rounded-btn` (8) · `rounded-hero` (20)
  - Helper class `bg-dot-grid` (faint dot texture) and a global `prefers-reduced-motion` guard are in `globals.css`.
- **Typed API layer** — `lib/api.ts` (`getListings`, `getListing`, `getCategories`), `lib/types.ts` (`Listing`, `ListingsPage`, `CategoryCount`, `ListingQuery`, `SortOrder`).
- **Formatters** — `lib/format.ts`: `formatUSD(n, {decimals?})`, `isRequestPrice(listing)`, `formatRelativeTime(iso)`, `shopHref(listing)`.
- **`cn()`** class-merge helper — `lib/utils.ts` (clsx + tailwind-merge), at the shadcn-default path.
- **Installed deps**: `framer-motion`, `lucide-react`, `gsap`, `@gsap/react`, `clsx`, `tailwind-merge`.

### Still to install (do this first)
- **shadcn/ui** for primitives. Run `npx shadcn@latest init` (it will respect the existing `@/` alias and `lib/utils.ts` `cn` helper), then add **Button, Badge, Slider, Switch, Input, Skeleton, Separator, Tooltip**. shadcn supports Tailwind v4 + React 19. **Keep the Specsy `@theme` tokens as the source of truth** — if shadcn's generated CSS variables clash, ours win; simple primitives (Badge/Skeleton/Separator) may be hand-rolled with our tokens if that's cleaner.

---

## Next.js 16 specifics (don't rely on older muscle memory — `frontend/AGENTS.md` warns about this)

- **Server Components by default.** Fetch data directly in `async` page/component bodies via the `lib/api.ts` helpers. Add `"use client"` only to leaf components that need state, effects, browser APIs, or framer-motion/GSAP.
- **`params` and `searchParams` are Promises** — `await` them:
  ```tsx
  export default async function Page({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;
  }
  ```
- **`fetch` is uncached by default** and blocks render. Wrap slow sections in `<Suspense>` with a skeleton fallback, or add `loading.tsx`. Categories are already cached (12h) in `lib/api.ts`.
- Remote images already configured; always pass `width`/`height` (or `fill`) to `next/image`.
- Stream the homepage's data sections with `<Suspense>` so the hero paints instantly.

---

## Aesthetic direction (keep this — it's the soul of the product)

**Dark-first "premium tech" — Linear × Apple × Raycast.**
- Layered near-black surfaces (`bg-base` / `bg-surface` / `bg-elevated`) — never pure `#000`.
- ONE accent: electric indigo (`accent` / `accent-soft`). Resist rainbow gradients.
- Ambient indigo/violet radial-gradient blobs bleeding into the dark — **used sparingly.** Overusing big purple glows reads as AI-generated; keep them low-opacity, few, and large. Pair with the faint `bg-dot-grid` texture.
- Specular hairline borders (`border-hairline`), soft multi-layer shadows (not hard drops), 8pt spacing grid (8/16/24/32/48/64), radii `rounded-card` / `rounded-btn` / `rounded-hero`.
- Typography: **Geist** for UI, **Geist Mono** for all prices/specs/SKUs/numbers (use `font-mono`). Display headings: large, editorial, tight tracking, two lines max.
- Motion: restrained, 200–300ms. framer-motion `whileHover` / `initial`-`animate` / `useInView` for staggered scroll reveals. **Respect `prefers-reduced-motion` everywhere** (`useReducedMotion()` for framer-motion; guard GSAP timelines; the CSS guard is already in `globals.css`).

---

## Pages

### 1. Homepage `/`

**Hero** (mostly a Server Component; isolate animated bits as client leaves):
- Full-viewport dark hero, 1–2 restrained ambient blobs + dot-grid.
- Headline, editorial, two lines, tight tracking: e.g. *"Lebanon's PC parts, compared."*
- Sub: *"Real prices from Lebanese shops. No tab-switching."*
- CTAs: **Browse parts** (filled `bg-accent`) → `/browse` · **Build a PC** (ghost, hairline border) → can be a `/build` placeholder for now.
- A floating glassmorphic **price-preview card** showing **2–3 real listings** from the API (`getListings({ in_stock: true, has_price: true, sort: "price_desc", limit: 3 })`, or `category: "gpu"` if you want GPU-themed — expect Matrox cards). Real data only.
- Optional subtle parallax on blobs (scroll listener + transform, **disabled below 768px** and under reduced-motion).

**Pinned scroll showcase** (GSAP `ScrollTrigger`, client component, use `@gsap/react`'s `useGSAP`):
- One full-screen pinned section featuring the **most expensive in-stock priced item** (`sort: "price_desc", in_stock: true, has_price: true, limit: 1` — optionally `category: "gpu"`).
- Centered product image; scroll-driven reveals built **only from real fields we have**: price (`formatUSD`, big `font-mono`), in-stock badge, SKU, shop, `last_seen_at`. **Do NOT invent VRAM/clock-speed callouts — those specs aren't in the data.** You can frame the callouts as "Real price • In stock now • From {shop}".
- Dark → indigo background transition across the scroll; ends with a **View deal** CTA linking to `/listing/{id}` (or the shop URL).
- Must degrade gracefully: under reduced-motion or on mobile, render it as a static feature card.

**Category bento grid** — *"Shop by category"*:
- Data from `getCategories()`. **Asymmetric bento** (NOT a uniform grid): give the largest tiles to high-count, marquee categories (e.g. `gpu`, `cpu`, `laptop`, `monitor`); peripherals fill smaller slots.
- Each tile: `lucide-react` icon, category name, `count`, hover lift + accent glow. Link to `/browse?category={slug}`.
- Staggered scroll-in with `useInView`.

**Featured** — *"Best value right now"*:
- `getListings({ in_stock: true, has_price: true, sort: "price_asc", limit: 6 })` (cheapest first) — or `price_desc` for "premium picks"; pick one and label it honestly.
- **Strict uniform 3-column grid** (bento lives only in the category section). Reuse the same `ProductCard` as `/browse`.

**Footer:** minimal — logo, tagline, links (Browse / Build a PC / About), and a *"Data refreshed every 12h"* trust line.

### 2. Browse `/browse`

- **Left sticky filter rail (280px):**
  - Category selector from `getCategories()` with count badges.
  - **Price range** (USD) slider — note the API has no min/max price params, so apply price-range as a **client-side filter** on the fetched page, and be explicit that it filters the current result set. (Server-side price bounds are a future API enhancement.)
  - **In-stock** toggle → `in_stock`.
  - **Has-price** toggle (hide Request-Price) → `has_price`.
  - **Search** input → `q` (debounce ~300ms).
  - **Sort** control → `sort` (`name` / `price_asc` / `price_desc`).
- **Main area: strict uniform grid** — 3 cols desktop, 2 tablet, 1 mobile.
- **`ProductCard`** (shared): `next/image` or dark category-icon placeholder; `raw_name` truncated to 2 lines; `formatUSD(price_usd)` **or** an amber `warning` "Request Price" badge when `isRequestPrice`; in-stock dot (`success` / `faint`); shop badge (`shop.name`); hover → lift `-translateY-1`, brighten border, accent shadow; whole card links to `/listing/{id}`.
- **Infinite scroll** via `IntersectionObserver`, paging with `page`/`pages` from the response (client component that appends).
- **URL param sync** — filters read from and write to `searchParams` (`?category=gpu&in_stock=true&sort=price_asc`) so links are shareable; the page is the source of truth.
- **Skeleton** loading cards that match `ProductCard`'s layout exactly (use shadcn `Skeleton` / our tokens), pulsing.
- **Mobile:** the filter rail collapses to a bottom sheet.

### 3. Listing detail `/listing/[id]`

The core value page. `await params`, then `getListing(id)`; if `null` → `notFound()`.

- **Breadcrumb:** Home → {category name, resolved from `getCategories()`} → `raw_name`.
- **Left:** large product image (or category-icon placeholder), `raw_name`, category chip. (No brand/model — not in the data.)
- **Right — price-comparison panel (the hero feature):**
  - Build it as a **list of shop rows that scales to many shops**, even though there's exactly one today.
  - Each row: shop name (+ logo placeholder), big `font-mono` `formatUSD(price_usd, {decimals:true})`, stock badge (`success`/`faint`), **View at shop →** button → `product_url` (new tab).
  - **Request-Price state:** amber `warning` badge + a **WhatsApp / Contact** CTA instead of a price (never a price).
  - **"Best price"** badge on the cheapest in-stock priced row.
  - **"Last updated {formatRelativeTime(last_seen_at)}"** trust line.
- **Details table** (replaces the old "specs from jsonb", which the API can't provide): a clean two-column table of the **real** fields — SKU, Category, Availability, Currency, Shop, Listed price, Last seen. Add a small note like *"Full specs coming soon"* rather than faking a spec sheet.

---

## What NOT to do

- No mock/placeholder **data** — every value comes from the API (skeletons for loading are fine).
- No invented specs, brands, VRAM/clock numbers, or LBP prices. USD only until the rate feed lands.
- No `$0` — `price_raw == null` is "Request Price" with a contact CTA.
- No purple-gradient-on-white "AI slop"; no overusing ambient blobs.
- No Inter / Plus Jakarta — Geist is already wired.
- No uniform grid for the homepage categories (bento there); no bento on Browse/Detail (strict uniform grid there).
- No heavy 3D on Browse/Detail — keep them fast and scannable.
- Don't add `tailwind.config.ts` (Tailwind v4 is configured in `globals.css`); don't re-add Geist/env/api-client/tokens — they exist.

---

## Acceptance checks (run `cd frontend && npm run dev`, backend must be up on :8000)

1. Homepage paints instantly; hero price-preview + featured grid show **real listings** from the API; categories bento reflects real counts.
2. The pinned GSAP showcase animates on scroll and degrades to a static card under reduced-motion / on mobile.
3. Browse filters work, infinite scroll pages correctly, and **URL params stay in sync** and are shareable.
4. A Request-Price listing shows the amber badge + WhatsApp CTA (no price, no `$0`).
5. Detail page shows real data, the scalable price panel, "Last updated", and the honest Details table; bad id → `notFound()`.
6. Correct at a **375px** viewport (filter rail → bottom sheet); dark theme + tokens applied globally; `prefers-reduced-motion` respected.
7. `npm run build` passes with no type errors (types come from `lib/types.ts`).

---

### Backend note (already handled for you)
The `sort` param and `last_seen_at` field this prompt relies on were **added and verified** in `backend/api/routers/listings.py`. Start the API with `cd backend && uvicorn api.main:app --port 8000 --reload`.
