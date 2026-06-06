"""Ayoub Computers scraper — BigCommerce (Stencil) via the Storefront GraphQL API.

Platform discovery (DevTools / endpoint probing):
- NOT WooCommerce (/wp-json 404) and NOT Shopify (/products.json 404).
- BigCommerce: homepage has 600+ `cdn11.bigcommerce.com` refs, `stencil` markers,
  `SF-CSRF-TOKEN` + `fornax_anonymousId` cookies, store hash `s-sp9oc95xrw`,
  and `/api/storefront/cart`.

Data source — BigCommerce **Storefront GraphQL** (`POST /graphql`):
- The homepage embeds a short-lived storefront JWT (a `Bearer` token, ~2-day TTL,
  CORS-locked to https://ayoubcomputers.com). We scrape a FRESH token each run and
  send it with an `Origin` header, so expiry is a non-issue.
- `site.category(entityId:).products` returns a category's products INCLUDING all
  descendant subcategories, paginated 50 at a time. We query one clean node per
  target slug and dedup by product id.

Why an allowlist (not a denylist): ayoubcomputers.com is a general marketplace
(~38k products: beauty, toys, kitchen, pets, food …). Only a small tech slice is in
scope, so we map specific in-scope BigCommerce category ids → our slugs and ignore
everything else. `scope.py`'s title gate still runs as the final filter.

Field semantics (verified against live data):
- price: `prices.price.value` (USD). `prices == null` → "Request Price" (price_raw=None).
- in_stock: `availabilityV2.status == "Available"`. (`inventory.isInStock` is unreliable
  here — it stays True on some Unavailable items — so we don't use it.)
- raw_specs: `customFields` (RESOLUTION, SIZE, REFRESH RATE, CONNECTIVITY, …) + Brand.

    python -m scraper.runner ayoub            # dry run
    python -m scraper.runner ayoub --save     # upsert to Supabase
"""
import html
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from scraper.scope import apply_scope

SHOP_URL = "https://ayoubcomputers.com"
GRAPHQL = f"{SHOP_URL}/graphql"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
PER_PAGE = 50  # BigCommerce Storefront GraphQL hard max for products(first:)

SHOP_META = {
    "slug": "ayoub",
    "name": "Ayoub Computers",
    "url": SHOP_URL,
    "platform": "bigcommerce",
    "scraper_module": "scraper.shops.ayoub",
}

# In-scope BigCommerce category id → our category slug.
# Each category's products() includes descendants, so we list the cleanest node per
# slug. Order = dedup priority (first category to claim a product wins); since almost
# all overlaps resolve to the same slug, order rarely matters. Counts (Jun 2026) in
# comments are the live productCount for sanity.
IN_SCOPE: list[tuple[int, str]] = [
    # --- PC components (under "Computer Components") ---
    (135,  "cpu"),          # CPU (29)
    (140,  "gpu"),          # Video Graphics Cards (21)
    (137,  "ram"),          # RAM (82)
    (289,  "motherboard"),  # MOTHERBOARD (34)
    (126,  "psu"),          # POWER SUPPLY (96)
    (125,  "case"),         # COMPUTER CASE (130)
    (177,  "cooling"),      # FANS & COOLING (357)
    (104,  "storage"),      # Internal Storage (46)
    (2491, "storage"),      # External Storage (128)
    (300,  "storage"),      # OPTICAL DRIVE (11)
    (619,  "storage"),      # ENCLOSURE — drive enclosures (27)
    # --- Compute devices ---
    (583,  "laptop"),       # Laptops (whole subtree: gaming, macbooks, 2-in-1 …) (153)
    (854,  "laptop"),       # Apple > MAC Laptops (54)
    (355,  "desktop"),      # Desktops (AIO, business, mini PCs, NAS, servers) (62)
    (855,  "desktop"),      # Apple > MAC Desktop (1)
    (1232, "desktop"),      # Apple > iMAC (1)
    (1233, "desktop"),      # Apple > MAC Mini (3)
    (2821, "tablet"),       # Tablets (3)
    (858,  "tablet"),       # Apple > iPads (4)
    # --- Display & input peripherals ---
    (138,  "monitor"),      # Monitors (140)
    (112,  "keyboard"),     # KEYBOARD (gaming + office) (170)
    (868,  "keyboard"),     # Apple Keyboard (9)
    (592,  "keyboard"),     # MOUSE & KEYBOARD COMBO (56)
    (512,  "keyboard"),     # Keyboard (phone-acc bucket) (11)
    (1432, "keyboard"),     # Number Pad (1)
    (114,  "mouse"),        # MOUSE (gaming + office) (367)
    (863,  "mouse"),        # Apple Mouse (3)
    (118,  "mouse"),        # MOUSE PAD — project treats mouse-mats as 'mouse' (94)
    (117,  "joystick"),     # CONTROLLER — gamepads/controllers (17)
    (594,  "drawing-pad"),  # GRAPHIC TABLET (20)
    (2571, "gaming-chair"), # Gaming Chairs (58)
    # --- Audio peripherals (clean children of the broad "Audio & Sound" bucket) ---
    (147,  "headset"),      # Headphones & Headsets (377)
    (1357, "headset"),      # Earphones & Earbuds (330)
    (1368, "headset"),      # Gaming & Accessories — gaming headsets (88)
    (425,  "headset"),      # Headphones & Earphones (phone-acc bucket) (96)
    (860,  "headset"),      # Apple > Airpods (8)
    (1670, "headset"),      # Apple > In-Ear Headphones (2)
    (115,  "speaker"),      # Speakers (587)
    (946,  "speaker"),      # Apple > HomePod (3)
    (1703, "speaker"),      # Apple > Smart Speaker (2)
    (1402, "microphone"),   # Microphones (leaf — excludes mic accessories) (126)
    # --- Networking: active gear only (passive cabling/racks/tools excluded) ---
    (132,  "networking"),   # Router (123)
    (133,  "networking"),   # Switch (143)
    (837,  "networking"),   # Mesh WIFI (41)
    (839,  "networking"),   # NETWORK ADAPTERS (66)
    (308,  "networking"),   # Network cards (2)
    (262,  "networking"),   # Network Expansion (82)
    (516,  "networking"),   # Media Converter (9)
    (727,  "networking"),   # Antenna (1)
    # --- Power / camera / projector ---
    (1355, "ups"),          # UPS (leaf — excludes UPS accessories) (32)
    (714,  "camera"),       # Cameras (digital, instant, action, DSLR, mirrorless) (193)
    (364,  "camera"),       # Webcams (41)
    (420,  "projector"),    # Projector (31)
]


@dataclass
class Listing:
    raw_name: str               # == raw_title
    sku: Optional[str]
    price_raw: Optional[float]  # None = "Request Price"
    currency: str
    in_stock: bool
    product_url: str
    image_url: Optional[str]
    category_slug: Optional[str]
    raw_specs: dict = field(default_factory=dict)


_PRODUCTS_Q = """
query($id: Int!, $after: String) {
  site {
    category(entityId: $id) {
      products(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            entityId
            sku
            name
            path
            brand { name }
            availabilityV2 { status }
            prices { price { value currencyCode } }
            defaultImage { url(width: 600) }
            customFields(first: 25) { edges { node { name value } } }
          }
        }
      }
    }
  }
}
"""


def _fresh_token(client: httpx.Client) -> str:
    """Scrape the short-lived storefront GraphQL JWT from the homepage."""
    import re
    home = _retry(lambda: client.get(SHOP_URL)).text
    m = re.search(r"(eyJ0eXAiOiJKV1Q[A-Za-z0-9_.\-]+)", home)
    if not m:
        raise RuntimeError("could not find storefront GraphQL token on homepage")
    return m.group(1)


def _retry(fn, tries: int = 5, delay: float = 2.0):
    """This machine's network is intermittently blocked; retry transient failures."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            time.sleep(delay)
    raise last


def _specs(node: dict) -> dict:
    specs: dict[str, str] = {}
    for e in (node.get("customFields") or {}).get("edges", []):
        n = e["node"]
        name, val = (n.get("name") or "").strip(), (n.get("value") or "").strip()
        if not name or not val:
            continue
        specs[name] = f"{specs[name]} | {val}" if name in specs else val  # keep dup values
    brand = (node.get("brand") or {}).get("name")
    if brand and "Brand" not in specs:
        specs["Brand"] = brand
    return specs


def _to_listing(node: dict) -> Listing:
    name = html.unescape(node.get("name") or "")
    prices = node.get("prices")
    price_raw = None
    currency = "USD"
    if prices and prices.get("price"):
        val = prices["price"].get("value")
        currency = prices["price"].get("currencyCode") or "USD"
        if val and val > 0:
            price_raw = float(val)
    img = node.get("defaultImage") or {}
    return Listing(
        raw_name=name,
        sku=(node.get("sku") or "").strip() or None,
        price_raw=price_raw,
        currency=currency,
        in_stock=(node.get("availabilityV2") or {}).get("status") == "Available",
        product_url=SHOP_URL + (node.get("path") or ""),
        image_url=img.get("url") or None,
        category_slug=None,  # set by caller (per the category being scraped)
        raw_specs=_specs(node),
    )


def _fetch_category(client: httpx.Client, token: str, cat_id: int) -> list[dict]:
    nodes, after = [], None
    while True:
        def _call():
            r = client.post(
                GRAPHQL,
                headers={"Authorization": f"Bearer {token}", "Origin": SHOP_URL},
                json={"query": _PRODUCTS_Q, "variables": {"id": cat_id, "after": after}},
            )
            r.raise_for_status()
            return r.json()

        data = _retry(_call)
        if "errors" in data:
            raise RuntimeError(f"GraphQL error on category {cat_id}: {data['errors']}")
        conn = data["data"]["site"]["category"]
        if not conn:  # category id no longer exists
            break
        products = conn["products"]
        nodes.extend(e["node"] for e in products["edges"])
        page = products["pageInfo"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]
    return nodes


def fetch_all(verbose: bool = True) -> list[Listing]:
    listings: dict[int, Listing] = {}  # entityId → Listing (first in-scope cat wins)

    with httpx.Client(headers=HEADERS, timeout=40) as client:
        token = _fresh_token(client)
        if verbose:
            print(f"  got storefront token ({len(token)} chars); "
                  f"querying {len(IN_SCOPE)} in-scope categories\n")

        for cat_id, slug in IN_SCOPE:
            nodes = _fetch_category(client, token, cat_id)
            new = 0
            for node in nodes:
                eid = node["entityId"]
                if eid in listings:
                    continue  # already claimed by an earlier in-scope category
                lst = _to_listing(node)
                lst.category_slug = apply_scope(slug, lst.raw_name)  # final title gate
                listings[eid] = lst
                new += 1
            if verbose:
                print(f"  cat {cat_id:>5} -> {slug:<12} {len(nodes):>4} products "
                      f"({new} new, {len(listings)} unique so far)")

    return list(listings.values())
