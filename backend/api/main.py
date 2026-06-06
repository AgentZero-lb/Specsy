from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import listings, admin

app = FastAPI(title="Specsy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Exact origins for local dev; regex covers every Vercel deployment
    # (production + preview URLs like https://specsy-xyz.vercel.app).
    # Note: Starlette does NOT expand "https://*.vercel.app" as a wildcard —
    # it must be a regex, hence allow_origin_regex below.
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router, prefix="/listings", tags=["listings"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health")
def health():
    return {"status": "ok", "project": "Specsy"}
