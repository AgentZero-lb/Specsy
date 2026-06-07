# Specsy

PCPartPicker for Lebanon — compare PC part prices across Lebanese shops in USD and LBP.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 16, TypeScript, Tailwind CSS |
| Backend | Python 3.12, FastAPI |
| Scraper | httpx + selectolax (one module per shop) |
| Database | PostgreSQL + pgvector via Supabase |
| AI | Claude API — Haiku (classification) · Sonnet (builds + chat) |
| Deploy | Vercel (frontend) · Render (backend) · GitHub Actions (scrapers) |

## Getting started

### 1. Probe the data source

```bash
cd backend
pip install -r requirements.txt
python scraper/probe.py
```

This confirms whether the WooCommerce Store API on PCandParts is publicly
accessible from the current network. PCandParts blocks some cloud-hosted IPs, so
its refresh must run from a trusted network or a dedicated scheduled service.

### 2. Run the API

```bash
cd backend
uvicorn api.main:app --reload
# GET http://localhost:8000/health
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000
```

## Environment

Copy `.env.example` to `.env` and fill in your Supabase and Anthropic credentials.
