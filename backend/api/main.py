import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import listings, products

app = FastAPI(title="Specsy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Exact origins for local dev; regex covers every Vercel deployment
    # (production + preview URLs like https://specsy-xyz.vercel.app).
    # Note: Starlette does NOT expand "https://*.vercel.app" as a wildcard —
    # it must be a regex, hence allow_origin_regex below.
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)

app.include_router(listings.router, prefix="/listings", tags=["listings"])
app.include_router(products.router, prefix="/products", tags=["products"])

# Internal QA endpoints are expensive and expose matching diagnostics. Keep them
# absent from public deployments unless an operator explicitly enables them.
if os.getenv("ENABLE_ADMIN_ROUTES", "").lower() == "true":
    from api.routers import admin

    app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health")
def health():
    return {"status": "ok", "project": "Specsy"}
