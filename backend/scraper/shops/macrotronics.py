import html
import httpx
from dataclasses import dataclass
from typing import Callable, Optional

from scraper.scope import apply_scope

API_BASE = "https://www.macrotronics.net/products.json"
SHOP_URL = "https://www.macrotronics.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
PER_PAGE = 250  # Shopify products.json hard max

SHOP_META = {
    "slug": "macrotronics",
    "name": "Macrotronics",
    "url": SHOP_URL,
    "platform": "shopify",
    "scraper_module": "scraper.shops.macrotronics",
}

# Shopify `product_type` → our category slug (None = in catalogue but out of scope).
# Unlisted types fall through to None (see _category_for).
CATEGORY_MAP: dict[str, Optional[str]] = {
    # --- In scope: PC parts ---
    "Processors":                      "cpu",
    "Graphic Cards":                   "gpu",
    "RAM":                             "ram",
    "Desktop RAM":                     "ram",
    "Motherboards":                    "motherboard",
    "SSD":                             "storage",
    "HDD":                             "storage",
    "Flash Drives and Memory Cards":   "storage",
    "Power Supplies":                  "psu",
    "Computer Cases":                  "case",
    "CPU Coolers":                     "cooling",
    "Thermal Paste and Pads":          "cooling",
    # --- In scope: peripherals ---
    "Computer Monitors":               "monitor",
    "Gaming Monitors":                 "monitor",
    "Gaming Mice":                     "mouse",
    "Gaming Keyboards":                "keyboard",
    "Earphones and Headphones":        "headset",
    "Speakers":                        "speaker",
    "Gaming Chairs":                   "gaming-chair",
    # --- In scope: compute devices ---
    "Laptops":                         "laptop",
    "OD Laptops":                      "laptop",
    "Desktops and Mini PCs":           "desktop",
    "iPads & Tablets":                 "tablet",
    # --- In scope: networking / power / AV ---
    "Networking and Tools":            "networking",
    "Routers, Repeaters and APs":      "networking",
    "Network Adapters":                "networking",
    "Network Switches and Adapters":   "networking",
    "Online and Backup UPS":           "ups",
    "Surveillance and Security":       "camera",
    "Projectors, Screens and More":    "projector",
    # --- Out of scope: print / consumables / POS ---
    "Original Inks and Ribbons":       None,
    "Original Toners and Drums":       None,
    "Compatible Toners and Drums":     None,
    "Printers, Scanners and Faxes":    None,
    "Paper and Media Supplies":        None,
    "POS and POS Equipment":           None,
    # --- Out of scope: cables / accessories / parts ---
    "Computer and Various Cables":     None,
    "Adapters and Converters":         None,
    "Laptop Chargers and Accessories": None,
    "Laptop Bags and Cases":           None,
    "Laptop Parts":                    None,
    "Apple Parts":                     None,
    "Apple Parts and Accessories":     None,
    "Tablet & Phone Accessories":      None,
    "Batteries":                       None,
    "Computer Case Accessories":       None,
    "Case Accessories":                None,
    "Monitor & TV Accessories":        None,
    # --- Out of scope: misc / non-catalogue ---
    "Consumer Electronics":            None,  # grab-bag, mixed — revisit if worth splitting
    "More PC Components":              None,  # grab-bag, mixed — revisit
    "Educational Electronics":         None,
    "Console, VR and Accessories":     None,  # no console category in V1
    "Gaming Desks":                    None,  # no desk category
    "Legacy Computer Parts":           None,
    "Smart Appliances":                None,  # maybe V3
    "Discontinued & Obsolete Items":   None,
    "Original Softwares and Antivirus": None,
    "Servers, Workstations and NAS":   None,
}

# product_types that mix two of our categories — decide from the product title.
AMBIGUOUS: dict[str, Callable[[str], Optional[str]]] = {
    "Mice and Keyboards":      lambda t: "keyboard" if "keyboard" in t else "mouse",
    "Webcams and Microphones": lambda t: "microphone" if "mic" in t else "camera",
    "Gaming Pads":             lambda t: "joystick"
        if any(k in t for k in ("controller", "gamepad", "game pad", "joystick"))
        else "mouse",  # otherwise a mouse pad
    "Apple Computers":         lambda t: "laptop" if "macbook" in t else "desktop",
}


@dataclass
class Listing:
    raw_name: str
    sku: Optional[str]
    price_raw: Optional[float]  # None = no real price (not expected on this shop)
    currency: str
    in_stock: bool
    product_url: str
    image_url: Optional[str]
    category_slug: Optional[str]  # our slug, None if out of scope / unmapped


def _category_for(product_type: str, title: str) -> Optional[str]:
    pt = product_type or ""
    if pt in CATEGORY_MAP:
        slug = CATEGORY_MAP[pt]
    else:
        refiner = AMBIGUOUS.get(pt)  # unknown product_type → None
        slug = refiner(title.lower()) if refiner else None
    # Final gate: drop accessories/cabling leaking in via broad shop buckets.
    return apply_scope(slug, title)


def _parse(p: dict) -> Listing:
    variants = p.get("variants") or []

    # Shopify prices are STRINGS in major units (e.g. "96.00") — NOT cents.
    prices: list[float] = []
    for v in variants:
        try:
            val = float(v.get("price"))
        except (TypeError, ValueError):
            continue
        if val > 0:
            prices.append(val)
    price_raw = min(prices) if prices else None  # cheapest variant

    in_stock = any(v.get("available") for v in variants)
    sku = (variants[0].get("sku") if variants else None) or None

    title = html.unescape(p.get("title", ""))
    images = p.get("images") or []
    handle = p.get("handle", "")

    return Listing(
        raw_name=title,
        sku=sku,
        price_raw=price_raw,
        currency="USD",  # store currency confirmed via Shopify.currency
        in_stock=in_stock,
        product_url=f"{SHOP_URL}/products/{handle}",
        image_url=images[0]["src"] if images else None,
        category_slug=_category_for(p.get("product_type", ""), title),
    )


def fetch_all(verbose: bool = True) -> list[Listing]:
    listings: list[Listing] = []
    page = 1

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        while True:
            resp = client.get(API_BASE, params={"limit": PER_PAGE, "page": page})
            resp.raise_for_status()

            batch = resp.json().get("products", [])
            if not batch:
                break

            listings.extend(_parse(p) for p in batch)

            if verbose:
                print(f"  page {page}: {len(batch)} products  (running total: {len(listings)})")

            if len(batch) < PER_PAGE:
                break

            page += 1

    return listings
