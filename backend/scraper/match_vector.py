"""Fuzzy cross-shop matching via Voyage embeddings + cosine (the pgvector pass).

Embeds in-scope listings (voyage-3, cached locally), then within each category
links every still-unmatched listing to its nearest cross-shop neighbour:
  cos >= HIGH                         -> attach to that neighbour's product, or
                                         (neighbour also unmatched) form a new product
  MID <= cos < HIGH, neighbour matched -> match_queue row for human review

    python -m scraper.match_vector                          # dry: distribution + banded samples
    python -m scraper.match_vector --apply --high 0.88 --mid 0.82

Idempotent: only unmatched listings are processed, products are reused, and the
pending queue for the affected listings is refreshed (not duplicated) on re-run.
Embeddings are cached in the OS temp dir, so re-runs don't re-spend tokens.
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
from scraper.match import DSU, _ensure_product, load_listings

load_dotenv()
VOYAGE_KEY = (os.environ.get("VOYAGE_API_KEY") or "").strip()
MODEL = "voyage-3"
CACHE = os.path.join(tempfile.gettempdir(), "specsy_voyage_emb.pkl")
BATCH = 120           # ~3K tokens/request — fits trial key's 10K TPM at 3 RPM
MAX_GROUP = 12        # safety cap on new-product cluster size


def _emb_text(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(tax includ[^)]*\)?", "", name or "", flags=re.I)).strip()


# spec fields that are marketing/grouping noise rather than identity signal
_SPEC_SKIP = {"class", "series", "warranty", "color", "colour", "condition"}


def listing_text(listing: dict) -> str:
    """Text fed to embeddings + Haiku: cleaned name plus identity-relevant spec VALUES
    (capacity, size, speed, chip, brand) that aren't already in the name.

    Listings with no raw_specs (PCandParts, Macrotronics) return name-only — byte-for-byte
    equal to the old `_emb_text(raw_name)`, so their cached embeddings/verdicts stay valid;
    only spec-bearing listings (Ayoub) get enriched text."""
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
            continue  # skip values already covered by the name or an earlier spec
        extra.append(val)
    return (name + " " + " ".join(extra)).strip() if extra else name


def _load_cache() -> dict:
    try:
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def embed(texts: list[str], verbose: bool = True) -> dict:
    cache = _load_cache()
    todo = sorted({t for t in texts if t and t not in cache})
    if verbose:
        print(f"embedding {len(todo)} new texts ({len(set(texts)) - len(todo)} cached)")
    with httpx.Client(timeout=90) as client:
        for k in range(0, len(todo), BATCH):
            batch = todo[k : k + BATCH]
            for attempt in range(20):
                r = client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {VOYAGE_KEY}"},
                    json={"input": batch, "model": MODEL, "input_type": "document"},
                )
                if r.status_code == 200:
                    break
                if r.status_code == 429:        # trial key: 3 RPM / 10K TPM — wait the window out
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
            time.sleep(2)  # stay comfortably under 3 RPM
    return cache


def cross_shop_neighbors(listings, M):
    """For each unmatched listing, its best same-category, different-shop neighbour.
    Returns list of (i, j, score)."""
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
                continue  # only unmatched targets
            row = sims[a].copy()
            row[a] = -1.0
            row[shop == shop[a]] = -1.0  # cross-shop only
            b = int(np.argmax(row))
            sc = float(row[b])
            if sc > 0:
                pairs.append((int(sub[a]), int(sub[b]), sc))
    return pairs


def run(apply: bool, high: float, mid: float):
    if not VOYAGE_KEY:
        raise SystemExit("VOYAGE_API_KEY not set")

    sb = get_client()
    cats = {c["slug"]: c["id"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)
    n = len(listings)
    already = sum(1 for l in listings if l["product_id"])

    texts = [listing_text(l) for l in listings]
    cache = embed(texts)
    M = np.vstack([cache[t] for t in texts]).astype(np.float32)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9

    pairs = cross_shop_neighbors(listings, M)
    scores = np.array([p[2] for p in pairs]) if pairs else np.array([])

    print(f"\nin-scope listings           : {n}  (already matched: {already})")
    print(f"unmatched w/ cross-shop nbr : {len(pairs)}")
    print("nearest cross-shop cosine distribution:")
    for lo in (0.95, 0.92, 0.90, 0.88, 0.85, 0.82, 0.80, 0.75, 0.70):
        print(f"   cos >= {lo:.2f} : {(scores >= lo).sum()}")

    print("\n--- banded samples (i  ->  best cross-shop neighbour) ---")
    bands = [(0.95, 1.01), (0.90, 0.95), (0.88, 0.90), (0.85, 0.88), (0.82, 0.85), (0.78, 0.82)]
    ps = sorted(pairs, key=lambda p: -p[2])
    for lo, hi in bands:
        sample = [p for p in ps if lo <= p[2] < hi][:4]
        if not sample:
            continue
        print(f"  [{lo:.2f}, {hi:.2f}):")
        for i, j, sc in sample:
            li, lj = listings[i], listings[j]
            print(f"    {sc:.3f}  {shops.get(li['shop_id'],'?')[:4]} {(li['raw_name'] or '')[:48]}")
            print(f"           {shops.get(lj['shop_id'],'?')[:4]} {(lj['raw_name'] or '')[:48]}")

    if not apply:
        print("\nDRY RUN — pick thresholds, then re-run with --apply --high H --mid M.")
        return

    # ---- apply ----
    dsu = DSU(n)
    attach_ops, queued, touched = [], [], set()
    for i, j, sc in pairs:
        if sc >= high:
            if listings[j]["product_id"]:
                attach_ops.append((i, listings[j]["product_id"]))
            else:
                dsu.union(i, j)
                touched.add(i)
                touched.add(j)
        elif sc >= mid and listings[j]["product_id"]:
            queued.append((i, listings[j]["product_id"], sc))

    # attach unmatched listings onto an existing (deterministic) product
    attached = 0
    for i, pid in attach_ops:
        if listings[i]["product_id"]:
            continue
        sb.table("listings").update({"product_id": pid}).eq("id", listings[i]["id"]).execute()
        sb.table("product_aliases").upsert(
            {"product_id": pid, "alias": (listings[i]["raw_name"] or "")[:500], "source": "vector"},
            on_conflict="alias",
            ignore_duplicates=True,
        ).execute()
        listings[i]["product_id"] = pid
        attached += 1

    # form NEW products from clusters of unmatched↔unmatched high-similarity listings
    comps = defaultdict(list)
    for i in touched:
        comps[dsu.find(i)].append(i)
    new_products = new_listings = 0
    for idxs in comps.values():
        if len({listings[i]["shop_id"] for i in idxs}) < 2 or len(idxs) > MAX_GROUP:
            continue
        _ensure_product(sb, listings, idxs, cats)
        new_products += 1
        new_listings += len(idxs)

    # middle band -> match_queue (idempotent: clear pending for these listings first)
    qids = [listings[i]["id"] for i, _, _ in queued]
    for k in range(0, len(qids), 200):
        sb.table("match_queue").delete().in_("listing_id", qids[k : k + 200]).eq(
            "status", "pending"
        ).execute()
    qrows = [
        {
            "listing_id": listings[i]["id"],
            "candidate_product_id": pid,
            "similarity_score": round(sc, 4),
            "status": "pending",
        }
        for i, pid, sc in queued
    ]
    for k in range(0, len(qrows), 200):
        if qrows[k : k + 200]:
            sb.table("match_queue").insert(qrows[k : k + 200]).execute()

    total_matched = sum(1 for l in listings if l["product_id"])
    print(
        f"\nApplied (high={high}, mid={mid}):"
        f"\n  attached to existing products : {attached}"
        f"\n  new products from clusters     : {new_products} ({new_listings} listings)"
        f"\n  queued for review              : {len(qrows)}"
        f"\n  total matched listings now     : {total_matched} "
        f"({100 * total_matched // max(n, 1)}% of in-scope)"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--high", type=float, default=0.88)
    ap.add_argument("--mid", type=float, default=0.82)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 chokes on ″ / – in names
    run(apply=args.apply, high=args.high, mid=args.mid)
