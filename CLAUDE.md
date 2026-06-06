# Specsy — Claude Code Context

## Project
PCPartPicker-style PC parts + tech products price comparison site for Lebanon.
Scrapes Lebanese shops, normalizes and matches products, shows prices in USD and LBP across shops.
GitHub: AgentZero-lb/Specsy (private)

## Stack
- Frontend: Next.js 16 (App Router), TypeScript, Tailwind v4 (CSS `@theme`), hand-rolled UI primitives + Radix slider, framer-motion + GSAP, lucide-react → /frontend  ✅ built
- Backend: Python, FastAPI → /backend/api
- Scraper: httpx, one module per shop → /backend/scraper
- DB: PostgreSQL + pgvector (extension name: `vector`) via Supabase
- AI: Claude API (Haiku for classification, Sonnet for builds + chat)
- Embeddings: Voyage AI voyage-3 → vector(1024)

## Rules — never break
- AI reasons only over real DB data — never invent products, prices, or stock
- Compatibility is rules-only — LLM never decides compatibility
- Build generator is a constraint solver; LLM only explains the result
- Store prices as-seen with currency; compute USD from daily exchange rate
- If scraper returns 0 products, log failure and do NOT overwrite existing data
- price_raw = null means "Request Price" — show WhatsApp/call CTA, never hide the product
- Price format is per-shop: PCandParts = integer cents (÷100); Macrotronics/Shopify = dollar strings (no ÷). Always store as-seen with currency
- Scope gate (`scraper/scope.py`) is shared by scrapers + DB cleanup — out-of-scope-by-title items get `category_slug = NULL` (hidden by API), never deleted

## Current status
- Phase: **3 shops live + full frontend built; matching in progress; pre-deploy**
- Schema: deployed to Supabase ✅
- Shops live: PCandParts (WooCommerce) + Macrotronics (Shopify) + Ayoub Computers (BigCommerce) ✅
- Listings: **~9,991 in-scope** across 24 categories (NULL-category rows hidden) ✅
- price_snapshots: one row per listing per run — the ~1000-row cap bug is fixed ✅
- Scope gate: title-based filter (`scope.py`) drops mis-filed accessories; `cleanup_scope.py` nulled existing rows ✅
- Matching: deterministic `match.py` + embedding `match_vector.py` + Haiku `match_llm.py`
  built + run across all 3 shops → **~3,596 matched listings (35%), 1,412 products,
  1,401 multi-shop**; 2,263 gray-band pairs in `match_queue` for review. Admin QA
  endpoints (`/admin/matches`, `/admin/match-queue`) + pages live. `listings.raw_specs`
  (jsonb, migration 002) feeds the embedding/Haiku passes.
- Re-scrape safety: `runner.py` no longer writes `product_id` on upsert, so re-scrapes
  PRESERVE matches (previously every `--save` reset product_id → wiped matching).
- FastAPI: live on :8000; added `sort` param + `last_seen_at` to listings ✅
- Frontend: Next.js 16 built (home / browse / listing detail), wired to /listings API ✅
- Deploy: `render.yaml` + `DEPLOY.md` ready; **not deployed yet** (backend must be hosted before the Vercel frontend) ⏳
- Next action: finish matching across 3 shops → deploy backend (Render) → frontend (Vercel)

## DB tables (all deployed)
shops, categories, products, listings, price_snapshots,
match_queue, product_aliases, exchange_rates, scrape_runs, builds

## Shop 1: PCandParts — VERIFIED
- Platform: WooCommerce
- API: https://pcandparts.com/wp-json/wc/store/v1/products (open, no auth needed)
- Total products: 5,303 across 54 pages
- In-scope after category filter: ~4,122 (78%)
- Has real price: 54% — rest are "Request Price" (price_raw = null, is fine)
- In stock: 62%
- Missing SKU: 0 (clean data)
- Price format: integer cents → divide by 100 (e.g. 58900 = $589.00)
- price = 0 + in_stock = true → "Request Price"
- price = 0 + in_stock = false → genuinely unavailable
- HTML entities in names need decoding before storing (e.g. &#8211; → –)
- Dedup key: product_url (SKU alone is not safe)
- Run: `python -m scraper.runner pcandparts [--save]`

## Shop 2: Macrotronics — VERIFIED
- Platform: Shopify (Cloudflare in front)
- API: https://www.macrotronics.net/products.json (open, no auth) — paginate `?limit=250&page=N`
- Host: use **www** (apex 301-redirects to www)
- Total products: ~2,984 (12 pages); **~1,536 in-scope**
- Currency: **USD** (Shopify.currency); price is a STRING in dollars `"96.00"` — do **NOT** divide by 100
- No "Request Price" — every product is priced (price_raw always set)
- In stock: ~65%; `in_stock = any variant available`; price = cheapest variant
- Missing SKU: ~63 (~2%); sku from first variant
- Category from `product_type` (not collections). 4 mixed types disambiguated by title: Mice and Keyboards, Webcams and Microphones, Gaming Pads, Apple Computers
- Images: `cdn.shopify.com` (added to frontend `next.config` remotePatterns)
- Dedup key: product_url (`https://www.macrotronics.net/products/{handle}`)
- Run: `python -m scraper.runner macrotronics [--save]`

## Shop 3: Ayoub Computers — VERIFIED
- Platform: **BigCommerce** (Stencil theme; Cloudflare in front). Store hash `s-sp9oc95xrw`.
  Fingerprints: `cdn11.bigcommerce.com`, `stencil`, `SF-CSRF-TOKEN`/`fornax_anonymousId`
  cookies, `/api/storefront/cart`. NOT Woo/Shopify (`/wp-json` + `/products.json` 404).
- Data source: **Storefront GraphQL** (`POST https://ayoubcomputers.com/graphql`).
  - Auth: homepage embeds a short-lived storefront JWT (~2-day TTL, CORS-locked to the
    origin). The scraper scrapes a **fresh token each run** (regex on homepage HTML) and
    sends `Authorization: Bearer <jwt>` + `Origin: https://ayoubcomputers.com`. Expiry is
    a non-issue because we never persist the token.
  - `site.category(entityId:).products` returns a category's products **including all
    descendant subcategories**, paginated `first:50` (hard max) via `after` cursor.
- Catalogue: ayoubcomputers.com is a **general marketplace (~38k products** — beauty, toys,
  kitchen, pets, food…), so we use a **default-deny allowlist** of in-scope BigCommerce
  category ids → our slugs (`IN_SCOPE` in `shops/ayoub.py`), query each, and dedup by
  product id (first in-scope category wins). `scope.py` title gate still runs last.
- In-scope after mapping: **~4,355** across 24 categories (Jun 2026).
- Currency: **USD** (`prices.price.currencyCode`); price is a number, no ÷100.
- price: `prices.price.value`; `prices == null` → "Request Price" (price_raw=None). ~187 of these.
- in_stock: `availabilityV2.status == "Available"`. Do **NOT** use `inventory.isInStock` —
  it stays `True` on some Unavailable items (unreliable here).
- raw_specs: `customFields` (RESOLUTION, REFRESH RATE, CONNECTIVITY, capacity…) + Brand —
  richest spec data of the 3 shops; persisted to `listings.raw_specs` (jsonb) and fed into
  the embedding/Haiku matching passes.
- Networking: only **active gear** mapped (router/switch/mesh/adapters/cards/expansion/
  media-converter/antenna); passive cabling/racks/tools excluded (clean subcats let us).
- Desktops bucket folds in NAS/servers as `desktop`; minor accessory leaks (<1%) possible
  in drawing-pad / joystick / speaker / tablet (sweepable later via `scope.py`).
- Dedup key: product_url (`https://ayoubcomputers.com{path}`).
- Run: `python -m scraper.runner ayoub [--save]`

## Scraper runner
- `python -m scraper.runner [shop] [--save]` (run from `backend/`); shop defaults to `pcandparts`
- Multi-shop registry in `runner.py` (slug → module). Each shop module exposes `fetch_all()` + `SHOP_META`
- Dry run prints counts; `--save` upserts to Supabase (idempotent on `shop_id,product_url`) + writes a price_snapshot per listing
- Note: large `--save` runs can hit transient Supabase read-timeouts from a flaky connection; it's idempotent — just re-run

## Category scope
PC parts: cpu, gpu, ram, motherboard, storage, psu, case, cooling
Peripherals: monitor, mouse, keyboard, headset, speaker, microphone, joystick, drawing-pad, gaming-chair
Devices: laptop, desktop, tablet
Other: networking, ups, camera, projector
Out of scope: printers, toner, shredders, accessories — skip till V3 (maybe + appliances later)

Title-based scope gate (`scraper/scope.py`): even within in-scope categories, drop mis-filed
accessories by title — CCTV coax/BNC, electrical tape, cable ties, extinguishers, safes, door
locks — and passive network cabling (patch cords, RJ45 connectors, cable rolls). Conservative
(keeps borderline-but-legit cheap tech). Shared by scrapers + `cleanup_scope.py` so live data
and re-scrapes stay consistent. `python -m scraper.cleanup_scope [--apply]` nulls existing rows.

## Product matching strategy (in order) — BUILT
1. `match.py` — exact SKU across shops, then deterministic chip/model-code/name-key
   union-find. No API, idempotent. `python -m scraper.match [--apply]`
2. `match_vector.py` — Voyage `voyage-3` embeddings + cosine; high band auto-matches,
   middle band → `match_queue`. Embeddings cached in OS temp.
   `python -m scraper.match_vector [--apply --high H --mid M]`
3. `match_llm.py` — `claude-haiku-4-5` judges embedding-flagged candidate pairs
   (same product? y/n), unions confirmed. Verdicts cached. `python -m scraper.match_llm [--apply]`
- Embedding/Haiku text = `raw_name` + `raw_specs` (Ayoub's custom fields enrich this).
- Confirmed matches write to `product_aliases` (skip re-embedding next time).
- All passes share `load_listings` / `_ensure_product` / `DSU` from `match.py`; all idempotent
  (reuse existing products, refresh — not duplicate — the pending queue).

## API endpoints (FastAPI, port 8000)
Start: `cd backend && uvicorn api.main:app --port 8000`
- `GET /health`
- `GET /listings?category=gpu&in_stock=true&has_price=true&q=rtx&sort=price_asc&page=1&limit=48`
  - `sort`: `name` (default) | `price_asc` | `price_desc`
  - response: `{ items, total, page, pages }`; ListingOut includes `last_seen_at`, `shop{slug,name,url}`
- `GET /listings/categories` → 24 categories with counts (RPC `get_category_counts`)
- `GET /listings/{id}`
- CORS: localhost:3000 + `allow_origin_regex` for `*.vercel.app`

## Frontend (built) → /frontend
- Next.js 16 App Router, Tailwind v4 dark theme, Geist / Geist Mono fonts
- Pages: `/` (hero + live price preview + GSAP pinned showcase + category bento + best-value),
  `/browse` (filter rail, infinite scroll, URL-synced filters, mobile bottom sheet),
  `/listing/[id]` (scalable price-comparison panel + details table), `/build` (placeholder)
- Data: typed client in `lib/api.ts` → FastAPI; base URL from `NEXT_PUBLIC_API_URL` (default http://localhost:8000)
- Images: `next.config.ts` remotePatterns allow `pcandparts.com` + `cdn.shopify.com`
- Run: `cd frontend && npm run dev`
- Note: detail page has no real specs/brand yet (listings aren't matched to products) — shows real fields only

## Deployment (configured, NOT deployed)
- Backend → Render: `render.yaml` (rootDir `backend`, `requirements-api.txt`, uvicorn, healthcheck `/health`).
  Set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` in the Render dashboard.
- Frontend → Vercel: **Root Directory = `frontend`**; set `NEXT_PUBLIC_API_URL` = backend public URL.
  Use the Vercel web dashboard (CLI install is flaky on this machine).
- ORDER matters: deploy backend first — the frontend fetches it at build + runtime, and localhost
  is unreachable from Vercel. Steps in `DEPLOY.md`.

## Known issues to fix
- Some product names have garbled chars (â€" instead of –) — double UTF-8 encoding from the shop HTML
- Frontend `NEXT_PUBLIC_*` env vars are baked at build time — set them on Vercel before/at first deploy
- This machine's network to Supabase/GitHub/npm is intermittently blocked — saves run fine via detached processes; pushes/deploys must come from a stable terminal

## Env vars needed
SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
DATABASE_URL, NEXT_PUBLIC_API_URL, VOYAGE_API_KEY

## Env vars set (in .env)
SUPABASE_URL, SUPABASE_SERVICE_KEY, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY
- Frontend uses NEXT_PUBLIC_API_URL (in frontend/.env.local), not the Supabase anon vars
