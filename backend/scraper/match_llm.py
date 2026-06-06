"""LLM verification of embedding-flagged candidates (Haiku), then union same-product pairs.

Embeddings give recall but blur model numbers (G703 vs G305 score ~0.95), so we
can't auto-match on cosine. This pass takes the cross-shop candidate pairs the
embeddings flag (cosine >= CAND_MIN) and has claude-haiku-4-5 judge each pair
"same product? yes/no", then unions the confirmed-"same" pairs into products
(reusing scraper.match._ensure_product).

    python -m scraper.match_llm                 # dry: judge candidates, report, no DB writes
    python -m scraper.match_llm --limit 80      # judge only the first N (quick quality check)
    python -m scraper.match_llm --apply         # + create/extend products from confirmed-same pairs

Idempotent: verdicts are cached locally (re-runs don't re-spend tokens), products
are reused. Embeddings come from the cached Voyage run (no Voyage calls here).
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
from scraper.match import DSU, _ensure_product, load_listings
from scraper.match_vector import cross_shop_neighbors, embed, listing_text

load_dotenv()

MODEL = "claude-haiku-4-5"
CAND_MIN = 0.84       # only verify pairs the embeddings scored at least this similar
BATCH = 18            # pairs per Haiku call
MAX_GROUP = 12        # safety cap on product cluster size
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
"i7-13700K" vs "i7-13700KF"; "Phantom Spirit 120" vs "120 EVO"; Pro vs non-Pro; \
Wireless vs Wired when it defines the SKU.
- Different brand entirely: MSI PSU vs Gigabyte PSU; noblechairs chair vs Havit chair.

Treat as SAME:
- Same model, only trivial wording/order/punctuation/marketing differences ("(TAX included)", \
"Gaming", casing) or one title adds the SKU/part-number while the model still matches.
- Same laptop/device model code (e.g. both "Lenovo V15 G5 83HF00EMIG"), even if one lists more specs.
- A genuine rebrand of the SAME item (e.g. "HyperX Fury" and "Kingston Fury" — HyperX memory \
became Kingston Fury) ONLY when model + capacity + speed all match.

When unsure, answer DIFFERENT — a false merge is worse than a missed match.

Examples:
- "Logitech G703 Lightspeed Wireless Mouse" / "Logitech G305 Lightspeed Wireless Mouse" -> DIFFERENT
- "Samsung Odyssey G5 QHD 180Hz" / "Samsung Odyssey G4 FHD 240Hz" -> DIFFERENT
- "MSI MAG A850GL 850W PSU" / "Gigabyte GP-P850GM 850W Gold PSU" -> DIFFERENT
- "HyperX Fury 16GB DDR5-6000" / "Kingston Fury 16GB DDR5 6000Mhz KF560..." -> SAME
- "Lenovo V15 G5 IRL 83HF00EMIG i7 16GB 512GB 15.6 (TAX included)" / \
"Lenovo V15 G5 IRL 83HF00EMIG i7 16GB 15.6-inch Laptop" -> SAME

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
    """items: [{id, a, b}]. Returns {id: bool}. Empty dict on failure (treated as no-match)."""
    user = (
        "Judge whether each pair is the SAME product. Return a verdict per id.\n"
        "Pairs (JSON):\n" + json.dumps(items, ensure_ascii=False)
    )
    for attempt in range(4):
        try:
            resp = client.messages.parse(
                model=MODEL,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM,
                        # caches only when the prefix is >= the model minimum (4096 tok on
                        # Haiku); harmless otherwise. Keeps the stable instructions first.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user}],
                output_format=Verdicts,
            )
            out = resp.parsed_output
            if out is None:
                continue
            return {v.id: bool(v.same) for v in out.verdicts}
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # parse/validation hiccup — retry, then give up safely
            time.sleep(2)
    return {}


def run(apply: bool, limit: int):
    sb = get_client()
    cats = {c["slug"]: c["id"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)
    n = len(listings)

    texts = [listing_text(l) for l in listings]
    cache = embed(texts)  # already cached from the vector run -> instant, no API calls
    M = np.vstack([cache[t] for t in texts]).astype(np.float32)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9

    # candidate cross-shop pairs, deduped to a canonical (min,max) and sorted by score
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

    verdicts = {}        # (i,j) -> bool
    to_judge = []        # (i, j, a, b, key)
    for i, j, sc in pairs:
        # name + identity-relevant specs; for spec-less shops this == raw_name, so
        # previously-cached verdicts still hit and only Ayoub pairs get re-judged.
        a, b = listing_text(listings[i]), listing_text(listings[j])
        ck = _key(a, b)
        if ck in vcache:
            verdicts[(i, j)] = vcache[ck]
        else:
            to_judge.append((i, j, a, b, ck))

    print(
        f"candidate pairs >= {CAND_MIN}: {len(pairs)}  "
        f"(cached: {len(pairs) - len(to_judge)}, to judge: {len(to_judge)})",
        flush=True,
    )

    for b0 in range(0, len(to_judge), BATCH):
        chunk = to_judge[b0:b0 + BATCH]
        items = [{"id": k, "a": a, "b": b} for k, (i, j, a, b, ck) in enumerate(chunk)]
        res = _judge_batch(client, items)
        for k, (i, j, a, b, ck) in enumerate(chunk):
            same = bool(res.get(k, False))
            verdicts[(i, j)] = same
            vcache[ck] = same
        with open(VCACHE, "wb") as f:
            pickle.dump(vcache, f)
        print(f"  judged {min(b0 + BATCH, len(to_judge))}/{len(to_judge)}", flush=True)

    same_pairs = [(i, j) for (i, j), v in verdicts.items() if v]
    print(f"\nverdicts: {len(same_pairs)} SAME / {len(verdicts)} judged")

    def _show(label, want):
        print(f"--- sample {label} ---")
        shown = 0
        for (i, j), v in verdicts.items():
            if v != want:
                continue
            print(f"  {shops.get(listings[i]['shop_id'],'?')[:4]} {(listings[i]['raw_name'] or '')[:46]}")
            print(f"  {shops.get(listings[j]['shop_id'],'?')[:4]} {(listings[j]['raw_name'] or '')[:46]}\n")
            shown += 1
            if shown >= 8:
                break

    _show("SAME", True)
    _show("DIFFERENT", False)

    if not apply:
        print("DRY RUN — re-run with --apply to create products from the SAME pairs.")
        return

    dsu = DSU(n)
    touched = set()
    for i, j in same_pairs:
        dsu.union(i, j)
        touched.add(i)
        touched.add(j)
    comps = defaultdict(list)
    for i in touched:
        comps[dsu.find(i)].append(i)

    created = reused = new_listings = 0
    for idxs in comps.values():
        if len({listings[i]["shop_id"] for i in idxs}) < 2 or len(idxs) > MAX_GROUP:
            continue
        state, _ = _ensure_product(sb, listings, idxs, cats)
        if state == "created":
            created += 1
        else:
            reused += 1
        new_listings += len(idxs)

    total_matched = sum(1 for l in listings if l["product_id"])
    print(
        f"\nApplied: {created} products created, {reused} extended, "
        f"{new_listings} listings in confirmed clusters."
        f"\n  total matched listings now: {total_matched} "
        f"({100 * total_matched // max(n, 1)}% of in-scope)"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N candidate pairs")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 chokes on ″ / – in names
    run(apply=args.apply, limit=args.limit)
