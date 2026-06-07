"""Haiku candidate verifier — QUEUE ONLY. Never merges.

Demoted from an auto-matcher: the LLM may only *propose* candidates into match_queue
for human review. It NEVER sets listings.product_id and NEVER creates/merges products —
that authority belongs solely to scraper.match (SKU + identity rules).

It judges embedding-flagged cross-shop pairs ("same product? yes/no"). For pairs it
confirms SAME where exactly one side is already matched, it enqueues the unmatched
listing against the matched product as a pending candidate.

IMPORTANT: API/parse failures are NEVER cached. A failed judgement is left UNJUDGED
(ret* next run) — it is never recorded as a rejection. Only genuine yes/no verdicts are
cached.

    python -m scraper.match_llm                 # dry: judge, report SAME/DIFFERENT samples
    python -m scraper.match_llm --apply         # enqueue LLM-confirmed candidates (queue only)
    python -m scraper.match_llm --limit 80      # judge only the first N (quick check)
"""
import argparse
import json
import os
import pickle
import sys
import tempfile
import time
from collections import defaultdict

import anthropic
import numpy as np
from dotenv import load_dotenv
from pydantic import BaseModel

from scraper.db import get_client
from scraper.match import load_listings                       # shared loader only
from scraper.match_vector import cross_shop_neighbors, embed, listing_text

load_dotenv()

MODEL = "claude-haiku-4-5"
CAND_MIN = 0.84
BATCH = 18
VCACHE = os.path.join(tempfile.gettempdir(), "specsy_llm_verdicts.pkl")

SYSTEM = """You match product listings between two Lebanese computer/electronics shops. \
Each pair is two product titles. Decide if they are the SAME product — a buyer would treat \
them as interchangeable: same brand line, same model/SKU, same identity-defining specs.

Answer SAME (true) ONLY when the core model identity matches. Answer DIFFERENT (false) when \
any identity-defining attribute differs.

Treat as DIFFERENT:
- Different model numbers: "Logitech G703" vs "G305"; monitor "VG279Q1R" vs "VG27AQML1A".
- Different capacity/size: 16GB vs 32GB; 4TB vs 2TB; 27-inch vs 32-inch.
- Different generation/variant/suffix: "Odyssey G5" vs "G4"; "RTX 4070" vs "RTX 4070 Super"; \
"i7-13700K" vs "i7-13700KF"; AIB partner/cooler variant (ASUS Dual vs ASUS Prime vs Zotac).
- Different brand entirely: MSI PSU vs Gigabyte PSU; noblechairs chair vs Havit chair.

Treat as SAME:
- Same model, only trivial wording/order/punctuation/marketing differences or one title adds \
the SKU/part-number while the model still matches.
- Same laptop/device model code (e.g. both "Lenovo V15 G5 83HF00EMIG"), even if one lists more specs.

When unsure, answer DIFFERENT — a false merge is worse than a missed match.

For each input pair, return its id and same=true/false."""


class Verdict(BaseModel):
    id: int
    same: bool


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def _key(a: str, b: str) -> str:
    return "␟".join(sorted([a or "", b or ""]))


def _load_vcache() -> dict:
    try:
        with open(VCACHE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _judge_batch(client, items: list[dict]) -> dict:
    """items: [{id, a, b}]. Returns {id: bool} for ids the model actually judged.
    Returns {} on failure — callers MUST treat missing ids as UNJUDGED, never as 'no'."""
    user = ("Judge whether each pair is the SAME product. Return a verdict per id.\n"
            "Pairs (JSON):\n" + json.dumps(items, ensure_ascii=False))
    for attempt in range(4):
        try:
            resp = client.messages.parse(
                model=MODEL, max_tokens=2048,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_format=Verdicts,
            )
            out = resp.parsed_output
            if out is None:
                continue
            return {v.id: bool(v.same) for v in out.verdicts}
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(2)
    return {}


def run(apply: bool, limit: int):
    sb = get_client()
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)

    texts = [listing_text(l) for l in listings]
    cache = embed(texts)
    M = np.vstack([cache[t] for t in texts]).astype(np.float32)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9

    seen, pairs = set(), []
    for i, j, sc in cross_shop_neighbors(listings, M):
        if sc < CAND_MIN:
            continue
        k = (min(i, j), max(i, j))
        if k not in seen:
            seen.add(k)
            pairs.append((k[0], k[1], sc))
    pairs.sort(key=lambda p: -p[2])
    if limit:
        pairs = pairs[:limit]

    vcache = _load_vcache()
    client = anthropic.Anthropic(max_retries=5)

    verdicts = {}        # (i,j) -> bool  (only genuinely judged pairs)
    failed = 0
    to_judge = []        # (i, j, a, b, ck)
    for i, j, sc in pairs:
        a, b = listing_text(listings[i]), listing_text(listings[j])
        ck = _key(a, b)
        if ck in vcache:
            verdicts[(i, j)] = vcache[ck]
        else:
            to_judge.append((i, j, a, b, ck))

    print(f"candidate pairs >= {CAND_MIN}: {len(pairs)}  "
          f"(cached: {len(pairs) - len(to_judge)}, to judge: {len(to_judge)})", flush=True)

    for b0 in range(0, len(to_judge), BATCH):
        chunk = to_judge[b0:b0 + BATCH]
        items = [{"id": k, "a": a, "b": b} for k, (i, j, a, b, ck) in enumerate(chunk)]
        res = _judge_batch(client, items)
        for k, (i, j, a, b, ck) in enumerate(chunk):
            if k not in res:        # FAILED/missing -> leave unjudged; do NOT cache as 'no'
                failed += 1
                continue
            verdicts[(i, j)] = res[k]
            vcache[ck] = res[k]     # cache ONLY genuine verdicts
        with open(VCACHE, "wb") as f:
            pickle.dump(vcache, f)
        print(f"  judged {min(b0 + BATCH, len(to_judge))}/{len(to_judge)}", flush=True)

    same_pairs = [(i, j) for (i, j), v in verdicts.items() if v]
    print(f"\nverdicts: {len(same_pairs)} SAME / {len(verdicts)} judged "
          f"({failed} unjudged due to API/parse failure — NOT cached, NOT rejected)")

    def _show(label, want):
        print(f"--- sample {label} ---")
        shown = 0
        for (i, j), v in verdicts.items():
            if v != want:
                continue
            print(f"  {shops.get(listings[i]['shop_id'],'?')[:4]} {(listings[i]['raw_name'] or '')[:46]}")
            print(f"  {shops.get(listings[j]['shop_id'],'?')[:4]} {(listings[j]['raw_name'] or '')[:46]}\n")
            shown += 1
            if shown >= 6:
                break
    _show("SAME", True)
    _show("DIFFERENT", False)

    # confirmed-SAME pairs with exactly one matched side -> enqueue unmatched->product
    candidates = []
    for (i, j) in same_pairs:
        pi, pj = listings[i]["product_id"], listings[j]["product_id"]
        if pi and not pj:
            candidates.append((j, pi))
        elif pj and not pi:
            candidates.append((i, pj))
        # both matched (different products) or neither matched -> cannot queue as listing->product
    print(f"\nLLM-confirmed enqueueable candidates (one side matched): {len(candidates)}")

    if not apply:
        print("DRY RUN — no writes. Re-run with --apply to enqueue candidates (queue only).")
        return

    qids = [lid for lid, _ in candidates]
    for k in range(0, len(qids), 200):
        sb.table("match_queue").delete().in_("listing_id",
            [listings[i]["id"] for i in qids[k:k + 200]]).eq("status", "pending").execute()
    rows = [{"listing_id": listings[i]["id"], "candidate_product_id": pid,
             "similarity_score": None, "status": "pending"} for i, pid in candidates]
    for k in range(0, len(rows), 200):
        if rows[k:k + 200]:
            sb.table("match_queue").insert(rows[k:k + 200]).execute()
    print(f"Enqueued {len(rows)} LLM-confirmed pending candidates (no products touched).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="enqueue LLM-confirmed candidates to match_queue")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(apply=args.apply, limit=args.limit)
