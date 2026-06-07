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
- Phase: **3 shops live + full frontend built + hardened matching live; pre-deploy**
- Schema: deployed to Supabase ✅
- Shops live: PCandParts (WooCommerce) + Macrotronics (Shopify) + Ayoub Computers (BigCommerce) ✅
- Listings: **9,994 in-scope** across 24 categories (NULL-category rows hidden) ✅
- price_snapshots: one row per listing per run — the ~1000-row cap bug is fixed ✅
- Scope gate: title-based filter (`scope.py`) drops mis-filed accessories; `cleanup_scope.py` nulled existing rows ✅
- Matching: **LIVE — identity-based + fail-closed (see "Product matching strategy")**.
  Old chip-level matcher produced ~414 false merges; replaced by `scraper/identity.py` strict
  per-category identity + validated, reversible, atomic staged rebuild. Embedding/Haiku passes
  demoted to queue-only candidate generators. Rebuild
  `f6090a06-96c5-4715-881c-6a8d22ca24b5` is active: **1,025 matched listings (10.3%) /
  462 products**, with 0 cross-brand/chip/multi-model/motherboard-variant groups; 76 groups
  quarantined for review. `listings.raw_specs` (jsonb, migration 002) enriches identity.
- Re-scrape safety: `runner.py` no longer writes `product_id` on upsert, so re-scrapes
  PRESERVE matches (previously every `--save` reset product_id → wiped matching).
- FastAPI: live locally; added `sort`, `last_seen_at`, product comparison endpoint, and
  paged admin product lookup (avoids Supabase's 1,000-row cap) ✅
- Frontend: Next.js 16 built (home / browse / listing detail), wired to /listings API ✅
- Deploy: `render.yaml` + `DEPLOY.md` ready; **not deployed yet** (backend must be hosted before the Vercel frontend) ⏳
- Next action: review quarantined groups with the read-only workspace / regenerate queue
  candidates, then deploy when ready.

## DB tables (all deployed)
shops, categories, products, listings, price_snapshots,
match_queue, product_aliases, exchange_rates, scrape_runs, builds
- **`match_decisions` — migrations 003 + 004 applied** (reversible provenance + guarded
  activation). Unknown/empty/duplicate staged runs fail before any mapping update.

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

## Product matching strategy — REBUILT & HARDENED (identity-based, fail-closed)
The old matcher treated the *chipset* as GPU identity ("RTX 5070" → one product),
producing ~414 suspect false merges (GPU 100%, laptop 85%, UPS 86%). Replaced with strict
per-category identity + fail-closed validation + a reversible, atomic rebuild.

- `scraper/identity.py` — pure, unit-tested. `identity_keys(category, raw_name, raw_specs,
  sku) -> set[str]`: strict per-category keys (GPU = chip+AIB+variant+VRAM and/or full
  manufacturer part-code; CPU = full model incl suffix; RAM = brand+ddr+capacity+kit+speed+
  line; storage/monitor/psu = model code qualified by capacity/refresh/wattage; motherboard =
  exact board code + DDR + WiFi + revision + product line; laptop/desktop = **exact**
  CPU + RAM + SSD + GPU + family). Title-first, `raw_specs` fallback
  (case-insensitive). Missing required attr → no key → stays unmatched (queue). `describe()`
  + `title_spec_conflict()` for evidence/quarantine. **A false merge is worse than a miss.**
- `scraper/match.py` — the ONLY auto-merge path. Pass 1 normalized cross-shop SKU (with
  category+brand compatibility guard; same SKU diff brand/cat = conflict, not merged).
  Pass 2 identity-key union-find. Then **every** completed group is VALIDATED (coherent
  category/brand/chip/capacity/config + single model-code family + no name-conflict like
  same MPN "Saga" vs "Surge" + no title↔spec conflict); failures are **quarantined**
  (`reports/quarantined_groups.csv`), never written. Each accepted listing stores the exact
  linking key(s). No `.delete()`; reset never deletes listings/snapshots/scrape_runs/products.
- `scraper/match_vector.py` + `scraper/match_llm.py` — **candidate-generators only** (queue):
  they may populate `match_queue`, never set `product_id` / create / merge products. LLM API
  failures are never cached as rejections.
- Old learned `product_aliases` are **quarantined** (source→'quarantined') on rebuild and not
  reused (they came from the false-merge matcher); the API doesn't read aliases.
- Tests: `cd backend && python tests/test_matching.py` (34, framework-free).
- Quarantine review: `cd backend && python scripts/review_quarantine.py --open` generates
  `reports/quarantine_review.html` using DB SELECTs only. Review choices stay in browser
  local storage and export to an inert proposal CSV; there is no apply path. See
  `backend/QUARANTINE_REVIEW.md`. Tests: `python tests/test_quarantine_review.py` (5).
- PostgREST pagination is mandatory for validation/cleanup reads over 1,000 rows. Staging
  validation checks the exact listing set + product count; aliases and queue cleanup page fully.

### Migration / apply / rollback (DDL is MANUAL in Supabase SQL editor)
1. Migrations 003 + 004 are applied. Function execution is **revoked from
   anon/authenticated, granted only to service_role**.
2. Dry-run shadow rebuild (no writes): `cd backend && python -m scraper.match`
   (`--reset` alone is still dry; shows the reset plan).
3. Apply (staged + atomic): `cd backend && python -m scraper.match --reset --apply`
   — creates fresh products, stages decisions (status='staged', rebuild_run_id), keeps
   current mappings LIVE, validates, then flips atomically via `activate_rebuild()`.
   Exports a backup CSV to `backend/backups/mapping_<ts>.csv` first.
4. Rollback / recovery:
   - whole rebuild: `python scripts/restore_mapping.py backups/mapping_<ts>.csv --apply`
   - one bad product: `python scripts/unmatch.py --product <uuid> --apply --reviewer <you> --reason "<why>"`
     (dry by default; reviewer+reason REQUIRED on apply; reverses decisions, un-links only
     listings still pointing there, never deletes data).
- Candidate-gen (optional, after a rebuild): `python -m scraper.match_vector --apply` /
  `python -m scraper.match_llm --apply` → match_queue only.

### Live rebuild stats (algo match-2026.06.07-identity-v3-motherboard)
- in-scope 9,994 · **LIVE matched 1,025 (10.3%), 462 products** (1 SKU product,
  461 identity_rule products). The old 3,596 mappings were replaced atomically.
- ACCEPTED quality: **cross-brand 0, cross-chip 0, multi-model 0, motherboard-variant 0**,
  SKU conflicts 0. Motherboard: 4 accepted products / 10 listings; DDR4/DDR5, WiFi,
  revision, and product-line variants stay separate.
- QUARANTINED (fail closed, → review): 76 groups / 184 listings (multi-model 39,
  name-conflict 40, oversized 1; overlap). 2 title↔spec-conflicted listings excluded.
- Decisions: 1,025 active, 0 staged; exact decision/listing/product parity verified.
- Orphan accounting: 1,412 old products kept (un-linked, never deleted), 462 live fresh
  products; 1,874 products total.
- All 3,556 old aliases are quarantined. The 2,263 pre-rebuild pending queue candidates
  referenced orphan products and are preserved as `superseded`; pending queue is now 0.
- Safety verification: migration 004 rejects an unknown run without changing mappings;
  `restore_mapping.py` successfully restored all 3,596 old links during recovery testing.
- name-conflict is a deliberate **hard** quarantine (catches wrong-MPN like Pulsefire Saga/
  Surge + size variants; also conservatively holds some divergent-wording same-product pairs
  for review). Tunable via the `_DESCRIPTORS` list in `match.py` if higher recall is wanted.

## API endpoints (FastAPI, port 8000)
Start: `cd backend && uvicorn api.main:app --port 8000`
- `GET /health`
- `GET /listings?category=gpu&in_stock=true&has_price=true&q=rtx&sort=price_asc&page=1&limit=48`
  - `sort`: `name` (default) | `price_asc` | `price_desc`
  - response: `{ items, total, page, pages }`; ListingOut includes `last_seen_at`, `shop{slug,name,url}`
- `GET /listings/categories` → 24 categories with counts (RPC `get_category_counts`)
- `GET /listings/{id}` — ListingOut now also includes `product_id` (null = unmatched), the
  detail page's matched/unmatched signal
- `GET /products/{id}/listings` → `{ product{id,name,brand,category_slug,category_name,image_url},
  listings[] }`. Canonical product + every linked listing, sorted in-stock-priced cheapest-first,
  then out-of-stock priced, then Request-Price last. `product.image_url` = best image across the
  listings (products store none); `brand` is usually null (`_ensure_product` doesn't set it).
  Router: `api/routers/products.py`.
- CORS: localhost:3000 + `allow_origin_regex` for `*.vercel.app`

## Frontend (built) → /frontend
- Next.js 16 App Router, Tailwind v4 dark theme, Geist / Geist Mono fonts
- Pages: `/` (hero + live price preview + GSAP pinned showcase + category bento + best-value),
  `/browse` (filter rail, infinite scroll, URL-synced filters, mobile bottom sheet),
  `/listing/[id]` (PCPartPicker-style product detail), `/build` (placeholder)
- `/listing/[id]` (server component): fetches the listing, then if it's matched
  (`product_id` set) fetches `GET /products/{id}/listings`. **Matched** → canonical product
  shown once (hero image + name + brand chip when present) → "From $X · Save $Y" summary →
  "Where to buy" = one row per shop (collapsed to each shop's best offer), ranked cheapest-first;
  winner row gets a subtle indigo tint + "Cheapest" chip + primary CTA. **Unmatched / single-shop**
  → clean single-shop view, no comparison. CTAs: "View Deal" (priced) / "Request Price" (links to
  the shop page — no WhatsApp number in schema). Out-of-stock rows are muted. All page-specific
  pieces live inline in `page.tsx` (server-rendered, no client JS).
- Data: typed client in `lib/api.ts` → FastAPI; base URL from `NEXT_PUBLIC_API_URL` (default http://localhost:8000)
- Images: `next.config.ts` remotePatterns allow `pcandparts.com` + `cdn.shopify.com`
- Run: `cd frontend && npm run dev`
- Note: real per-shop prices/stock + cross-shop comparison are live; full technical spec tables
  still pending (products.specs is empty until matching enriches it)

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
