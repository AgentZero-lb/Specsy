"""Inspect raw identity-key candidate components WITHOUT touching the DB.

Builds cross-shop candidate components from strict identity keys, then runs the
Phase-1 divergence checks on those candidates. Suspect components are expected
here because production validation has not run yet.

    cd backend && python scripts/test_identity.py
    cd backend && python scripts/test_identity.py --cat ram   # dump one category's groups

This diagnostic runs before match.py's fail-closed validation. Use
`python -m scraper.match` for the authoritative accepted/quarantined projection.
"""
import argparse
import os
import sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for audit_matches
from scraper.db import get_client                 # noqa: E402
from scraper.identity import (                     # noqa: E402
    identity_keys, brand, gpu_chip, model_codes, _clean, _spec_lookup)
from audit_matches import extract_axes, AXES      # noqa: E402


def _distinct_models(g, listings):
    """Distinct title model-codes in a group, ignoring prefix/rendering variants
    (90YV0M17-M0NA00 vs ...-M0NA0). >1 left = likely different models merged."""
    codes = set()
    for i in g:
        codes |= model_codes(listings[i]["raw_name"], listings[i].get("raw_specs") or {})
    keep = []
    for c in sorted(codes, key=len, reverse=True):
        if not any(c in k or k in c for k in keep):   # collapse substring/rendering variants
            keep.append(c)
    return keep


def _brand_of(l):
    return brand(_clean(l["raw_name"]), _spec_lookup(l.get("raw_specs") or {}))


def _chip_of(l):
    return gpu_chip(_clean(l["raw_name"]), _spec_lookup(l.get("raw_specs") or {}))

MAX_GROUP = 12
HARD = {"brand", "capacity", "chip", "wattage", "size", "refresh", "resolution", "kit"}


class DSU:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[ra] = rb


def load(sb):
    cats = {c["id"]: c["slug"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    rows, page, PAGE = [], 0, 1000
    while True:
        chunk = (sb.table("listings")
                 .select("id, shop_id, sku, raw_name, category_slug, product_id, price_usd, raw_specs")
                 .not_.is_("category_slug", "null")
                 .range(page * PAGE, page * PAGE + PAGE - 1).execute().data)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        page += 1
    return cats, shops, rows


def run(focus_cat: str):
    sb = get_client()
    cats, shops, listings = load(sb)
    n = len(listings)
    cur_matched = sum(1 for l in listings if l["product_id"])

    # ---- Pass 1: cross-shop exact SKU ----
    dsu = DSU(n)
    by_sku = defaultdict(list)
    for i, l in enumerate(listings):
        s = (l["sku"] or "").strip()
        if s:
            by_sku[s].append(i)
    sku_unions = 0
    for idxs in by_sku.values():
        if len({listings[i]["shop_id"] for i in idxs}) >= 2:
            for j in idxs[1:]:
                dsu.union(idxs[0], j); sku_unions += 1

    # ---- Pass 2: identity keys ----
    key_index = defaultdict(list)
    no_key = 0
    for i, l in enumerate(listings):
        keys = identity_keys(l["category_slug"], l["raw_name"], l.get("raw_specs") or {}, l["sku"])
        if not keys:
            no_key += 1
        for k in keys:
            key_index[k].append(i)
    for key, idxs in key_index.items():
        if len({listings[i]["shop_id"] for i in idxs}) >= 2:
            for j in idxs[1:]:
                dsu.union(idxs[0], j)

    comps = defaultdict(list)
    for i in range(n):
        comps[dsu.find(i)].append(i)
    groups = [g for g in comps.values()
              if len({listings[i]["shop_id"] for i in g}) >= 2 and len(g) <= MAX_GROUP]
    oversized = [g for g in comps.values() if len(g) > MAX_GROUP]
    matched = sum(len(g) for g in groups)

    # ---- quality checks on projected groups ----
    # PRIMARY (identity-side, precise): a group spanning >1 brand, or >1 GPU chip, is a
    # genuine over-merge bug. SECONDARY: the cruder Phase-1 audit divergence (may
    # over-flag when one shop omits a detail, e.g. SSD) — informational only.
    crossbrand = crosschip = soft_suspect = 0
    cat_groups = Counter()
    cat_matched = Counter()
    bugs = []
    soft_groups = []
    multi_code = []
    for g in groups:
        cat = listings[g[0]]["category_slug"]
        cat_groups[cat] += 1
        cat_matched[cat] += len(g)
        brands = {b for b in (_brand_of(listings[i]) for i in g) if b}
        chips = {c for c in (_chip_of(listings[i]) for i in g) if c} if cat == "gpu" else set()
        bug = None
        if len(brands) > 1:
            bug = f"CROSS-BRAND {sorted(brands)}"
        elif len(chips) > 1:
            bug = f"CROSS-CHIP {sorted(chips)}"
        if bug:
            if len(brands) > 1:
                crossbrand += 1
            else:
                crosschip += 1
            bugs.append((cat, bug, g))
            continue
        per_axis = defaultdict(set)
        for i in g:
            for k, v in extract_axes(listings[i]["raw_name"], listings[i].get("raw_specs") or {},
                                     listings[i]["category_slug"]).items():
                if v:
                    per_axis[k].add(v)
        diff = [a for a in AXES if len(per_axis.get(a, set())) > 1 and a in HARD]
        models = _distinct_models(g, listings)
        if len(models) > 1:
            multi_code.append((cat, models, g))
        elif diff:
            soft_suspect += 1
            soft_groups.append((cat, diff, g))

    print(f"in-scope listings        : {n}")
    print(f"current matched (old)    : {cur_matched} ({100*cur_matched//n}%)")
    print(f"PRE-VALIDATION candidates: {matched} ({100*matched//n}%)   "
          f"[delta {matched-cur_matched:+d}]")
    print(f"candidate components     : {len(groups)}   (oversized >{MAX_GROUP} skipped: {len(oversized)})")
    print(f"listings with NO identity key (-> queue) : {no_key}")
    print(f"\nPRE-VALIDATION candidate quality (production quarantines suspects):")
    print(f"  CROSS-BRAND groups (real bug)  : {crossbrand}   <-- must be 0")
    print(f"  CROSS-CHIP gpu groups (real bug): {crosschip}   <-- must be 0")
    print(f"  MULTI-MODEL-CODE groups (likely over-merge): {len(multi_code)}   <-- must be ~0")
    print(f"  audit hard-conflict (a shop omitting a detail): {soft_suspect}")

    print("\ncandidates by category (groups / listings):")
    for cat in sorted(cat_groups, key=lambda c: -cat_matched[c]):
        print(f"  {cat:<14} {cat_groups[cat]:>4} groups / {cat_matched[cat]:>4} listings")

    if bugs:
        print(f"\n!!! {len(bugs)} REAL-BUG GROUPS (cross-brand / cross-chip) !!!")
        for cat, why, g in bugs[:15]:
            print(f"\n[{cat}] {why}")
            for i in g:
                print(f"    [{shops.get(listings[i]['shop_id'],'?')[:4]}] {(listings[i]['raw_name'] or '')[:74]}")

    # groups carrying >1 distinct model code = different models merged by a too-coarse
    # spec key (the precision risk brand/capacity checks can't see)
    mc = Counter(c for c, _, _ in multi_code)
    print(f"\n--- {len(multi_code)} MULTI-MODEL-CODE groups by category: {dict(mc)} ---")
    for cat, models, g in multi_code[:25]:
        print(f"\n[{cat}] codes={models}")
        for i in g:
            print(f"    [{shops.get(listings[i]['shop_id'],'?')[:4]}] {(listings[i]['raw_name'] or '')[:74]}")

    # ---- dump a category's groups for eyeballing (default: gpu) ----
    dump = focus_cat or "gpu"
    print(f"\n========== PRE-VALIDATION {dump.upper()} CANDIDATES ==========")
    shown = 0
    for g in sorted(groups, key=lambda g: -len(g)):
        if listings[g[0]]["category_slug"] != dump:
            continue
        prices = [listings[i]["price_usd"] for i in g if listings[i]["price_usd"] is not None]
        spread = f"  spread ${max(prices)-min(prices):.0f}" if len(prices) >= 2 else ""
        print(f"\n  group of {len(g)}{spread}")
        for i in g:
            p = f"${listings[i]['price_usd']}" if listings[i]["price_usd"] is not None else "—"
            print(f"    [{shops.get(listings[i]['shop_id'],'?')[:4]}] {p:>8}  {(listings[i]['raw_name'] or '')[:70]}")
        shown += 1
        if shown >= 40:
            break


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="gpu")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.cat)
