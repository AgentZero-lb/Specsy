import html
import httpx
from dataclasses import dataclass
from typing import Optional

from scraper.scope import apply_scope

API_BASE = "https://pcandparts.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://pcandparts.com/",
}
PER_PAGE = 100

SHOP_META = {
    "slug": "pcandparts",
    "name": "PC and Parts",
    "url": "https://pcandparts.com",
    "platform": "woocommerce",
    "scraper_module": "scraper.shops.pcandparts",
}

# WooCommerce category slug → our category slug (None = out of scope, skip)
CATEGORY_MAP: dict[str, str | None] = {
    # --- In scope: PC parts ---
    "cpu":                               "cpu",
    "video-card":                        "gpu",
    "memory":                            "ram",
    "motherboard":                       "motherboard",
    "storage-hdd-hard-drives-nvme-ssd-m2": "storage",
    "power-supplies":                    "psu",
    "computer-cases":                    "case",
    "cooling":                           "cooling",
    # --- In scope: peripherals we want to show ---
    "monitor":                           "monitor",
    "mouse":                             "mouse",
    "keyboard":                          "keyboard",
    "headset":                           "headset",
    "keyboard-mouse":                    "keyboard",
    "mouse-mat":                         "mouse",
    "speaker":                           "speaker",
    "microphone":                        "microphone",
    "joysticks":                         "joystick",
    "drawing-pad":                       "drawing-pad",
    "gaming-chair":                      "gaming-chair",
    # --- In scope: compute devices ---
    "laptops":                           "laptop",
    "desktops":                          "desktop",
    "tablets":                           "tablet",
    # --- In scope: networking ---
    "router":                            "networking",
    "switch":                            "networking",
    "access-point":                      "networking",
    "network-adapter":                   "networking",
    "network-card":                      "networking",
    "extender":                          "networking",
    "antenna":                           "networking",
    # --- In scope: storage accessories ---
    "flash-memory":                      "storage",
    "enclosure":                         "storage",
    "dvd-writer":                        "storage",
    # --- In scope: power ---
    "ups":                               "ups",
    # --- In scope: camera / AV ---
    "camera":                            "camera",
    "projector":                         "projector",
    # --- Out of scope: office / consumables ---
    "accessories":                       None,
    "printer":                           None,
    "toner":                             None,
    "shredder":                          None,
    "scanner":                           None,
    "barcode-reader":                    None,
    "cards":                             None,
    "software":                          None,
    "ribbon":                            None,
    "cash-drawer":                       None,
    "print-server":                      None,
    "docking-station":                   None,
    "home-tv-monitor":                   None,
    "uncategorized":                     None,
}


@dataclass
class Listing:
    raw_name: str
    sku: Optional[str]
    price_raw: Optional[float]  # None = "Request Price"
    currency: str
    in_stock: bool
    product_url: str
    image_url: Optional[str]
    category_slug: Optional[str]  # our slug, None if unmapped


def _parse(p: dict) -> Listing:
    prices = p.get("prices", {})
    raw = prices.get("price")

    # prices are in cents as strings; "0" means Request Price
    price_raw = int(raw) / 100 if raw and int(raw) > 0 else None

    name = html.unescape(p.get("name", ""))

    wc_cats = p.get("categories", [])
    category_slug = None
    for c in wc_cats:
        slug = c.get("slug", "")
        if slug in CATEGORY_MAP:
            category_slug = CATEGORY_MAP[slug]  # may be None (out of scope)
            break
    # Final gate: drop accessories/cabling leaking in via broad shop categories.
    category_slug = apply_scope(category_slug, name)

    images = p.get("images", [])

    return Listing(
        raw_name=name,
        sku=p.get("sku") or None,
        price_raw=price_raw,
        currency=prices.get("currency_code", "USD"),
        in_stock=bool(p.get("is_in_stock", False)),
        product_url=p.get("permalink", ""),
        image_url=images[0]["src"] if images else None,
        category_slug=category_slug,
    )


def fetch_all(verbose: bool = True) -> list[Listing]:
    listings: list[Listing] = []
    page = 1

    with httpx.Client(headers=HEADERS, timeout=20) as client:
        while True:
            resp = client.get(API_BASE, params={
                "rest_route": "/wc/store/v1/products",
                "per_page": PER_PAGE,
                "page": page,
            })
            resp.raise_for_status()

            try:
                batch = resp.json()
            except ValueError as exc:
                content_type = resp.headers.get("content-type", "unknown")
                raise RuntimeError(
                    f"PC and Parts returned non-JSON content ({content_type})"
                ) from exc
            if not isinstance(batch, list):
                raise RuntimeError("PC and Parts returned an unexpected API payload")
            if not batch:
                break

            listings.extend(_parse(p) for p in batch)

            if verbose:
                print(f"  page {page}: {len(batch)} products  (running total: {len(listings)})")

            if len(batch) < PER_PAGE:
                break

            page += 1

    return listings
