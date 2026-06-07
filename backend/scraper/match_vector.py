"""Embedding (Voyage) candidate generator — QUEUE ONLY. Never merges.

Demoted from an auto-matcher: under the identity-rule regime, embeddings are recall-
biased and blur model numbers, so they may ONLY *propose* candidates into match_queue
for human review. This module NEVER sets listings.product_id and NEVER creates or merges
products — that authority belongs solely to scraper.match (SKU + identity rules).

For each still-unmatched listing whose best cross-shop neighbour is already MATCHED, if
the cosine is at least --min we queue (listing -> that neighbour's product) as a pending
candidate. Unmatched<->unmatched pairs are reported but not queued (no product to point
to — they wait for the identity matcher).

    python -m scraper.match_vector                    # dry: distribution + samples
    python -m scraper.match_vector --apply --min 0.84 # write pending candidates to match_queue
"""
import argparse
import os
import pickle
import re
import sys
import tempfile
import time
from collections import defaultdict

import httpx
import numpy as np
from dotenv import load_dotenv

from scraper.db import get_client
from scraper.match import load_listings   # shared loader only (no merge primitive imported)

load_dotenv()
VOYAGE_KEY = (os.environ.get("VOYAGE_API_KEY") or "").strip()
MODEL = "voyage-3"
CACHE = os.path.join(tempfile.gettempdir(), "specsy_voyage_emb.pkl")
BATCH = 120

_SPEC_SKIP = {"class", "series", "warranty", "color", "colour", "condition"}


def _emb_text(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(tax includ[^)]*\)?", "", name or "", flags=re.I)).strip()


def listing_text(listing: dict) -> str:
    """Cleaned name plus identity-relevant spec values not already in the name."""
    name = _emb_text(listing.get("raw_name") or "")
    specs = listing.get("raw_specs") or {}
    if not specs:
        return name
    nlow = name.lower()
    extra = []
    for k, v in specs.items():
        if not v or str(k).strip().lower() in _SPEC_SKIP:
            continue
        val = str(v).strip()
        if not val or val.lower() in nlow or val.lower() in " ".join(extra).lower():
            continue
        extra.append(val)
    return (name + " " + " ".join(extra)).strip() if extra else name


def _load_cache() -> dict:
    try:
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def embed(texts: list[str], verbose: bool = True) -> dict:
    """Embed unseen texts; ONLY successful responses are cached (failures never poison
    the cache). Raises on exhausted retries rather than caching a bad/empty vector."""
    cache = _load_cache()
    todo = sorted({t for t in texts if t and t not in cache})
    if verbose:
        print(f"embedding {len(todo)} new texts ({len(set(texts)) - len(todo)} cached)")
    with httpx.Client(timeout=90) as client:
        for k in range(0, len(todo), BATCH):
            batch = todo[k:k + BATCH]
            for attempt in range(20):
                r = client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {VOYAGE_KEY}"},
                    json={"input": batch, "model": MODEL, "input_type": "document"},
                )
                if r.status_code == 200:
                    break
                if r.status_code == 429:
                    time.sleep(22)
                    continue
                if r.status_code in (500, 502, 503):
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"voyage {r.status_code}: {r.text[:200]}")
            else:
                raise RuntimeError("voyage: retries exhausted")
            for item in sorted(r.json()["data"], key=lambda x: x["index"]):
                cache[batch[item["index"]]] = np.asarray(item["embedding"], dtype=np.float32)
            with open(CACHE, "wb") as f:
                pickle.dump(cache, f)
            if verbose:
                print(f"  embedded {min(k + BATCH, len(todo))}/{len(todo)}", flush=True)
            time.sleep(2)
    return cache


def cross_shop_neighbors(listings, M):
    """For each UNMATCHED listing, its best same-category, different-shop neighbour.
    Returns [(i, j, score)] with i unmatched."""
    by_cat = defaultdict(list)
    for i, l in enumerate(listings):
        by_cat[l["category_slug"]].append(i)
    pairs = []
    for idxs in by_cat.values():
        if len(idxs) < 2:
            continue
        sub = np.array(idxs)
        sims = M[sub] @ M[sub].T
        shop = np.array([listings[i]["shop_id"] for i in sub])
        for a in range(len(sub)):
            if listings[sub[a]]["product_id"] is not None:
                continue
            row = sims[a].copy()
            row[a] = -1.0
            row[shop == shop[a]] = -1.0
            b = int(np.argmax(row))
            sc = float(row[b])
            if sc > 0:
                pairs.append((int(sub[a]), int(sub[b]), sc))
    return pairs


def run(apply: bool, min_score: float):
    if not VOYAGE_KEY:
        raise SystemExit("VOYAGE_API_KEY not set")
    sb = get_client()
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)
    n = len(listings)

    texts = [listing_text(l) for l in listings]
    cache = embed(texts)
    M = np.vstack([cache[t] for t in texts]).astype(np.float32)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9

    pairs = cross_shop_neighbors(listings, M)
    # only pairs whose neighbour is already matched can become a (listing -> product) candidate
    candidates = [(i, j, sc) for i, j, sc in pairs
                  if listings[j]["product_id"] and sc >= min_score]
    no_product = sum(1 for i, j, sc in pairs if not listings[j]["product_id"] and sc >= min_score)

    print(f"in-scope listings              : {n}")
    print(f"unmatched w/ cross-shop nbr    : {len(pairs)}")
    print(f"candidates (nbr matched, cos>= {min_score}) -> queue : {len(candidates)}")
    print(f"high-sim pairs with NO matched side (cannot queue)   : {no_product}")
    print("\n--- sample candidates ---")
    for i, j, sc in sorted(candidates, key=lambda p: -p[2])[:12]:
        print(f"  {sc:.3f}  {shops.get(listings[i]['shop_id'],'?')[:4]} {(listings[i]['raw_name'] or '')[:50]}")
        print(f"         -> product of  {shops.get(listings[j]['shop_id'],'?')[:4]} {(listings[j]['raw_name'] or '')[:50]}")

    if not apply:
        print("\nDRY RUN — no writes. Re-run with --apply to enqueue candidates (queue only).")
        return

    # write candidates to match_queue ONLY (idempotent: refresh pending for these listings).
    # No product_id is ever set and no product is created/merged here.
    qids = [listings[i]["id"] for i, _, _ in candidates]
    for k in range(0, len(qids), 200):
        sb.table("match_queue").delete().in_("listing_id", qids[k:k + 200]).eq(
            "status", "pending").execute()
    rows = [{"listing_id": listings[i]["id"], "candidate_product_id": listings[j]["product_id"],
             "similarity_score": round(sc, 4), "status": "pending"} for i, j, sc in candidates]
    for k in range(0, len(rows), 200):
        if rows[k:k + 200]:
            sb.table("match_queue").insert(rows[k:k + 200]).execute()
    print(f"\nEnqueued {len(rows)} pending candidates to match_queue (no products touched).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write pending candidates to match_queue")
    ap.add_argument("--min", type=float, default=0.84, dest="min_score")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(apply=args.apply, min_score=args.min_score)
