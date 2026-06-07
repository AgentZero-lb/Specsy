"""Deterministic, reversible, fail-closed cross-shop matching (the ONLY auto-merge path).

Passes (union-find over the result):
  Pass 1  exact normalized cross-shop SKU — only unions listings that are also
          category- AND brand-compatible (a shared junk SKU is a CONFLICT, not a match).
  Pass 2  scraper.identity strict identity keys.

Then EVERY completed component is VALIDATED before it can be applied (fail closed):
  * coherent category and brand,
  * coherent category-critical attributes (chip/vram, cpu, capacity, ddr/kit, size/refresh,
    wattage, laptop config, motherboard memory/WiFi/revision/line),
  * a single model-code family (no multi-model / bundle listings),
  * no name conflict (e.g. same MPN but "Saga" vs "Surge" — bad upstream data),
  * no listing whose title disagrees with its raw_specs.
Components that fail are QUARANTINED (reported, never written) — this also prevents
transitive A-B-C merges, since an incompatible C makes the whole component incoherent.
Each accepted listing stores the EXACT key(s) that linked it (not a single group key).

Failure-safe rebuild (only with --reset --apply):
  1. export current listing_id->product_id mapping (backup),
  2. create fresh products + STAGE decisions (status='staged', rebuild_run_id) — current
     mappings stay LIVE, nothing is unlinked yet,
  3. validate the staged set,
  4. atomically activate via the activate_rebuild() SQL function (one transaction):
     supersede old decisions, repoint listings, unlink listings not in the rebuild,
     flip staged->active. A failure anywhere before step 4 leaves production untouched.
  Recovery: scripts/restore_mapping.py re-applies any exported backup.

Nothing is ever deleted (listings, snapshots, scrape_runs, products all preserved;
orphaned products are kept and reported). Reset is DRY unless --apply.

    python -m scraper.match                  # dry-run shadow rebuild + report (no writes)
    python -m scraper.match --reset          # same + reset plan (still no writes)
    python -m scraper.match --reset --apply  # staged rebuild + atomic activation
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from scraper.db import get_client
from scraper import identity

ALGO_VERSION = "match-2026.06.07-identity-v3-motherboard"
MAX_GROUP = 12
MIN_SKU_LEN = 4
DECISIONS_TABLE = "match_decisions"

# Generic words that never distinguish one model from another, used ONLY by the
# name-conflict guard (catches "same MPN, different model name" e.g. Saga vs Surge).
# True model-tier words (pro/max/plus/lite/se/elite/prime/hero/ace/saga/surge/…) are
# deliberately EXCLUDED so genuine variant differences still trigger. Genuinely different
# variants that share a generic word are already caught by the multi-model-code check.
_DESCRIPTORS = {
    # packaging / marketing
    "tray", "boxed", "box", "retail", "oem", "new", "desktop", "laptop", "processor",
    "gaming", "gamer", "unlocked", "boost", "performance", "premium", "edition",
    "version", "series", "generation", "official", "genuine", "original",
    # spec words
    "core", "cores", "thread", "threads", "ghz", "mhz", "dpi", "watt", "watts", "rgb",
    "argb", "led", "backlit", "hdr", "cache", "socket", "speed", "frequency",
    # connectivity / form
    "wired", "wireless", "bluetooth", "usb", "type", "gigabit", "ethernet", "pcie", "pci",
    "nic", "lan", "wan", "poe", "wifi", "band", "dual", "tri", "ceiling", "mount",
    "outdoor", "indoor", "portable", "external", "internal", "tower", "compact",
    # category nouns
    "mouse", "keyboard", "headset", "headphone", "headphones", "earbuds", "earbud",
    "earphone", "earphones", "speaker", "speakers", "monitor", "webcam", "microphone",
    "camera", "card", "adapter", "router", "switch", "system", "point", "access",
    "network", "controller", "cooler", "cooling", "fan", "fans", "heatsink", "radiator",
    "liquid", "kit", "pump", "case", "chassis", "power", "supply", "modular", "tube",
    "soft", "mesh", "whole", "home", "chair", "stand", "dock", "cable", "drive",
    "memory", "module", "express", "wireless",
    # adjectives / finishes
    "high", "slim", "curved", "smart", "ergonomic", "lightweight", "professional",
    "extra", "bass", "sound", "stereo", "surround", "noise", "with",
    # colors
    "black", "white", "silver", "grey", "gray", "red", "blue", "green", "orange",
    "gold", "pink", "purple", "magenta", "cyan", "yellow", "lemon", "lake", "cranberry",
    "flame", "fresh", "snow", "mirror", "rose", "graphite", "carbon", "color", "colour",
    # modularity / efficiency
    "fully", "semi", "bronze", "platinum", "titanium", "standard",
    # networking / form factor / packaging nouns (commonly vary between shops)
    "port", "rack", "rackmount", "mount", "mounted", "modem", "vdsl", "adsl", "omada",
    "nuclias", "connect", "wave", "pack", "plug", "play", "managed", "unmanaged", "easy",
    "sodimm", "dimm", "notebook", "valueram", "registered", "unbuffered", "broadcasting",
    "streaming", "ring", "light", "wall", "projection", "projector", "screen", "business",
    "office", "gaming", "ceiling",
    # storage / display tech vocab (varies in wording between shops)
    "nvme", "nmve", "ssd", "hdd", "sata", "solid", "state", "data", "traveler",
    "datatraveler", "microduo", "metal", "internal", "external", "dyac", "fast", "full",
    "oled", "panel", "nano", "dualband", "surveillance", "enterprise", "value",
}


# ───────────────────────────────── primitives ─────────────────────────────────


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def norm_sku(s) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "")).lower())


def brand_of(listing: dict):
    blob = identity._clean(listing.get("raw_name"))
    S = identity._spec_lookup(listing.get("raw_specs") or {})
    return identity.brand(blob, S) or identity.gpu_maker(blob, S)


def listing_keys(listing: dict) -> set:
    return identity.identity_keys(
        listing.get("category_slug"), listing.get("raw_name"),
        listing.get("raw_specs") or {}, listing.get("sku"),
    )


def load_listings(sb):
    cols = "id, shop_id, sku, raw_name, category_slug, product_id, price_usd, raw_specs"
    try:
        sb.table("listings").select(cols).limit(1).execute()
    except Exception:
        cols = "id, shop_id, sku, raw_name, category_slug, product_id, price_usd"
    rows, page, PAGE = [], 0, 1000
    while True:
        chunk = (sb.table("listings").select(cols)
                 .not_.is_("category_slug", "null")
                 .range(page * PAGE, page * PAGE + PAGE - 1).execute().data)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        page += 1
    for r in rows:
        r.setdefault("raw_specs", {})
    return rows


# ──────────────────────────── pure matching passes ────────────────────────────


def sku_pass(listings: list) -> tuple[list, list]:
    """Pass 1. (groups, conflicts). Same SKU but different brand/category -> conflict."""
    by = defaultdict(list)
    for i, l in enumerate(listings):
        s = norm_sku(l.get("sku"))
        if s and len(s) >= MIN_SKU_LEN:
            by[s].append(i)
    groups, conflicts = [], []
    for s, idxs in by.items():
        if len({listings[i]["shop_id"] for i in idxs}) < 2:
            continue
        by_cat = defaultdict(list)
        for i in idxs:
            by_cat[listings[i].get("category_slug")].append(i)
        if len(by_cat) > 1:
            conflicts.append(("category", s, idxs))
        for cat, cidxs in by_cat.items():
            brands = {brand_of(listings[i]) for i in cidxs}
            brands.discard(None)
            if len(brands) > 1:
                conflicts.append(("brand", s, cidxs))
                continue
            if len({listings[i]["shop_id"] for i in cidxs}) >= 2:
                groups.append((s, cidxs))
    return groups, conflicts


def _distinct_models(idxs, listings):
    codes = set()
    for i in idxs:
        codes |= identity.model_codes(listings[i]["raw_name"], listings[i].get("raw_specs") or {})
    keep = []
    for c in sorted(codes, key=len, reverse=True):
        if not any(c in k or k in c for k in keep):
            keep.append(c)
    return keep


def _model_name_tokens(name: str) -> set:
    """Significant model-name tokens (not brand/fluff/descriptor), brand-canonicalized
    (so 'tp link'->'tplink' drops the stray 'link') and plural-normalized ('port'=='ports')."""
    out = set()
    for t in identity._canon_brands(identity._clean(name)).split():
        if len(t) < 4 or not t.isalpha():
            continue
        t = t[:-1] if (len(t) >= 5 and t.endswith("s")) else t   # plural-normalize FIRST
        if t not in identity._BRANDS and t not in identity._GPU_MAKERS \
                and t not in identity._FLUFF and t not in _DESCRIPTORS:
            out.add(t)
    return out


def _name_conflict(idxs, listings) -> bool:
    """True if two members carry DIFFERENT distinctive model-name tokens (e.g. 'Saga' vs
    'Surge'): catches bad upstream MPNs that share a code but aren't the same product.
    Caller skips this for SKU-method groups (an exact MPN is authoritative)."""
    sets = [_model_name_tokens(listings[i]["raw_name"]) for i in idxs]
    shared = set.intersection(*sets) if sets else set()
    distinctive = [s - shared for s in sets if (s - shared)]
    for a in range(len(distinctive)):
        for b in range(a + 1, len(distinctive)):
            if distinctive[a].isdisjoint(distinctive[b]):
                return True
    return False


def validate_group(idxs, listings, sku_linked=False) -> tuple[bool, list]:
    """A completed component is ACCEPTED only if it is coherent on every category-critical
    axis. Otherwise it is QUARANTINED (fail closed). Returns (ok, reasons).
    name-conflict is skipped for SKU-method groups (an exact MPN is authoritative)."""
    reasons = []
    cat = listings[idxs[0]]["category_slug"]
    if len({listings[i]["category_slug"] for i in idxs}) > 1:
        reasons.append("multi-category")
    brands = {brand_of(listings[i]) for i in idxs} - {None}
    if len(brands) > 1:
        reasons.append(f"cross-brand:{sorted(brands)}")

    def nvals(fn):
        s = set()
        for i in idxs:
            blob = identity._clean(listings[i]["raw_name"])
            S = identity._spec_lookup(listings[i].get("raw_specs") or {})
            v = fn(blob, S)
            if v is not None:
                s.add(v)
        return len(s)

    checks = {
        "gpu": [("cross-chip", lambda b, S: identity.gpu_chip(b, S)),
                ("vram-conflict", lambda b, S: identity.vram(b, S))],
        "cpu": [("cpu-conflict", lambda b, S: identity.cpu_model(b))],
        "ram": [("ddr-conflict", lambda b, S: identity.ddr_gen(b, S)),
                ("capacity-conflict", lambda b, S: identity.mem_total(b, S)),
                ("kit-conflict", lambda b, S: identity.mem_kit(b))],
        "storage": [("capacity-conflict", lambda b, S: identity.capacity(b, S))],
        "monitor": [("size-conflict", lambda b, S: identity.inches(b, S)),
                    ("refresh-conflict", lambda b, S: identity.refresh(b, S))],
        "psu": [("wattage-conflict", lambda b, S: identity.wattage(b, S))],
        "laptop": [("cpu-conflict", lambda b, S: identity.cpu_model(b)),
                   ("ram-conflict", lambda b, S: identity.laptop_config(b)[0]),
                   ("ssd-conflict", lambda b, S: identity.laptop_config(b)[1])],
    }
    checks["desktop"] = checks["laptop"]
    for label, fn in checks.get(cat, []):
        if nvals(fn) > 1:
            reasons.append(label)
    if cat == "motherboard":
        signatures = [
            identity.motherboard_signature(
                listings[i]["raw_name"], listings[i].get("raw_specs") or {}
            )
            for i in idxs
        ]
        for pos, label in enumerate(
            ("ddr-conflict", "wifi-conflict", "revision-conflict", "line-conflict")
        ):
            # Missing is a value here: known and unknown are not proof of equivalence.
            if len({sig[pos] for sig in signatures}) > 1:
                reasons.append(label)
    if len(_distinct_models(idxs, listings)) > 1:
        reasons.append("multi-model-code")
    if not sku_linked and _name_conflict(idxs, listings):
        reasons.append("name-conflict")
    return (not reasons), reasons


def build_groups(listings: list):
    """Returns (accepted, quarantined, sku_conflicts, keys, conflicted, members_sku).
       accepted   : [(method, [idx...])]   validated, safe to apply
       quarantined: [(reasons, [idx...])]  cross-shop but failed validation (fail closed)
       conflicted : set of idx with title<->spec disagreement (excluded up front)"""
    n = len(listings)
    conflicted, keys = set(), []
    for i, l in enumerate(listings):
        if identity.title_spec_conflict(l["category_slug"], l["raw_name"], l.get("raw_specs") or {}):
            conflicted.add(i)
            keys.append(frozenset())          # excluded from auto-merge
        else:
            keys.append(frozenset(listing_keys(l)))

    dsu = DSU(n)
    sku_groups, sku_conflicts = sku_pass(listings)
    members_sku = set()
    for _s, idxs in sku_groups:
        idxs = [i for i in idxs if i not in conflicted]
        if len({listings[i]["shop_id"] for i in idxs}) < 2:
            continue
        for j in idxs[1:]:
            dsu.union(idxs[0], j)
        members_sku.update(idxs)

    key_index = defaultdict(list)
    for i, ks in enumerate(keys):
        for k in ks:
            key_index[k].append(i)
    for _k, idxs in key_index.items():
        if len({listings[i]["shop_id"] for i in idxs}) >= 2:
            for j in idxs[1:]:
                dsu.union(idxs[0], j)

    comps = defaultdict(list)
    for i in range(n):
        comps[dsu.find(i)].append(i)

    accepted, quarantined = [], []
    for idxs in comps.values():
        if len({listings[i]["shop_id"] for i in idxs}) < 2:
            continue
        if len(idxs) > MAX_GROUP:
            quarantined.append((["oversized"], sorted(idxs)))
            continue
        sku_linked = any(i in members_sku for i in idxs)
        ok, reasons = validate_group(idxs, listings, sku_linked=sku_linked)
        if ok:
            method = "sku" if sku_linked else "identity_rule"
            accepted.append((method, sorted(idxs)))
        else:
            quarantined.append((reasons, sorted(idxs)))
    return accepted, quarantined, sku_conflicts, keys, conflicted, members_sku


def link_evidence(i, idxs, keys, members_sku, listings):
    """The EXACT key(s) that connect listing i to the rest of its group (per-listing
    provenance, not one representative group key)."""
    others = set().union(*[keys[j] for j in idxs if j != i]) if len(idxs) > 1 else set()
    shared = sorted(set(keys[i]) & others)
    if not shared and i in members_sku:
        shared = ["sku:" + norm_sku(listings[i].get("sku"))]
    return shared


# ──────────────────────────── shadow report (read-only) ────────────────────────


def shadow_report(listings, accepted, quarantined, sku_conflicts, conflicted, n_products):
    n = len(listings)
    cur = sum(1 for l in listings if l.get("product_id"))
    proj = sum(len(idxs) for _m, idxs in accepted)
    q_listings = sum(len(idxs) for _r, idxs in quarantined)
    by_method = Counter(m for m, _ in accepted)
    print(f"in-scope listings           : {n}")
    print(f"current matched (existing)  : {cur}  ({100*cur//max(n,1)}%)")
    print(f"PROJECTED accepted (rebuild): {proj}  ({100*proj//max(n,1)}%)   [delta {proj-cur:+d}]")
    print(f"accepted products           : {len(accepted)}  (by method: {dict(by_method)})")
    print(f"QUARANTINED groups (fail closed, NOT written): {len(quarantined)}  ({q_listings} listings)")
    print(f"title<->spec conflicted listings (excluded) : {len(conflicted)}")
    print(f"SKU conflicts (same SKU diff brand/cat)     : {len(sku_conflicts)}")

    cat_g, cat_l = Counter(), Counter()
    for _m, idxs in accepted:
        c = listings[idxs[0]]["category_slug"]
        cat_g[c] += 1
        cat_l[c] += len(idxs)
    print("\nprojected coverage by category (accepted products / listings):")
    for c in sorted(cat_g, key=lambda c: -cat_l[c]):
        print(f"  {c:<14} {cat_g[c]:>4} / {cat_l[c]:>4}")

    qreasons = Counter(r for reasons, _ in quarantined for r in reasons)
    print("\nquarantine reasons (group count per reason):")
    for r, c in qreasons.most_common():
        print(f"  {r:<22} {c}")

    print("\norphan-product accounting (products are NEVER deleted):")
    print(f"  existing products           : {n_products}")
    print(f"  orphaned after activation   : {n_products}  (kept; all listings repoint to fresh)")
    print(f"  fresh products written      : {len(accepted)}")


def quality_check(listings, accepted):
    cb = cc = mm = mv = 0
    for _m, idxs in accepted:
        cat = listings[idxs[0]]["category_slug"]
        brands = {brand_of(listings[i]) for i in idxs} - {None}
        chips = ({identity.gpu_chip(identity._clean(listings[i]["raw_name"]),
                                    identity._spec_lookup(listings[i].get("raw_specs") or {}))
                  for i in idxs} if cat == "gpu" else set()) - {None}
        if len(brands) > 1:
            cb += 1
        if len(chips) > 1:
            cc += 1
        if len(_distinct_models(idxs, listings)) > 1:
            mm += 1
        if cat == "motherboard":
            signatures = {
                identity.motherboard_signature(
                    listings[i]["raw_name"], listings[i].get("raw_specs") or {}
                )
                for i in idxs
            }
            if len(signatures) > 1:
                mv += 1
    return cb, cc, mm, mv


# ────────────────────────────── DB writers (apply) ─────────────────────────────


def _has_table(sb, table):
    try:
        sb.table(table).select("id").limit(1).execute()
        return True
    except Exception:
        return False


def export_mapping(listings, out_dir="backups") -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.abspath(os.path.join(out_dir, f"mapping_{ts}.csv"))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["listing_id", "product_id", "shop_id", "category_slug", "raw_name"])
        for l in listings:
            w.writerow([l["id"], l.get("product_id") or "", l["shop_id"],
                        l.get("category_slug") or "", (l.get("raw_name") or "")[:200]])
    return path


def write_quarantine_report(listings, quarantined, out_dir="reports") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(out_dir, "quarantined_groups.csv"))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "category", "reasons", "listing_id", "shop_id", "raw_name"])
        for gi, (reasons, idxs) in enumerate(quarantined):
            for i in idxs:
                w.writerow([gi, listings[i]["category_slug"], ";".join(reasons),
                            listings[i]["id"], listings[i]["shop_id"],
                            (listings[i]["raw_name"] or "")[:200]])
    return path


def quarantine_aliases(sb) -> int:
    rows, page, page_size = [], 0, 1000
    while True:
        chunk = (sb.table("product_aliases").select("id, source")
                 .range(page * page_size, page * page_size + page_size - 1)
                 .execute().data or [])
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1
    to_q = [r["id"] for r in rows if not str(r.get("source", "")).startswith("quarantined")]
    for k in range(0, len(to_q), 200):
        sb.table("product_aliases").update({"source": "quarantined"}).in_(
            "id", to_q[k:k + 200]).execute()
    return len(to_q)


def supersede_pending_queue(sb) -> int:
    """Retire candidates generated against the previous product mapping."""
    ids, page, page_size = [], 0, 1000
    while True:
        chunk = (sb.table("match_queue").select("id").eq("status", "pending")
                 .range(page * page_size, page * page_size + page_size - 1)
                 .execute().data or [])
        ids.extend(r["id"] for r in chunk)
        if len(chunk) < page_size:
            break
        page += 1
    now = datetime.now(timezone.utc).isoformat()
    for k in range(0, len(ids), 200):
        sb.table("match_queue").update(
            {"status": "superseded", "reviewed_at": now}
        ).in_("id", ids[k:k + 200]).execute()
    return len(ids)


def stage_rebuild(sb, listings, accepted, keys, members_sku, cats, run_id) -> int:
    """Create fresh products and STAGE one decision per accepted listing. Does NOT touch
    listings.product_id — current mappings stay live until activate_rebuild() runs."""
    staged = 0
    for method, idxs in accepted:
        cat_slug = Counter(listings[i]["category_slug"] for i in idxs).most_common(1)[0][0]
        name = max((listings[i]["raw_name"] or "" for i in idxs), key=len)
        name = re.sub(r"\s*\(tax included\)\s*", "", name, flags=re.I).strip()
        pid = sb.table("products").insert(
            {"category_id": cats.get(cat_slug), "name": name[:300]}).execute().data[0]["id"]
        rows = []
        for i in idxs:
            link = link_evidence(i, idxs, keys, members_sku, listings)
            ev = identity.describe(listings[i].get("category_slug"), listings[i].get("raw_name"),
                                   listings[i].get("raw_specs") or {}, listings[i].get("sku"))
            ev["link_keys"] = link
            rows.append({
                "listing_id": listings[i]["id"], "product_id": pid,
                "method": method, "source": "auto", "status": "staged",
                "identity_key": link[0] if link else None,
                "evidence": ev, "confidence": 1.0,
                "algo_version": ALGO_VERSION, "rebuild_run_id": run_id,
            })
        for k in range(0, len(rows), 200):
            sb.table(DECISIONS_TABLE).insert(rows[k:k + 200]).execute()
        staged += len(idxs)
    return staged


def validate_staging(sb, run_id, expected_listing_ids, expected_products) -> None:
    """Validate every staged row before activation, paging past PostgREST's 1,000-row cap."""
    rows, page, page_size = [], 0, 1000
    while True:
        chunk = (sb.table(DECISIONS_TABLE).select("listing_id, product_id")
                 .eq("rebuild_run_id", run_id).eq("status", "staged")
                 .range(page * page_size, page * page_size + page_size - 1)
                 .execute().data or [])
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1

    expected_listing_ids = set(expected_listing_ids)
    actual_listing_ids = [r["listing_id"] for r in rows]
    if len(actual_listing_ids) != len(expected_listing_ids):
        raise SystemExit(
            f"staging mismatch: staged {len(actual_listing_ids)} != "
            f"expected {len(expected_listing_ids)} — NOT activating"
        )
    if len(set(actual_listing_ids)) != len(actual_listing_ids):
        raise SystemExit("staging has a listing with >1 staged decision — NOT activating")
    if set(actual_listing_ids) != expected_listing_ids:
        raise SystemExit("staging listing set differs from the shadow rebuild — NOT activating")
    if len({r["product_id"] for r in rows}) != expected_products:
        raise SystemExit(
            f"staging product count differs from expected {expected_products} — NOT activating"
        )


# ───────────────────────────────────── run ─────────────────────────────────────


def run(apply: bool, reset: bool):
    sb = get_client()
    cats = {c["slug"]: c["id"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)
    n_products = (sb.table("products").select("id", count="exact").limit(1).execute().count) or 0

    accepted, quarantined, sku_conflicts, keys, conflicted, members_sku = build_groups(listings)

    print("=" * 74)
    print(f"SHADOW REBUILD  (algo {ALGO_VERSION})")
    print("=" * 74)
    shadow_report(listings, accepted, quarantined, sku_conflicts, conflicted, n_products)
    cb, cc, mm, mv = quality_check(listings, accepted)
    print(f"\nACCEPTED quality: cross-brand={cb} (must be 0) · cross-chip={cc} (must be 0) "
          f"· multi-model={mm} (must be 0) · motherboard-variant={mv} (must be 0)")

    # representative accepted groups (one per category, up to 20)
    print("\n────────── 20 representative ACCEPTED groups ──────────")
    by_cat = defaultdict(list)
    for m, idxs in accepted:
        by_cat[listings[idxs[0]]["category_slug"]].append((m, idxs))
    shown = 0
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        for m, idxs in by_cat[cat][:1]:
            pr = [listings[i]["price_usd"] for i in idxs if listings[i]["price_usd"] is not None]
            sp = f"  spread ${max(pr)-min(pr):.0f}" if len(pr) >= 2 else ""
            ik = link_evidence(idxs[0], idxs, keys, members_sku, listings)
            print(f"\n[{cat}] {m}{sp}  key={ik[0] if ik else '-'}")
            for i in idxs:
                p = f"${listings[i]['price_usd']}" if listings[i]["price_usd"] is not None else "—"
                print(f"    [{shops.get(listings[i]['shop_id'],'?')[:4]}] {p:>8}  {(listings[i]['raw_name'] or '')[:64]}")
            shown += 1
        if shown >= 20:
            break

    qpath = write_quarantine_report(listings, quarantined)
    mpath = export_mapping(listings)
    print(f"\nquarantined groups report: {qpath}")
    print(f"current mapping backup    : {mpath}")

    if not (reset and apply):
        if apply and not reset:
            print("\nREFUSING TO WRITE: writes require BOTH --reset --apply.")
        print("\nDRY RUN — no DB writes.")
        return

    # ---- APPLY: staged rebuild + atomic activation ----
    if not _has_table(sb, DECISIONS_TABLE):
        print(f"\nABORT: {DECISIONS_TABLE} missing — run migration 003 first.")
        sys.exit(2)
    run_id = str(uuid.uuid4())
    print("\n" + "=" * 74 + f"\nAPPLYING (staged rebuild {run_id})\n" + "=" * 74)
    print(f"  aliases quarantined : {quarantine_aliases(sb)}")
    expected_listing_ids = {
        listings[i]["id"] for _method, idxs in accepted for i in idxs
    }
    staged = stage_rebuild(sb, listings, accepted, keys, members_sku, cats, run_id)
    print(f"  staged decisions    : {staged} (listings.product_id still LIVE)")
    validate_staging(sb, run_id, expected_listing_ids, len(accepted))
    print("  staging validated   : OK")
    try:
        sb.rpc("activate_rebuild", {"p_run_id": run_id}).execute()
    except Exception as e:
        print(f"  ACTIVATION FAILED (atomic; production unchanged): {e}")
        print("  staged rows remain inert. Investigate, then retry or restore_mapping.py.")
        sys.exit(3)
    print(f"  activated atomically: rebuild {run_id} is now live.")
    print(f"  stale queue retired  : {supersede_pending_queue(sb)} pending candidates")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(apply=args.apply, reset=args.reset)
