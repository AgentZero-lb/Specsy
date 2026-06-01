from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import listings

app = FastAPI(title="Specsy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router, prefix="/listings", tags=["listings"])


@app.get("/health")
def health():
    return {"status": "ok", "project": "Specsy"}
