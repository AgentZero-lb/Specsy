# Deploying Specsy

Two pieces, deployed separately:

| Piece | Lives in | Host | Why |
|-------|----------|------|-----|
| **API** (FastAPI) | `backend/` | **Render** | Long-running Python server, talks to Supabase |
| **Web** (Next.js) | `frontend/` | **Vercel** | Best-in-class Next.js hosting |

> **Order matters.** Deploy the **backend first**, confirm it's live, then deploy the
> frontend pointing at the backend's public URL. The web app has no data of its own —
> it fetches everything from the API via `NEXT_PUBLIC_API_URL`.

---

## Part 1 — Backend on Render

Everything is pre-configured in [`render.yaml`](./render.yaml). You only set two secrets.

1. **Push** the launch-ready commits:
   ```powershell
   git push
   ```
2. Go to **[dashboard.render.com](https://dashboard.render.com)** → **New** → **Blueprint**.
3. Connect your GitHub and pick **`AgentZero-lb/Specsy`**. Render detects `render.yaml`
   and proposes a service called **`specsy-api`**. Click **Apply**.
4. When prompted (or under the service's **Environment** tab), set the two secrets —
   copy the values from your local `.env`:
   | Key | Value |
   |-----|-------|
   | `SUPABASE_URL` | *(from `.env`)* |
   | `SUPABASE_SERVICE_KEY` | *(from `.env`)* |
5. Render builds and deploys. When it's live you'll get a URL like
   **`https://specsy-api.onrender.com`**.
6. **Verify it works** — open these in a browser:
   - `https://specsy-api.onrender.com/health` → `{"status":"ok","project":"Specsy"}`
   - `https://specsy-api.onrender.com/listings?category=gpu&limit=2` → real JSON

> **Free-tier note:** the service sleeps after ~15 min idle, so the *first* request
> after a nap takes ~30–50s to wake. Fine for now; upgrade later for always-on.

---

## Part 2 — Frontend on Vercel (no CLI needed)

Skip the `vercel` CLI — the web dashboard is more reliable and the CLI install was
failing on your machine anyway. (If you ever want the CLI, use `npx vercel` instead of
a global install.)

1. Go to **[vercel.com/new](https://vercel.com/new)** → **Import** `AgentZero-lb/Specsy`.
2. **Root Directory** → click **Edit** → choose **`frontend`**. *(Critical — the Next app
   is in a subfolder. Vercel will then auto-detect the Next.js framework preset.)*
3. **Environment Variables** → add:
   | Key | Value |
   |-----|-------|
   | `NEXT_PUBLIC_API_URL` | `https://specsy-api.onrender.com` *(your Render URL, no trailing slash)* |
4. Click **Deploy**.

> **Important:** `NEXT_PUBLIC_*` vars are baked in at **build time**. If you change the
> API URL later, you must **redeploy** (Vercel → Deployments → ⋯ → Redeploy) for it to
> take effect.

After this, every `git push` to `master` auto-deploys both Render and Vercel.

---

## Part 3 — Automatic catalog refresh

The repository includes `.github/workflows/refresh-catalog.yml`, scheduled every
12 hours and also runnable manually from GitHub Actions.

In GitHub, open **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `SUPABASE_URL` | *(from local `.env`)* |
| `SUPABASE_SERVICE_KEY` | *(from local `.env`)* |

Then open **Actions → Refresh catalog → Run workflow** once. Confirm all three
shop jobs finish successfully. Existing product matches are preserved on re-scrape;
listings absent from a healthy full catalog are retained but marked out of stock.

Internal `/admin` API and frontend routes are disabled by default. Do not enable
`ENABLE_ADMIN_ROUTES` or `ENABLE_ADMIN_UI` on the public beta.

---

## Env var cheat-sheet

| Where | Var | Purpose |
|-------|-----|---------|
| Render (backend) | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | DB access |
| Render (backend) | `PYTHON_VERSION` | pinned to 3.12.7 (in `render.yaml`) |
| Vercel (frontend) | `NEXT_PUBLIC_API_URL` | points the web app at the live API |

The frontend does **not** use Supabase directly — `NEXT_PUBLIC_API_URL` is the only var it needs.

---

## Sanity checklist

- [ ] Backend `/health` returns ok on the Render URL
- [ ] Backend `/listings?...` returns real JSON
- [ ] Vercel **Root Directory** is `frontend`
- [ ] `NEXT_PUBLIC_API_URL` is set on Vercel (no trailing slash) **before** the build
- [ ] Open the Vercel URL → homepage shows real products (not empty)
- [ ] Open a product → price-comparison panel + "View at shop" work
- [ ] Browse → filters + infinite scroll load real listings
- [ ] GitHub Actions `Refresh catalog` succeeds for all three shops
- [ ] Footer warns users to verify final price and stock with the shop

If the deployed site is **empty**: the API URL is wrong/unset, the backend is asleep
(retry after ~40s), or CORS is blocking — confirm the backend origin regex matches your
Vercel domain (`https://.*\.vercel\.app`, already set in `backend/api/main.py`).

---

## Cleaning up the half-installed Vercel CLI (optional)

That `EPERM ... node_modules\vercel` error is a broken partial install. To clear it:
```powershell
npm rm -g vercel
# if it still complains, close all terminals/editors and delete the folder:
Remove-Item -Recurse -Force "$env:APPDATA\npm\node_modules\vercel"
```
You don't need it if you deploy via the dashboard.
