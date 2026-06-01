# Specsy — Claude Code Context

## Project
PCPartPicker-style PC parts + tech products price comparison site for Lebanon.
Scrapes Lebanese shops, normalizes and matches products, shows prices in USD and LBP across shops.
GitHub: AgentZero-lb/Specsy (private)

## Stack
- Frontend: Next.js 16, TypeScript, Tailwind, shadcn/ui → /frontend
- Backend: Python 3.11, FastAPI → /backend/api
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
- Prices from PCandParts come in cents — divide by 100 before storing

## Current status
- Phase: API live, ready to build frontend
- Schema: deployed to Supabase ✅
- First scrape: 5,303 products in listings table, category_slug populated ✅
- FastAPI: running, all endpoints tested ✅
- Next action: build Next.js frontend — category grid → product listing page

## DB tables (all deployed)
shops, categories, products, listings, price_snapshots,
match_queue, product_aliases, exchange_rates, scrape_runs, builds

## Shop 1: PCandParts — VERIFIED
- Platform: WooCommerce
- API: https://pcandparts.com/wp-json/wc/store/v1/products (open, no auth needed)
- Total products: 5,303 across 54 pages
- In-scope after category filter: 4,122 (78%)
- Has real price: 54% — rest are "Request Price" (price_raw = null, is fine)
- In stock: 62%
- Missing SKU: 0 (clean data)
- Price format: integer cents → divide by 100 (e.g. 58900 = $589.00)
- price = 0 + in_stock = true → "Request Price"
- price = 0 + in_stock = false → genuinely unavailable
- HTML entities in names need decoding before storing (e.g. &#8211; → –)
- Dedup key: product_url (SKU alone is not safe)

## Category scope
PC parts: cpu, gpu, ram, motherboard, storage, psu, case, cooling
Peripherals: monitor, mouse, keyboard, headset, speaker, microphone, joystick, drawing-pad, gaming-chair
Devices: laptop, desktop, tablet
Other: networking, ups, camera, projector
Out of scope: printers, toner, shredders, accessories — skip these till now, maybe will be in in V3 in addition for appiances...

## Product matching strategy (in order)
1. SKU match → instant high-confidence match
2. Spec + name parsing (regex normalize) → deterministic match
3. Voyage AI embeddings + pgvector cosine similarity → fuzzy match
4. Middle-band similarity → send to match_queue for human confirm
5. Confirmed matches → write to product_aliases (skip embedding next time)

## API endpoints (FastAPI, port 8000)
Start: `cd backend && uvicorn api.main:app --port 8000`
- `GET /health`
- `GET /listings?category=gpu&in_stock=true&has_price=true&q=rtx&page=1&limit=48`
- `GET /listings/categories` → 24 categories with counts (uses RPC `get_category_counts`)
- `GET /listings/{id}`

## Known issues to fix
- Some product names have garbled chars (â€" instead of –) — double UTF-8 encoding from the shop HTML, fix during frontend work

## Env vars needed
SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
DATABASE_URL, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY

## Env vars set (in .env)
SUPABASE_URL, SUPABASE_SERVICE_KEY, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY