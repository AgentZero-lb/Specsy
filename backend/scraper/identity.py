"""Category-specific product identity (the auto-merge gate).

The old matcher treated the *chipset* as product identity for GPUs, so every
"RTX 5070" — ASUS Dual, Zotac, MSI Ventus — collapsed into one product. That is
wrong: those are distinct products with distinct prices/coolers/warranties.

This module replaces that shortcut with strict, per-category identity. The unit of
matching is `identity_keys(category, raw_name, raw_specs, sku) -> set[str]`:

  * Each returned key is an *exact identity assertion* (e.g. a manufacturer part
    number, or "gpu|v|asus|rtx5070|12|dual oc"). Two listings are the same product
    iff they share at least one key — the matcher (scraper.match) unions on shared
    keys. There is no fuzzy/threshold logic here.
  * A listing emits MULTIPLE complementary keys when warranted — a normalized
    manufacturer part-code key AND a structured spec key — because shops are
    inconsistent (one lists the code, another spells out the specs). Both are
    strict, so this raises recall without weakening precision.
  * If a *required* attribute can't be determined (from title first, raw_specs as
    fallback), NO key is emitted for that path. We never guess. A listing with no
    keys stays unmatched and is left for the human-review queue. Per project rule:
    a false merge is worse than a missed match.

Pure functions, no DB, no network — unit-testable in isolation.

raw_specs is Ayoub-only and its keys are inconsistently cased ("RESOLUTION" vs
"Resolution", "HEAT SINK" vs "HEATSINK"), so all spec lookups are case-insensitive.
"""
import re
import unicodedata

# ───────────────────────────────── normalization ─────────────────────────────────


def _clean(s: str) -> str:
    """lowercase, fold accents, non-alphanumerics -> single spaces."""
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _spec_lookup(raw_specs: dict) -> dict:
    """case-insensitive view of raw_specs ({'MEMORY SIZE': '8GB'} -> 'memory size')."""
    out = {}
    for k, v in (raw_specs or {}).items():
        if v is None:
            continue
        out[str(k).strip().lower()] = str(v)
    return out


def _first_spec(S: dict, *names: str):
    for n in names:
        if n in S and S[n].strip():
            return S[n].strip()
    return None


# ─────────────────────────────────── vocab ───────────────────────────────────────

# GPU board partners (the *maker*). Chip vendors (nvidia/amd/geforce/radeon) are NOT
# makers — they appear in nearly every GPU title. Sub-brand lines (TUF, ROG, Strix,
# Aorus, Prime, Dual, Ventus…) are NOT makers either — they are the *variant*.
_GPU_MAKERS = {
    "asus", "msi", "gigabyte", "zotac", "palit", "gainward", "pny", "sapphire",
    "powercolor", "xfx", "inno3d", "asrock", "evga", "colorful", "galax", "manli",
    "maxsun", "yeston", "gunnir",
}
# generic brand vocab for non-GPU categories
_BRANDS = {
    "asus", "msi", "gigabyte", "asrock", "zotac", "corsair", "gskill", "kingston",
    "hyperx", "crucial", "adata", "xpg", "teamgroup", "samsung", "sandisk",
    "seagate", "toshiba", "wd", "western", "logitech", "razer", "steelseries",
    "hp", "dell", "lenovo", "acer", "apple", "microsoft", "msi", "tplink", "dlink",
    "netgear", "ubiquiti", "mikrotik", "cisco", "cudy", "tenda", "mercusys",
    "jbl", "havit", "fantech", "cougar", "redragon", "a4tech", "genius", "philips",
    "lg", "benq", "aoc", "viewsonic", "dahua", "hikvision", "ezviz", "anker",
    "baseus", "thermaltake", "nzxt", "deepcool", "arctic", "seasonic",
    "coolermaster", "lianli", "thermalright", "aerocool", "zumax", "noctua",
    "bequiet", "twinmos", "ocpc", "apc", "prolink", "legrand", "vertiv", "kstar",
    "eaton", "epson", "benq", "viewsonic", "xiaomi", "huawei", "tplink",
    "biostar", "evga",
}
# Multi-word brand canonicalization, applied BEFORE tokenizing so "TP-Link" / "tp link"
# -> "tplink". Deliberately NO single-letter or ambiguous aliases ("d", "g", "cooler",
# "lian" mislabel ordinary words like "cooler" in "CPU cooler"). The HyperX->Kingston
# rebrand is NOT global — it holds only for memory, and is applied in _keys_ram.
_BRAND_PHRASES = (
    (re.compile(r"\btp[\s-]*link\b"), "tplink"),
    (re.compile(r"\bd[\s-]*link\b"), "dlink"),
    (re.compile(r"\bg[\s.\-]*skill\b"), "gskill"),
    (re.compile(r"\bcooler\s*master\b"), "coolermaster"),
    (re.compile(r"\blian[\s-]*li\b"), "lianli"),
    (re.compile(r"\bwestern\s*digital\b"), "wd"),
    (re.compile(r"\bbe\s*quiet\b"), "bequiet"),
)


def _canon_brands(blob: str) -> str:
    for pat, rep in _BRAND_PHRASES:
        blob = pat.sub(rep, blob)
    return blob

_FLUFF = {
    "tax", "included", "with", "for", "and", "the", "brand", "retail", "new",
    "graphics", "card", "video", "gpu", "series", "edition", "gaming", "gamer",
    "desktop", "pc", "computer",
}

# ─────────────────────────────────── regexes ─────────────────────────────────────

_GPU_RE = re.compile(r"\b(rtx|gtx|rx|arc|gt)\s*(\d{3,4})\s*(ti\s*super|super|ti|xtx|xt)?\b")
_CPU_INTEL_RE = re.compile(r"\b(i[3579])\s*-?\s*(\d{4,5})\s*([a-z]{0,2})\b")
_CPU_RYZEN_RE = re.compile(r"\bryzen\s*(\d)\s*(\d{3,4})\s*([a-z0-9]{0,3})\b")
_CPU_ULTRA_RE = re.compile(r"\b(?:core\s*)?ultra\s*(\d)\s*(\d{3})\s*([a-z]{0,2})\b")

_CAP_RE = re.compile(r"\b(\d+)\s*(tb|gb)\b")
_KIT_RE = re.compile(r"\b(\d)\s*[x*]\s*(\d+)\s*gb\b")
_SPEED_RE = re.compile(r"\b(\d{4,5})\s*(?:mhz|mt/?s|mts)\b|ddr\d[\s-]+(\d{4,5})\b")
_DDR_RE = re.compile(r"\bddr([345])\b")
_WATT_RE = re.compile(r"\b(\d{3,4})\s*w(?:att)?\b")
_VA_RE = re.compile(r"\b(\d{3,5})\s*va\b")
_INCH_RE = re.compile(r"\b(\d{2}(?:\.\d)?)\s*(?:inch\b|in\b|\"|”|″|')")
_HZ_RE = re.compile(r"\b(\d{2,3})\s*hz\b")
_RES_RE = re.compile(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b")
_DASH_CODE_RE = re.compile(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+")
_LONG_CODE_RE = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}\b")

# tokens that LOOK like model codes but are family/spec/standard identifiers — never
# unique products. Excluded from model-code keys (this is what merged AX6000 routers).
_CLASS_CODE_RE = re.compile(
    r"^(?:"
    r"rtx|gtx|rx|arc|gt|"                       # GPU chips
    r"ddr|gddr|lpddr|"                          # memory gen
    r"ax|ac|be|ad|av|wifi|wi|usb|bt|pcie|pci|sata|nvme|"  # bus / wifi / powerline classes
    r"lga|am|tr|fm|"                            # CPU sockets
    r"atx|sfx|itx|matx|eatx|"                   # form factors
    r"win|hdmi|dp|vga|hdr|"                     # ports / OS / HDR cert (HDR400/600/1000)
    r"80plus"                                   # PSU efficiency
    r")\d"
)
_KITCODE_RE = re.compile(r"^\d+x\d+")           # RAM kit notation 2x16(gb), 4x8 — not a code
# number+unit tokens ("14inch", "5400rpm", "120mm", "64bit") — specs, never products.
_MEASURE_RE = re.compile(
    r"^\d+(?:inch|rpm|hz|mhz|ghz|bit|watt|va|mm|nm|cm|mah|wh|ppi|fps|nits|mp|gbps|mbps|"
    r"kbps|mbs|gbs|kbs|mts|mt|port|ports|core|cores|thread|threads|key|keys|pin|pins|"
    r"gram|g|w)$"
)
# screen-size-prefixed chassis/generation codes ("16IAX10H", "15IRX10", "14IAL10"):
# identify a laptop *family*, shared across configs — over-merge, so never a product id.
_CHASSIS_RE = re.compile(r"^\d{2}[a-z]{2,5}\d{1,3}[a-z]?$")
_MOTHERBOARD_DDR_ALIAS_RE = re.compile(r"\bd([345])\b")
_MOTHERBOARD_WIFI_RE = re.compile(
    r"\bwi[\s-]*fi(?:[\s-]*[4567](?:e)?)?\b|\bwireless\b|\bwlan\b|\bax\b"
)
_MOTHERBOARD_NON_WIFI_RE = re.compile(
    r"\b(?:non|no|without)[\s-]*(?:wi[\s-]*fi|wireless)\b"
)
_MOTHERBOARD_LINE_TOKENS = {
    "ace", "aorus", "bomber", "carbon", "creator", "eagle", "edge", "elite",
    "gaming", "hero", "ice", "legend", "lightning", "mag", "max", "meg",
    "mortar", "mpg", "nova", "plus", "prime", "pro", "proart", "project",
    "riptide", "rog", "stealth", "steel", "strix", "taichi", "tomahawk",
    "tuf", "ud", "zero",
}
_RES_CANON = {
    (1920, 1080): "fhd", (2560, 1440): "qhd", (3840, 2160): "uhd",
    (3440, 1440): "uwqhd", (2560, 1080): "uwfhd", (1366, 768): "hd",
    (1280, 1024): "sxga", (1920, 1200): "wuxga", (3840, 1600): "uwqhdp",
    (5120, 1440): "ddqhd", (7680, 4320): "8k", (2880, 1620): "qhdp",
}


# ──────────────────────────────── component extractors ────────────────────────────
# Each is title-first (operates on the cleaned blob) with raw_specs as fallback.
# Returns a canonical token, or None when the attribute can't be determined.


def gpu_chip(blob: str, S: dict):
    m = _GPU_RE.search(blob)
    if m:
        fam, num, suf = m.group(1), m.group(2), (m.group(3) or "").replace(" ", "")
        return f"{fam}{num}{suf}"
    series = _first_spec(S, "gpu series", "gpu chipset", "chipset")
    if series:
        return _clean(series).replace(" ", "")
    return None


def cpu_model(blob: str):
    m = _CPU_INTEL_RE.search(blob)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = _CPU_RYZEN_RE.search(blob)
    if m:
        return f"ryzen{m.group(1)}{m.group(2)}{m.group(3)}"
    m = _CPU_ULTRA_RE.search(blob)
    if m:
        return f"ultra{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def gpu_maker(blob: str, S: dict):
    b = _first_spec(S, "brand")
    if b:
        bl = _clean(b).split()
        for t in bl:
            if t in _GPU_MAKERS:
                return t
    for t in blob.split():
        if t in _GPU_MAKERS:
            return t
    return None


def brand(blob: str, S: dict):
    b = _first_spec(S, "brand")
    cand = _canon_brands(_clean(b)).split() if b else []
    cand += _canon_brands(blob).split()
    for t in cand:
        if t in _BRANDS:
            return t
    return None


def vram(blob: str, S: dict):
    sz = _first_spec(S, "memory size", "vram", "memory")
    if sz:
        m = _CAP_RE.search(_clean(sz))
        if m:
            return int(m.group(1))
    # in a GPU title the memory size is a GB figure adjacent to the chip / gddr
    caps = [int(n) for n, u in _CAP_RE.findall(blob) if u == "gb" and int(n) <= 48]
    return caps[0] if caps else None


def mem_total(blob: str, S: dict):
    sz = _first_spec(S, "memory size", "capacity")
    if sz:
        m = _CAP_RE.search(_clean(sz))
        if m:
            return int(m.group(1))
    caps = [int(n) for n, u in _CAP_RE.findall(blob) if u == "gb"]
    return max(caps) if caps else None       # total = the largest GB figure in the name


def mem_kit(blob: str):
    m = _KIT_RE.search(blob)
    return f"{m.group(1)}x{m.group(2)}" if m else None


def mem_speed(blob: str, S: dict):
    f = _first_spec(S, "frequency", "speed")
    if f:
        m = re.search(r"(\d{4,5})", f)
        if m:
            return int(m.group(1))
    m = _SPEED_RE.search(blob)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def ddr_gen(blob: str, S: dict):
    d = _first_spec(S, "ddr classification", "ddr", "memory type")
    if d:
        m = _DDR_RE.search(_clean(d))
        if m:
            return f"ddr{m.group(1)}"
    m = _DDR_RE.search(blob)
    return f"ddr{m.group(1)}" if m else None


def motherboard_memory(blob: str, S: dict):
    """Memory generation, including board-name aliases such as D4/D5."""
    ddr = ddr_gen(blob, S)
    if ddr:
        return ddr
    m = _MOTHERBOARD_DDR_ALIAS_RE.search(blob)
    return f"ddr{m.group(1)}" if m else None


def motherboard_wireless(blob: str, S: dict):
    """Wireless capability when explicitly stated; absence remains unknown."""
    spec = _first_spec(S, "wireless", "wi-fi", "wifi", "wlan")
    text = f"{blob} {_clean(spec)}" if spec else blob
    if _MOTHERBOARD_NON_WIFI_RE.search(text):
        return "none"
    if _MOTHERBOARD_WIFI_RE.search(text):
        return "wifi"
    if spec and _clean(spec) in {"no", "none", "false", "without"}:
        return "none"
    return None


def motherboard_revision(raw_name: str):
    """Identity-bearing board revision (II/V2/R2.0/rev. 1.1), if stated."""
    text = unicodedata.normalize("NFKD", raw_name or "").lower()
    explicit = re.search(
        r"\b(?:rev(?:ision)?|ver(?:sion)?|r|v)\.?\s*(\d+(?:\.\d+)?)\b", text
    )
    if explicit:
        return explicit.group(1)
    roman = re.search(r"\b(iii|ii)\b", text)
    if roman:
        return {"ii": "2", "iii": "3"}[roman.group(1)]
    for m in re.finditer(r"\b([1-9]\d?\.\d+)\b", text):
        if float(m.group(1)) > 3.0:
            continue
        before = text[max(0, m.start() - 12):m.start()]
        after = text[m.end():m.end() + 8]
        if re.search(r"(?:pcie|pci-e|usb|bluetooth|m\.?|gen)\s*$", before):
            continue
        if re.match(r"\s*(?:g(?:bps)?|ghz|mhz|w|v)\b", after):
            continue
        return m.group(1)
    return None


def motherboard_line(raw_name: str):
    """Marketing line/edition that distinguishes boards sharing a base code."""
    text = unicodedata.normalize("NFKD", raw_name or "").lower()
    tags = set(_clean(text).split()) & _MOTHERBOARD_LINE_TOKENS
    if re.search(r"\bd\s*\+", text):
        tags.add("dplus")
    return "+".join(sorted(tags)) if tags else None


def motherboard_signature(raw_name: str, raw_specs: dict):
    """Strict configuration suffix used by key generation and group validation."""
    blob = _clean(raw_name)
    S = _spec_lookup(raw_specs)
    return (
        motherboard_memory(blob, S),
        motherboard_wireless(blob, S),
        motherboard_revision(raw_name),
        motherboard_line(raw_name),
    )


def capacity(blob: str, S: dict):
    c = _first_spec(S, "capacity")
    if c:
        m = _CAP_RE.search(_clean(c))
        if m:
            return int(m.group(1)) * (1024 if m.group(2) == "tb" else 1)
    vals = [int(n) * (1024 if u == "tb" else 1) for n, u in _CAP_RE.findall(blob)]
    return max(vals) if vals else None


def storage_interface(blob: str):
    if re.search(r"gen\s*5|pcie\s*5|5\.0|nvme.*gen\s*5", blob):
        return "nvme5"
    if re.search(r"gen\s*4|pcie\s*4|4\.0", blob):
        return "nvme4"
    if re.search(r"gen\s*3|pcie\s*3|3\.0", blob):
        return "nvme3"
    if "nvme" in blob or "m 2 nvme" in blob:
        return "nvme"
    if "sata" in blob:
        return "sata"
    if re.search(r"\bexternal\b|portable|usb", blob):
        return "ext"
    return None


def storage_form(blob: str):
    if re.search(r"\bm\s*2\b|2280|m\.2", blob):
        return "m2"
    if "2 5" in blob or '2.5' in blob:
        return "2.5"
    if "3 5" in blob or '3.5' in blob:
        return "3.5"
    if re.search(r"micro\s*sd|microsd|sdxc|sdhc", blob):
        return "microsd"
    if re.search(r"\bsd\b|sd card", blob):
        return "sd"
    if re.search(r"enclosure|external|portable", blob):
        return "ext"
    return None


def inches(blob: str, S: dict):
    sz = _first_spec(S, "size", "screen size")
    if sz:
        m = _INCH_RE.search(_clean(sz) + '"')
        if m:
            return float(m.group(1))
    m = _INCH_RE.search(blob)
    if m:
        v = float(m.group(1))
        if 10 <= v <= 65:
            return v
    return None


def resolution(blob: str, S: dict):
    r = _first_spec(S, "resolution")
    text = (_clean(r) + " " + blob) if r else blob
    m = _RES_RE.search(text.replace("×", "x"))
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        return _RES_CANON.get((w, h), f"{w}x{h}")
    for kw, lab in (("3840", "uhd"), ("2160", "uhd"), ("1440", "qhd"),
                    ("4k", "uhd"), ("uhd", "uhd"), ("qhd", "qhd"), ("2k", "qhd"),
                    ("fhd", "fhd"), ("1080", "fhd"), ("uwqhd", "uwqhd")):
        if re.search(rf"\b{kw}\b", text):
            return lab
    return None


def refresh(blob: str, S: dict):
    r = _first_spec(S, "refresh rate", "refresh")
    if r:
        m = re.search(r"(\d{2,3})", r)
        if m:
            return int(m.group(1))
    m = _HZ_RE.search(blob)
    return int(m.group(1)) if m else None


def panel(blob: str):
    if re.search(r"qd[\s-]*oled|oled", blob):
        return "oled"
    if re.search(r"\bips\b|nano\s*ips", blob):
        return "ips"
    if re.search(r"\bva\b|\bvis\b", blob):
        return "va"
    if re.search(r"\btn\b", blob):
        return "tn"
    return None


def wattage(blob: str, S: dict):
    w = _first_spec(S, "wattage", "power")
    if w:
        m = re.search(r"(\d{3,4})", w)
        if m:
            return int(m.group(1))
    m = _WATT_RE.search(blob)
    if m:
        v = int(m.group(1))
        if 150 <= v <= 2200:
            return v
    return None


def va_rating(blob: str):
    m = _VA_RE.search(blob)
    return int(m.group(1)) if m else None


def efficiency(blob: str, S: dict):
    e = _first_spec(S, "efficiency rating", "efficiency")
    text = (_clean(e) + " " + blob) if e else blob
    m = re.search(r"(titanium|platinum|gold|silver|bronze|white|standard)", text)
    return m.group(1) if m else None


def modularity(blob: str, S: dict):
    mo = _first_spec(S, "modularity")
    text = (_clean(mo) + " " + blob) if mo else blob
    if re.search(r"full[\s-]*modular|fully\s*modular", text):
        return "full"
    if re.search(r"semi[\s-]*modular", text):
        return "semi"
    if re.search(r"non[\s-]*modular|not\s*modular", text):
        return "non"
    return None


def cpu_tier(blob: str):
    """Coarse CPU tier for laptop/desktop config keys."""
    full = cpu_model(blob)
    if full:
        return full
    for pat, lab in (
        (r"core\s*ultra\s*9|ultra\s*9", "u9"), (r"core\s*ultra\s*7|ultra\s*7", "u7"),
        (r"core\s*ultra\s*5|ultra\s*5", "u5"), (r"ryzen\s*9", "r9"),
        (r"ryzen\s*7", "r7"), (r"ryzen\s*5", "r5"), (r"ryzen\s*3", "r3"),
        (r"\bi9\b|core\s*i9", "i9"), (r"\bi7\b|core\s*i7", "i7"),
        (r"\bi5\b|core\s*i5", "i5"), (r"\bi3\b|core\s*i3", "i3"),
        (r"\bm4\b", "m4"), (r"\bm3\b", "m3"), (r"\bm2\b", "m2"), (r"\bm1\b", "m1"),
        (r"core\s*9", "c9"), (r"core\s*7", "c7"), (r"core\s*5", "c5"),
    ):
        if re.search(pat, blob):
            return lab
    return None


# laptop/desktop product lines — distinguishes same-brand, same-config models
# (e.g. Lenovo Legion vs IdeaPad) so the config key can't merge across lines.
_FAMILIES = {
    "legion", "loq", "ideapad", "yoga", "thinkpad", "thinkbook", "v14", "v15", "v17",
    "victus", "omen", "pavilion", "envy", "spectre", "elitebook", "probook", "zbook",
    "omnibook", "nitro", "aspire", "predator", "swift", "spin", "travelmate",
    "zenbook", "vivobook", "rog", "tuf", "proart", "expertbook", "zephyrus", "flow",
    "inspiron", "latitude", "xps", "alienware", "vostro", "precision", "macbook",
    "imac", "surface", "galaxybook", "gram", "katana", "modern", "prestige",
    "stealth", "cyborg", "sword", "raider", "vector", "titan", "creator", "crosshair",
    "matebook", "magicbook", "aurora", "optiplex", "nuc", "trident", "aegis",
    "thinkcentre", "elitedesk", "prodesk", "veriton", "mac", "studio",
}


def laptop_family(blob: str):
    for t in blob.split():
        if t in _FAMILIES:
            return t
    return None


def laptop_config(blob: str):
    """(ram_gb, ssd_gb, gpu_chip) parsed from a laptop/desktop title. RAM and SSD are
    separated by magnitude: RAM is a small GB figure, SSD is >=256GB or any TB."""
    gb = [(int(n), u) for n, u in _CAP_RE.findall(blob)]
    ram = next((n for n, u in gb if u == "gb" and n in (4, 8, 12, 16, 24, 32, 48, 64, 96)), None)
    ssd_vals = [n * 1024 if u == "tb" else n for n, u in gb if u == "tb" or (u == "gb" and n >= 256)]
    ssd = min(ssd_vals) if ssd_vals else None
    g = _GPU_RE.search(blob)
    gpu = f"{g.group(1)}{g.group(2)}{(g.group(3) or '').replace(' ', '')}" if g else None
    return ram, ssd, gpu


_CPU_STRIP = (
    re.compile(r"\bi[3579][\s-]*\d{3,5}[a-z]{0,2}\b"),              # i7-13620H, i5 13420H
    re.compile(r"\bryzen\s*\d\s*\d{3,4}[a-z0-9]{0,3}\b"),          # Ryzen 7 8840HS
    re.compile(r"\b(?:core\s*)?ultra\s*\d\s*\d{3}[a-z]{0,2}\b"),    # Core Ultra 9 275HX
    re.compile(r"\b\d{4,5}(?:hx|hs|hk|kf|ks|h|u|p|k|f|t|x|g7)\b"),  # bare 8940HX, 13620H
)


def model_codes(raw_name: str, raw_specs: dict) -> set:
    """Manufacturer part-numbers in the *title* (not the shop sku, which differs per
    shop). Dashed/slashed codes (ZT-B50600F-10M, SKC3000D/2048G, RT-AX89X) plus long
    mixed alnum codes. Excluded: class/spec codes (AX6000, DDR5, 80PLUS, ATX),
    measurements (14inch, 5400rpm), chassis/family codes (16IAX10H), and CPU model
    numbers (i7-13620H) — those bridge distinct products that merely share an attribute."""
    name = (raw_name or "").lower()
    for rx in _CPU_STRIP:
        name = rx.sub(" ", name)
    # remove capacities and RAM/SSD labels first — shops like Ayoub join them with dashes
    # ("RAM-512GB-RTX5060"), which would otherwise mint junk codes like "ram512gb".
    name = re.sub(r"\b\d+\s*(?:gb|tb)\b", " ", name)
    name = re.sub(r"\b(?:ram|ssd|hdd|memory|storage)\b", " ", name)
    # strip socket/chipset/vendor spec words so dash-joined spec phrases
    # ("AMD-Ryzen-AM5-DDR5") don't mint junk codes that bridge unrelated boards.
    name = re.sub(r"\b(?:amd|intel|ryzen|geforce|radeon|core|ddr[2-5]x?|am[45]|lga\d*|"
                  r"pcie|wi-?fi|bluetooth|nvme|sata|atx|matx|itx|eatx)\b", " ", name)
    # Take dashed/slashed codes WHOLE (90YV0M10-MVAA00 -> 90yv0m10mvaa00); do not let
    # _LONG_CODE_RE re-extract their segments — the suffix (M0NA00) is shared across
    # different ASUS models and would falsely bridge Prime vs Dual.
    dash = _DASH_CODE_RE.findall(name)
    longs = _LONG_CODE_RE.findall(_DASH_CODE_RE.sub(" ", name))
    out = set()
    for tok in dash + longs:
        norm = re.sub(r"[^a-z0-9]", "", tok.lower())
        if len(norm) < 6:
            continue
        if sum(c.isalpha() for c in norm) < 2 or sum(c.isdigit() for c in norm) < 2:
            continue
        if _CLASS_CODE_RE.match(norm) or _MEASURE_RE.match(norm) or _CHASSIS_RE.match(norm):
            continue
        if _KITCODE_RE.match(norm) or _CAP_RE.fullmatch(norm):
            continue
        out.add(norm)
    return out


def _variant(blob: str, drop: set) -> str:
    """Distinctive descriptor tokens (e.g. GPU line: 'dual oc', 'twin edge oc'),
    after removing maker/chip/capacity/fluff. Sorted set -> stable, order-free key."""
    toks = []
    for t in blob.split():
        if t in drop or t in _FLUFF or t in _GPU_MAKERS or t in _BRANDS:
            continue
        if len(t) < 2 or t.isdigit():
            continue
        if _GPU_RE.fullmatch(t) or re.fullmatch(r"g?ddr[3-7]x?", t) or _CAP_RE.fullmatch(t):
            continue
        if re.fullmatch(r"\d+(?:mhz|mts?|x)|cl\d+", t):   # RAM speed/kit noise, not a line
            continue
        # drop part-number-like tokens (>=2 letters AND >=2 digits) — they are codes,
        # not variant words, and their shared suffixes would bridge distinct models
        if len(t) >= 6 and sum(c.isalpha() for c in t) >= 2 and sum(c.isdigit() for c in t) >= 2:
            continue
        toks.append(t)
    return " ".join(sorted(set(toks)))


# ──────────────────────────────── per-category keys ───────────────────────────────


def _keys_gpu(blob, S, name, raw_specs) -> set:
    chip = gpu_chip(blob, S)
    if not chip:
        return set()
    keys = set()
    for code in model_codes(name, raw_specs):
        keys.add(f"gpu|c|{chip}|{code}")
    maker, vr = gpu_maker(blob, S), vram(blob, S)
    # variant excludes the chip family/number tokens so wording like the chip can't leak in
    drop = set(re.findall(r"[a-z0-9]+", chip)) | {"gddr5", "gddr6", "gddr6x", "gddr7", "ddr6", "ddr7"}
    var = _variant(blob, drop)
    if maker and vr and var:
        keys.add(f"gpu|v|{maker}|{chip}|{vr}|{var}")
    return keys


def _keys_cpu(blob, S, name, raw_specs) -> set:
    chip = cpu_model(blob)
    return {f"cpu|{chip}"} if chip else set()


def _keys_ram(blob, S, name, raw_specs) -> set:
    keys = {f"ram|c|{c}" for c in model_codes(name, raw_specs)}
    br = brand(blob, S)
    if br == "hyperx":          # HyperX memory became Kingston Fury — rebrand valid for RAM only
        br = "kingston"
    ddr, tot, kit, spd = ddr_gen(blob, S), mem_total(blob, S), mem_kit(blob), mem_speed(blob, S)
    if br and ddr and tot and kit and spd:
        # line/variant (Fury vs Renegade vs Vengeance) is identity — without it the spec
        # key merges different product lines that share brand+capacity+speed.
        var = _variant(blob, set())
        keys.add(f"ram|s|{br}|{ddr}|{tot}|{kit}|{spd}|{var}")
    return keys


def _keys_storage(blob, S, name, raw_specs) -> set:
    # No coarse spec key: brand+capacity+interface+form is NOT identity — it merges
    # different models (SanDisk E61 vs E81, Kingston XS1000 vs XS2000, all "2TB external").
    # The model code IS the identity; qualify it with capacity (codes like DC600M are a
    # series spanning 480G..7680G).
    cap = capacity(blob, S)
    return {f"storage|c|{c}|{cap or '?'}" for c in model_codes(name, raw_specs)}


def _keys_monitor(blob, S, name, raw_specs) -> set:
    # The model code IS the identity. brand+size+res+refresh+panel is NOT — it merges
    # different models with the same panel (Samsung S3 flat LS27D300 vs curved LS27D362,
    # both 27" FHD 100Hz). MSI "274QPF" is a series across refresh variants, so qualify the
    # code with refresh.
    hz = refresh(blob, S)
    return {f"monitor|c|{c}|{hz or '?'}" for c in model_codes(name, raw_specs)}


def _keys_psu(blob, S, name, raw_specs) -> set:
    # Like storage: brand+wattage+efficiency+modularity merges different models (Thermalright
    # KG-750 vs TR-SG750 vs TR-TGFX-750, all 750W Gold fully-modular). The user's rule names
    # "brand+model" — so the model code is required; qualify it with wattage.
    w = wattage(blob, S)
    return {f"psu|c|{c}|{w or '?'}" for c in model_codes(name, raw_specs)}


def _keys_motherboard(blob, S, name, raw_specs) -> set:
    """Exact board code qualified by memory, wireless, revision, and product line.

    Motherboard base codes are commonly reused across materially different products:
    B760M-A DDR4 vs DDR5, WiFi vs non-WiFi, and revisions such as II/V2. Unknown
    attributes are kept as "?" rather than treated as compatible with a known value.
    """
    br = brand(blob, S)
    if not br:
        return set()
    ddr, wireless, revision, line = motherboard_signature(name, raw_specs)
    suffix = "|".join((ddr or "?", wireless or "?", revision or "?", line or "?"))
    return {
        f"motherboard|c|{br}|{code}|{suffix}"
        for code in model_codes(name, raw_specs)
    }


def _keys_compute(cat, blob, S, name, raw_specs) -> set:
    """laptop / desktop — config-aware so different RAM/SSD/GPU builds stay distinct.
    Full model SKUs (e.g. PHN16S-71-98RF) already encode the config, so the code key
    separates configs on its own; the spec key adds the config explicitly."""
    br = brand(blob, S)
    fam = laptop_family(blob)
    ram, ssd, gpu = laptop_config(blob)
    cpu = cpu_model(blob)   # EXACT cpu (i7-13620H), never a coarse i7/Ryzen tier
    # Config is identity: require EXACT cpu + ram + ssd (different SSD/CPU-gen must NOT merge).
    # MSI-style codes ("B14WGK") are a series shared across configs, so the code key carries
    # the full config too.
    keys = set()
    if cpu and ram and ssd:
        for c in model_codes(name, raw_specs):
            keys.add(f"{cat}|c|{c}|{cpu}|{ram}|{ssd}|{gpu or '-'}")
        if br and fam:   # family required so the spec key can't merge different lines
            keys.add(f"{cat}|s|{br}|{fam}|{cpu}|{ram}|{ssd}|{gpu or '-'}")
    return keys


def _keys_default(cat, blob, S, name, raw_specs) -> set:
    """brand + full model number; fall back to brand + exact normalized name.
    The name fallback is deliberately strict (whole normalized name must match) so it
    can't repeat the old token-overlap over-merges; near-matches go to the queue."""
    br = brand(blob, S)
    keys = set()
    for c in model_codes(name, raw_specs):
        keys.add(f"{cat}|c|{br or '?'}|{c}")
    if not keys and br:
        keys.add(f"{cat}|n|{br}|{blob}")
    return keys


_BUILDERS = {
    "gpu": _keys_gpu, "cpu": _keys_cpu, "ram": _keys_ram, "storage": _keys_storage,
    "monitor": _keys_monitor, "psu": _keys_psu, "motherboard": _keys_motherboard,
}


def identity_keys(category: str, raw_name: str, raw_specs: dict, sku: str = None) -> set:
    """Strict identity keys for a listing. Two listings are the same product iff they
    share >= 1 key. Empty set = identity undetermined (do not auto-merge; queue)."""
    cat = (category or "").strip().lower()
    blob = _clean(raw_name)
    S = _spec_lookup(raw_specs)
    if cat in _BUILDERS:
        return _BUILDERS[cat](blob, S, raw_name, raw_specs)
    if cat in ("laptop", "desktop"):
        return _keys_compute(cat, blob, S, raw_name, raw_specs)
    return _keys_default(cat, blob, S, raw_name, raw_specs)


def title_spec_conflict(category: str, raw_name: str, raw_specs: dict) -> list:
    """Attributes where the TITLE and raw_specs DISAGREE (both present, different values).
    A non-empty result means we cannot trust this listing's identity — the matcher
    quarantines it rather than silently choosing title or spec."""
    cat = (category or "").strip().lower()
    blob = _clean(raw_name)
    S = _spec_lookup(raw_specs)
    out = []

    def conflict(attr, tv, sv):
        if tv is not None and sv is not None and tv != sv:
            out.append(f"{attr}(title={tv}/spec={sv})")

    def spec_cap(*names, cap_to=None):
        v = _first_spec(S, *names)
        if not v:
            return None
        m = _CAP_RE.search(_clean(v))
        if not m:
            return None
        g = int(m.group(1)) * (1024 if m.group(2) == "tb" else 1)
        return g if (cap_to is None or g <= cap_to) else g

    if cat == "gpu":
        tcaps = [int(n) for n, u in _CAP_RE.findall(blob) if u == "gb" and int(n) <= 48]
        conflict("vram", tcaps[0] if tcaps else None, spec_cap("memory size", "vram", "memory"))
        m = _GPU_RE.search(blob)
        tc = f"{m.group(1)}{m.group(2)}{(m.group(3) or '').replace(' ', '')}" if m else None
        gs = _first_spec(S, "gpu series", "chipset")
        conflict("chip", tc, _clean(gs).replace(" ", "") if gs else None)
    elif cat == "ram":
        tcaps = [int(n) for n, u in _CAP_RE.findall(blob) if u == "gb"]
        conflict("total", max(tcaps) if tcaps else None, spec_cap("memory size", "capacity"))
        md = _DDR_RE.search(blob)
        sd = _first_spec(S, "ddr classification", "ddr", "memory type")
        sm = _DDR_RE.search(_clean(sd)) if sd else None
        conflict("ddr", f"ddr{md.group(1)}" if md else None, f"ddr{sm.group(1)}" if sm else None)
    elif cat == "storage":
        tcaps = [int(n) * (1024 if u == "tb" else 1) for n, u in _CAP_RE.findall(blob)]
        conflict("capacity", max(tcaps) if tcaps else None, spec_cap("capacity"))
    elif cat == "monitor":
        mi = _INCH_RE.search(blob)
        tsz = float(mi.group(1)) if mi and 10 <= float(mi.group(1)) <= 65 else None
        ssz = None
        sz = _first_spec(S, "size", "screen size")
        if sz:
            ms = _INCH_RE.search(_clean(sz) + '"')
            ssz = float(ms.group(1)) if ms else None
        conflict("size", tsz, ssz)
        mh = _HZ_RE.search(blob)
        rr = _first_spec(S, "refresh rate", "refresh")
        rm = re.search(r"(\d{2,3})", rr) if rr else None
        conflict("refresh", int(mh.group(1)) if mh else None, int(rm.group(1)) if rm else None)
    elif cat == "psu":
        mw = _WATT_RE.search(blob)
        tw = int(mw.group(1)) if mw and 150 <= int(mw.group(1)) <= 2200 else None
        pw = _first_spec(S, "wattage", "power")
        pm = re.search(r"(\d{3,4})", pw) if pw else None
        conflict("wattage", tw, int(pm.group(1)) if pm else None)
    return out


def describe(category: str, raw_name: str, raw_specs: dict, sku: str = None) -> dict:
    """Evidence dict for match_decisions / auditing — the parsed attributes + keys."""
    cat = (category or "").strip().lower()
    blob = _clean(raw_name)
    S = _spec_lookup(raw_specs)
    ev = {"category": cat, "keys": sorted(identity_keys(category, raw_name, raw_specs, sku))}
    if cat == "gpu":
        ev.update(chip=gpu_chip(blob, S), maker=gpu_maker(blob, S), vram=vram(blob, S),
                  codes=sorted(model_codes(raw_name, raw_specs)))
    elif cat == "cpu":
        ev.update(model=cpu_model(blob))
    elif cat == "ram":
        ev.update(brand=brand(blob, S), ddr=ddr_gen(blob, S), total=mem_total(blob, S),
                  kit=mem_kit(blob), speed=mem_speed(blob, S))
    elif cat == "storage":
        ev.update(brand=brand(blob, S), capacity=capacity(blob, S),
                  interface=storage_interface(blob), form=storage_form(blob))
    elif cat == "monitor":
        ev.update(brand=brand(blob, S), size=inches(blob, S), resolution=resolution(blob, S),
                  refresh=refresh(blob, S), panel=panel(blob))
    elif cat == "psu":
        ev.update(brand=brand(blob, S), watt=wattage(blob, S),
                  efficiency=efficiency(blob, S), modularity=modularity(blob, S))
    elif cat == "motherboard":
        ddr, wireless, revision, line = motherboard_signature(raw_name, raw_specs)
        ev.update(brand=brand(blob, S), ddr=ddr, wireless=wireless,
                  revision=revision, line=line,
                  codes=sorted(model_codes(raw_name, raw_specs)))
    elif cat in ("laptop", "desktop"):
        ram, ssd, gpu = laptop_config(blob)
        ev.update(brand=brand(blob, S), family=laptop_family(blob), cpu=cpu_model(blob),
                  ram=ram, ssd=ssd, gpu=gpu, codes=sorted(model_codes(raw_name, raw_specs)))
    else:
        ev.update(brand=brand(blob, S), codes=sorted(model_codes(raw_name, raw_specs)))
    return ev
