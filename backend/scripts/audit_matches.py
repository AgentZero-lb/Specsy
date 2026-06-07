"""Phase 1 — read-only audit of CURRENT product merges (diagnose, don't destroy).

For every product that has >= 2 linked listings, extract identity-relevant
attributes from each listing (title-first, raw_specs as fallback) and flag the
product as a SUSPECT MERGE when its listings *disagree* on any axis:

    brand/AIB partner · GPU/CPU chipset · capacity (VRAM/RAM/disk) · RAM kit
    config · PSU/UPS wattage · screen size · refresh rate · resolution ·
    manufacturer model code

Divergence is counted only among listings that actually *carry* an attribute
(missing data never counts as disagreement), so a flag means a positive conflict
a human can eyeball — e.g. ASUS vs Zotac, 8GB vs 16GB, 27" vs 32".

This is a DIAGNOSTIC, intentionally high-recall: it surfaces suspects for review.
The precise auto-merge gate is the Phase 2 identity rules (scraper/identity.py).
Nothing is written to the DB. Output is a CSV plus an on-screen summary.

    cd backend && python scripts/audit_matches.py
    cd backend && python scripts/audit_matches.py --out reports/match_audit.csv
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

# allow `python scripts/audit_matches.py` from backend/ (puts backend/ on path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.db import get_client  # noqa: E402

# ────────────────────────────── attribute extractors ──────────────────────────────
# Heuristic, title-first. Each returns the set of values found in one listing's
# text blob (raw_name + raw_specs values). A product "diverges" on an axis when the
# union of *distinct non-empty* per-listing values across its listings has size > 1.

# GPU board partners. Sub-brands fold into the manufacturer so ASUS-TUF vs
# ASUS-Prime is NOT counted as a brand conflict (that's a *variant* split, caught
# by model-code/price signals). Chip vendors (nvidia/amd/geforce/radeon) are
# excluded — they appear in almost every GPU title and are not the maker.
_AIB = {
    "asus": "asus", "rog": "asus", "tuf": "asus", "prime": "asus", "proart": "asus",
    "strix": "asus", "msi": "msi", "gigabyte": "gigabyte", "aorus": "gigabyte",
    "zotac": "zotac", "palit": "palit", "gainward": "gainward", "pny": "pny",
    "sapphire": "sapphire", "powercolor": "powercolor", "xfx": "xfx",
    "inno3d": "inno3d", "asrock": "asrock", "evga": "evga", "colorful": "colorful",
    "galax": "galax", "manli": "manli", "maxsun": "maxsun",
}
# Generic brand vocabulary for non-GPU categories.
_BRANDS = {
    "asus", "msi", "gigabyte", "asrock", "zotac", "palit", "gainward", "pny",
    "sapphire", "powercolor", "xfx", "inno3d", "evga", "corsair", "gskill",
    "g.skill", "kingston", "hyperx", "crucial", "adata", "xpg", "teamgroup",
    "samsung", "sandisk", "seagate", "western", "wd", "toshiba", "logitech",
    "razer", "steelseries", "hp", "dell", "lenovo", "acer", "apple", "microsoft",
    "tplink", "tp-link", "dlink", "d-link", "netgear", "ubiquiti", "mikrotik",
    "cisco", "jbl", "havit", "fantech", "cougar", "redragon", "a4tech", "genius",
    "philips", "lg", "benq", "aoc", "viewsonic", "dahua", "hikvision", "ezviz",
    "tenda", "mercusys", "anker", "baseus", "thermaltake", "nzxt", "deepcool",
    "arctic", "seasonic", "coolermaster", "lianli", "thermalright", "aerocool",
    "zumax", "noctua", "bequiet", "twinmos", "ocpc", "enter", "tesla",
}
_GPU_RE = re.compile(r"\b(rtx|gtx|rx|arc)\s*(\d{3,4})\s*(ti\s*super|super|ti|xtx|xt)?\b")
_CPU_INTEL_RE = re.compile(r"\b(i[3579])\s*-?\s*(\d{4,5})\s*([a-z]{0,2})\b")
_CPU_RYZEN_RE = re.compile(r"\bryzen\s*(\d)\s*(\d{3,4})\s*([a-z0-9]{0,3})\b")
_CPU_ULTRA_RE = re.compile(r"\b(?:core\s*)?ultra\s*(\d)\s*(\d{3})([a-z]{0,2})\b")

_CAP_RE = re.compile(r"\b(\d+)\s*(tb|gb)\b")                       # 8gb, 1tb, 512gb
_KIT_RE = re.compile(r"\b(\d)\s*[x×*]\s*(\d+)\s*gb\b")             # 2x16gb, 1x32gb
_WATT_RE = re.compile(r"\b(\d{3,4})\s*w(att)?\b")                  # 650w, 850 watt
_VA_RE = re.compile(r"\b(\d{3,5})\s*va\b")                         # 1500va (ups)
_INCH_RE = re.compile(r"\b(\d{2}(?:\.\d)?)\s*(?:inch|in|\"|”|″|')")  # 27", 31.5 inch
_HZ_RE = re.compile(r"\b(\d{2,3})\s*hz\b")                         # 144hz
_RES_RE = re.compile(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b")          # 1920x1080
_DASH_CODE_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+")      # ZT-B50600F-10M
_LONG_CODE_RE = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}\b")


def _strip(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "")


def _blob(name: str, specs: dict) -> str:
    """raw_name + spec values, lowercased — the text we mine for attributes."""
    parts = [name or ""]
    for v in (specs or {}).values():
        if v:
            parts.append(str(v))
    return _strip(" ".join(parts)).lower()


def chip(blob: str, specs: dict, cat: str):
    if cat == "gpu":
        m = _GPU_RE.search(blob)
        if m:
            return f"{m.group(1)}{m.group(2)}{(m.group(3) or '').replace(' ', '')}"
        gs = (specs or {}).get("GPU SERIES") or (specs or {}).get("GPU Series")
        if gs:
            return _strip(gs).lower().replace(" ", "")
        return None
    if cat == "cpu":
        for rx, pre in ((_CPU_INTEL_RE, ""), (_CPU_RYZEN_RE, "ryzen"), (_CPU_ULTRA_RE, "ultra")):
            m = rx.search(blob)
            if m:
                return pre + "".join(g for g in m.groups() if g).replace(" ", "")
    return None


def brand(blob: str, specs: dict, cat: str):
    b = (specs or {}).get("Brand")
    if b:
        bl = _strip(b).lower().strip()
        if cat == "gpu":
            return _AIB.get(bl, bl)
        return bl.replace(" ", "")
    toks = re.findall(r"[a-z0-9.\-]+", blob)
    table = _AIB if cat == "gpu" else None
    if table:
        for t in toks:
            if t in table:
                return table[t]
        return None
    for t in toks:
        if t in _BRANDS:
            return t.replace("-", "").replace(".", "")
    return None


def _caps(blob: str) -> frozenset:
    """capacities normalized to integer GB (tb -> *1024)."""
    out = set()
    for num, unit in _CAP_RE.findall(blob):
        out.add(int(num) * 1024 if unit == "tb" else int(num))
    return frozenset(out)


def _kit(blob: str) -> frozenset:
    return frozenset(f"{a}x{b}" for a, b in _KIT_RE.findall(blob))


def _watts(blob: str, cat: str) -> frozenset:
    out = {int(w) for w, _ in _WATT_RE.findall(blob)}
    if cat == "ups":
        out |= {int(v) for v in _VA_RE.findall(blob)}
    return frozenset(out)


def _inches(blob: str) -> frozenset:
    return frozenset(float(x) for x in _INCH_RE.findall(blob))


def _hz(blob: str) -> frozenset:
    return frozenset(int(x) for x in _HZ_RE.findall(blob))


def _res(blob: str) -> frozenset:
    return frozenset(f"{w}x{h}" for w, h in _RES_RE.findall(blob))


_CODE_SKIP = re.compile(r"^(rtx|gtx|rx|arc|ddr|gddr|lga|am[45]|pcie|usb|wifi|win)\d")


def _codes(name: str) -> frozenset:
    """Manufacturer part-numbers embedded in the *title* (not the shop sku, which
    differs per shop even for the same product). Used as a weak divergence hint."""
    out = set()
    for tok in _DASH_CODE_RE.findall(name or "") + _LONG_CODE_RE.findall(name or ""):
        norm = tok.lower().replace("-", "")
        if len(norm) < 6:
            continue
        if sum(c.isalpha() for c in norm) < 2 or sum(c.isdigit() for c in norm) < 2:
            continue
        if _CODE_SKIP.match(norm) or _CAP_RE.fullmatch(norm) or norm.endswith(("hz", "mhz", "ghz")):
            continue
        out.add(norm)
    return frozenset(out)


# axis name -> (extractor(listing-context) , human label). Each extractor returns a
# frozenset for one listing; product diverges on the axis if the distinct non-empty
# per-listing frozensets number > 1.
def extract_axes(name: str, specs: dict, cat: str) -> dict:
    blob = _blob(name, specs)
    c = chip(blob, specs, cat)
    b = brand(blob, specs, cat)
    return {
        "brand": frozenset([b]) if b else frozenset(),
        "chip": frozenset([c]) if c else frozenset(),
        "capacity": _caps(blob),
        "kit": _kit(blob),
        "wattage": _watts(blob, cat),
        "size": _inches(blob),
        "refresh": _hz(blob) if cat == "monitor" else frozenset(),
        "resolution": _res(blob) if cat == "monitor" else frozenset(),
        "code": _codes(name),
    }


AXES = ["brand", "chip", "capacity", "kit", "wattage", "size", "refresh", "resolution", "code"]


# ──────────────────────────────────── load ────────────────────────────────────
def _page_all(query_fn):
    rows, page, PAGE = [], 0, 1000
    while True:
        chunk = query_fn(page * PAGE, page * PAGE + PAGE - 1)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        page += 1
    return rows


def load(sb):
    cats = {c["id"]: c["slug"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    products = _page_all(lambda lo, hi: sb.table("products")
                         .select("id, name, category_id").range(lo, hi).execute().data)
    listings = _page_all(lambda lo, hi: sb.table("listings")
                         .select("id, shop_id, raw_name, category_slug, product_id, price_usd, raw_specs")
                         .not_.is_("product_id", "null").range(lo, hi).execute().data)
    return cats, shops, {p["id"]: p for p in products}, listings


# ──────────────────────────────────── run ─────────────────────────────────────
def run(out_path: str):
    sb = get_client()
    cats, shops, prod_by_id, listings = load(sb)

    by_prod = defaultdict(list)
    for l in listings:
        by_prod[l["product_id"]].append(l)
    multi = {pid: ls for pid, ls in by_prod.items() if len(ls) >= 2}

    rows_out, suspect_count = [], 0
    axis_hits = Counter()
    cat_suspect = Counter()
    cat_total = Counter()

    for pid, ls in multi.items():
        p = prod_by_id.get(pid)
        cat = cats.get(p["category_id"], "?") if p else "?"
        cat_total[cat] += 1

        per_axis = defaultdict(set)  # axis -> set of distinct non-empty frozensets
        for l in ls:
            ax = extract_axes(l["raw_name"], l.get("raw_specs") or {}, l["category_slug"] or cat)
            for k, v in ax.items():
                if v:
                    per_axis[k].add(v)
        differing = [a for a in AXES if len(per_axis.get(a, set())) > 1]
        suspect = bool(differing)
        if suspect:
            suspect_count += 1
            cat_suspect[cat] += 1
            for a in differing:
                axis_hits[a] += 1

        prices = [l["price_usd"] for l in ls if l["price_usd"] is not None]
        pmin = min(prices) if prices else None
        pmax = max(prices) if prices else None
        spread = round(pmax - pmin, 2) if prices else None

        def _vals(axis):  # flatten the distinct values seen for an axis, for the CSV
            seen = set()
            for fs in per_axis.get(axis, set()):
                seen |= set(fs)
            return ";".join(sorted(str(x) for x in seen))

        rows_out.append({
            "suspect": suspect,
            "severity": len(differing),
            "differing_axes": ",".join(differing),
            "category": cat,
            "product_id": pid,
            "product_name": (p["name"] if p else "")[:160],
            "num_listings": len(ls),
            "num_shops": len({l["shop_id"] for l in ls}),
            "price_min": pmin,
            "price_max": pmax,
            "price_spread": spread,
            "brands": _vals("brand"),
            "chips": _vals("chip"),
            "capacities": _vals("capacity"),
            "kits": _vals("kit"),
            "wattages": _vals("wattage"),
            "sizes": _vals("size"),
            "refresh": _vals("refresh"),
            "resolutions": _vals("resolution"),
            "codes": _vals("code"),
            "shops": ";".join(sorted({shops.get(l["shop_id"], "?") for l in ls})),
            "listing_titles": " || ".join((l["raw_name"] or "")[:90] for l in ls),
        })

    # suspects first, worst (most differing axes, then widest price spread, then most listings) on top
    rows_out.sort(key=lambda r: (
        not r["suspect"], -r["severity"], -(r["price_spread"] or 0), -r["num_listings"]))

    fields = list(rows_out[0].keys()) if rows_out else ["suspect"]
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    with open(out_abs, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    # ── summary ──
    print(f"products total                 : {len(prod_by_id)}")
    print(f"products with >= 2 listings    : {len(multi)}")
    print(f"SUSPECT merges (any conflict)  : {suspect_count} "
          f"({100 * suspect_count // max(len(multi), 1)}% of multi-listing products)")
    print(f"\nCSV written: {out_abs}\n")

    print("suspect merges by category (suspect / multi-listing):")
    for cat in sorted(cat_total, key=lambda c: -cat_suspect[c]):
        if cat_suspect[cat]:
            print(f"  {cat:<14} {cat_suspect[cat]:>4} / {cat_total[cat]}")

    print("\nconflicts by axis (how many suspect products disagree on each):")
    for a, c in axis_hits.most_common():
        print(f"  {a:<12} {c}")

    print("\n────────── SAMPLE: 20 worst suspect merges ──────────")
    for r in [r for r in rows_out if r["suspect"]][:20]:
        spread = f"  spread ${r['price_spread']}" if r["price_spread"] else ""
        print(f"\n[{r['category']}] {r['product_name']}")
        print(f"   {r['num_listings']} listings / {r['num_shops']} shops · "
              f"conflicts: {r['differing_axes']}{spread}")
        for t in r["listing_titles"].split(" || "):
            print(f"     - {t}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/match_audit.csv")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(args.out)
