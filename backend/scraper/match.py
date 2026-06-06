"""Deterministic, idempotent product matching across shops (no pgvector yet).

Pass 1 — exact SKU across shops.
Pass 2 — for still-unmatched listings: chip model (gpu/cpu) + distinctive model-code
         tokens + normalized-name keys; union listings that share a cross-shop key.

    python -m scraper.match            # dry run: report + sample groups, no writes
    python -m scraper.match --apply    # create products, set listings.product_id, write aliases

Idempotent: a group reuses the product already linked to any of its listings
(listings.product_id), so re-runs never duplicate products or aliases.
Keys are namespaced by category, so cross-category collisions can't happen.
"""
import re
import sys
import unicodedata
from collections import Counter, defaultdict

from scraper.db import get_client

MAX_GROUP = 12        # Pass-2 components larger than this look like cascade noise -> skip
MIN_NAME_TOKENS = 3   # a normalized-name key needs >= this many tokens to be a match key
KEY_MAX_FREQ = 6      # a code/name key shared by more listings than this is a family/spec
                      # code (e.g. chassis "15IRX10", Wi-Fi class "AXE5400"), not a product
                      # id — too broad to match on. Chip keys (gpu/cpu) are exempt.

_BRANDS = {
    "asus", "rog", "tuf", "msi", "gigabyte", "aorus", "asrock", "evga", "zotac",
    "palit", "gainward", "pny", "sapphire", "powercolor", "xfx", "inno3d", "nvidia",
    "geforce", "amd", "radeon", "intel", "corsair", "gskill", "kingston", "hyperx",
    "crucial", "adata", "xpg", "teamgroup", "samsung", "sandisk", "seagate",
    "logitech", "razer", "steelseries", "hp", "dell", "lenovo", "acer", "apple",
    "microsoft", "tplink", "dlink", "netgear", "ubiquiti", "mikrotik", "cisco",
    "jbl", "havit", "fantech", "cougar", "redragon", "a4tech", "genius", "philips",
    "lg", "benq", "aoc", "viewsonic", "dahua", "hikvision", "ezviz", "tenda",
    "mercusys", "anker", "baseus", "thermaltake", "nzxt", "deepcool", "arctic",
    "seasonic", "cooler", "master",
}
_FLUFF = {
    "tax", "included", "gaming", "gamer", "laptop", "notebook", "desktop", "pc",
    "computer", "monitor", "mouse", "keyboard", "headset", "headphone", "headphones",
    "graphics", "card", "processor", "edition", "retail", "brand", "series", "with",
    "the", "for", "and", "kit", "new",
}
_SPEC_TOKEN = re.compile(
    r"^\d+(\.\d+)?(gb|tb|mb|ghz|mhz|hz|w|wh|mah|mm|cm|inch|in|k|nm|ml|rpm|cl|p|fps)$"
)
_CHIP_STOP = re.compile(r"^(rtx|gtx|rx|ddr\d|win\d+|usb\d?|wifi\d?|pcie|nvme|sata|m2)$")
# screen-size-prefixed chassis/generation codes (15IAX9, 15IRX10, 16IML9, 16IAX10H):
# these identify a laptop *family*, not a specific model, so they over-merge.
_CHASSIS_RE = re.compile(r"^\d{2}[a-z]{2,5}\d{0,2}[a-z]?$")

_GPU_RE = re.compile(r"\b(rtx|gtx|rx|arc)\s*(\d{3,4})\s*(ti\s*super|super|ti|xtx|xt)?\b")
_CPU_INTEL_RE = re.compile(r"\b(i[3579])\s*-?\s*(\d{4,5})\s*([a-z]{0,2})\b")
_CPU_RYZEN_RE = re.compile(r"\bryzen\s*(\d)\s*(\d{3,4})\s*([a-z0-9]{0,3})\b")
_CPU_ULTRA_RE = re.compile(r"\b(?:core\s*)?ultra\s*(\d)\s*(\d{3})([a-z]{0,2})\b")


def _clean(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _chip_model(cleaned: str):
    m = _GPU_RE.search(cleaned)
    if m:
        return f"{m.group(1)}{m.group(2)}{(m.group(3) or '').replace(' ', '')}"
    m = _CPU_INTEL_RE.search(cleaned)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = _CPU_RYZEN_RE.search(cleaned)
    if m:
        return f"ryzen{m.group(1)}{m.group(2)}{m.group(3)}"
    m = _CPU_ULTRA_RE.search(cleaned)
    if m:
        return f"ultra{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def _is_model_code(tok: str) -> bool:
    """A distinctive model-code token: >=5 chars, >=2 letters AND >=2 digits,
    not a spec/marketing token (16gb, 144hz, ddr5, win11, rtx…)."""
    if len(tok) < 5:
        return False
    letters = sum(c.isalpha() for c in tok)
    digits = sum(c.isdigit() for c in tok)
    if letters < 2 or digits < 2:
        return False
    if _SPEC_TOKEN.match(tok) or _CHIP_STOP.match(tok) or tok in ("win10", "win11"):
        return False
    if _CHASSIS_RE.match(tok):
        return False
    return True


def _model_codes(cleaned: str, sku: str) -> set:
    codes = {t for t in cleaned.split() if _is_model_code(t)}
    sk = re.sub(r"[^a-z0-9]", "", (sku or "").lower())
    if _is_model_code(sk):
        codes.add(sk)
    return codes


def _name_key(cleaned: str) -> str:
    toks = sorted(
        {t for t in cleaned.split()
         if t not in _BRANDS and t not in _FLUFF and len(t) > 1}
    )
    return " ".join(toks)


def listing_keys(cat: str, name: str, sku: str) -> set:
    cleaned = _clean(name)
    keys = set()
    if cat in ("gpu", "cpu"):
        chip = _chip_model(cleaned)
        if chip:
            keys.add(f"{cat}|chip|{chip}")
    for code in _model_codes(cleaned, sku or ""):
        keys.add(f"{cat}|code|{code}")
    nk = _name_key(cleaned)
    if len(nk.split()) >= MIN_NAME_TOKENS:
        keys.add(f"{cat}|name|{nk}")
    return keys


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


def load_listings(sb):
    # include raw_specs when the column exists (migration 002); fall back otherwise so
    # the deterministic pass keeps working before the migration is applied.
    cols = "id, shop_id, sku, raw_name, category_slug, product_id, price_usd, raw_specs"
    try:
        sb.table("listings").select(cols).limit(1).execute()
    except Exception:
        cols = "id, shop_id, sku, raw_name, category_slug, product_id, price_usd"

    rows, page, PAGE = [], 0, 1000
    while True:
        chunk = (
            sb.table("listings")
            .select(cols)
            .not_.is_("category_slug", "null")
            .range(page * PAGE, page * PAGE + PAGE - 1)
            .execute()
            .data
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        page += 1
    for r in rows:
        r.setdefault("raw_specs", {})  # uniform shape for the embedding/Haiku passes
    return rows


def _group_category(listings, idxs, cats):
    counts = Counter(listings[i]["category_slug"] for i in idxs)
    return counts.most_common(1)[0][0]


def _ensure_product(sb, listings, idxs, cats):
    """Create or reuse the product for a group, set product_id on all its listings,
    and record aliases. Returns ('created'|'reused', product_id)."""
    existing = sorted({listings[i]["product_id"] for i in idxs if listings[i]["product_id"]})
    if existing:
        pid, state = existing[0], "reused"
    else:
        cat_slug = _group_category(listings, idxs, cats)
        cid = cats.get(cat_slug)
        name = max((listings[i]["raw_name"] or "" for i in idxs), key=len)
        name = re.sub(r"\s*\(tax included\)\s*", "", name, flags=re.I).strip()
        pid = (
            sb.table("products")
            .insert({"category_id": cid, "name": name[:300]})
            .execute()
            .data[0]["id"]
        )
        state = "created"

    ids = [listings[i]["id"] for i in idxs]
    for k in range(0, len(ids), 200):
        sb.table("listings").update({"product_id": pid}).in_("id", ids[k:k + 200]).execute()

    aliases, seen = [], set()
    for i in idxs:
        a = (listings[i]["raw_name"] or "")[:500]
        if a and a not in seen:
            seen.add(a)
            aliases.append({"product_id": pid, "alias": a, "source": "confirmed"})
    if aliases:
        sb.table("product_aliases").upsert(
            aliases, on_conflict="alias", ignore_duplicates=True
        ).execute()

    for i in idxs:
        listings[i]["product_id"] = pid
    return state, pid


def run(apply: bool):
    sb = get_client()
    cats = {c["slug"]: c["id"] for c in sb.table("categories").select("id, slug").execute().data}
    shops = {s["id"]: s["slug"] for s in sb.table("shops").select("id, slug").execute().data}
    listings = load_listings(sb)
    n = len(listings)

    # ---- Pass 1: exact SKU across shops ----
    by_sku = defaultdict(list)
    for i, l in enumerate(listings):
        s = (l["sku"] or "").strip()
        if s:
            by_sku[s].append(i)
    pass1_groups, in_pass1 = [], set()
    for idxs in by_sku.values():
        if len({listings[i]["shop_id"] for i in idxs}) >= 2:
            pass1_groups.append(idxs)
            in_pass1.update(idxs)

    # ---- Pass 2: model/chip/name keys over the rest, union-find ----
    remaining = [i for i in range(n) if i not in in_pass1]
    dsu = DSU(n)
    key_index = defaultdict(list)
    for i in remaining:
        l = listings[i]
        for k in listing_keys(l["category_slug"], l["raw_name"], l["sku"]):
            key_index[k].append(i)
    for key, idxs in key_index.items():
        # drop over-broad family/spec codes (chassis, Wi-Fi class…); keep chip keys
        if "|chip|" not in key and len(idxs) > KEY_MAX_FREQ:
            continue
        if len({listings[i]["shop_id"] for i in idxs}) >= 2:
            for j in idxs[1:]:
                dsu.union(idxs[0], j)
    comps = defaultdict(list)
    for i in remaining:
        comps[dsu.find(i)].append(i)
    pass2_groups, skipped_large = [], 0
    for idxs in comps.values():
        if len({listings[i]["shop_id"] for i in idxs}) < 2:
            continue
        if len(idxs) > MAX_GROUP:
            skipped_large += 1
            continue
        pass2_groups.append(idxs)

    groups = [("sku", g) for g in pass1_groups] + [("name", g) for g in pass2_groups]
    matched_listings = sum(len(g) for _, g in groups)

    print(f"in-scope listings : {n}")
    print(f"Pass 1 (SKU)      : {len(pass1_groups)} cross-shop groups")
    print(f"Pass 2 (name)     : {len(pass2_groups)} cross-shop groups "
          f"({skipped_large} oversized groups skipped)")
    print(f"Cross-shop products: {len(groups)}")
    print(f"Matched listings  : {matched_listings} "
          f"({100 * matched_listings // max(n, 1)}% of in-scope)\n")

    # sample groups for eyeballing quality
    print("--- sample matched groups ---")
    for kind, idxs in groups[:22]:
        cat = _group_category(listings, idxs, cats)
        print(f"[{kind}] {cat}")
        for i in idxs:
            l = listings[i]
            price = f"${l['price_usd']}" if l["price_usd"] is not None else "—"
            print(f"    {shops.get(l['shop_id'], '?')[:4]:<4} {price:>9}  {(l['raw_name'] or '')[:62]}")

    if not apply:
        print("\nDRY RUN — re-run with --apply to write products/aliases/product_id.")
        return

    created = reused = 0
    for _, idxs in groups:
        state, _ = _ensure_product(sb, listings, idxs, cats)
        if state == "created":
            created += 1
        else:
            reused += 1
    print(f"\nApplied: {created} products created, {reused} reused, "
          f"{matched_listings} listings linked.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 chokes on ″ / – in names
    run(apply="--apply" in sys.argv)
