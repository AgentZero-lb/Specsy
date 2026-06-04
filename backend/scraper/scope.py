"""Title-based out-of-scope filter.

Some shops file accessories under broad buckets that map to a real category —
e.g. Macrotronics' "Surveillance and Security" -> camera also contains CCTV coax
connectors, power bricks, fire extinguishers, safes and door locks; "Networking
and Tools" -> networking also contains electrical tape, cable ties, junction
boxes and mains plugs/sockets.

Category mapping alone can't separate these (they share the shop's product_type),
so we additionally reject by title. This is intentionally conservative: it only
catches items we're confident are out of scope, and deliberately leaves
borderline-but-legit cheap tech in (patch cords, RJ45 plugs, flash drives,
thermal paste, mouse pads, USB/WiFi adapters).

Used by the scrapers (override category_slug -> None) and by the one-off DB
cleanup, so live data and future scrapes stay in sync.
"""

from typing import Optional

# Lowercased substrings that mark a listing as out of scope regardless of the
# category bucket the shop filed it under. Keep these specific enough not to
# collide with in-scope products (e.g. "security power supply" not "power
# supply"; "cable tie" not "cable").
_OUT_OF_SCOPE_SUBSTRINGS: tuple[str, ...] = (
    # --- CCTV / coax cabling accessories ---
    "rg6", "rg59", "rg-6", "rg-59", "bnc",
    # --- electrical / hardware-store items ---
    "electrical tape", "temflex", "cable tie", "zip tie", "cable zip",
    "cable organiser", "cable organizer", "junction", "pcb cleaner",
    "scame", "courbi",                       # mains plug/socket/junction brands
    "security power supply",                 # CCTV power bricks (not PC PSUs)
    # --- fire safety ---
    "extinguisher", "fire blanket",
    # --- physical security (not cameras) ---
    "safe box", "door lock", "fingerprint",
)


def title_out_of_scope(name: str) -> bool:
    """True if the product title alone marks it as out of scope."""
    t = (name or "").lower()
    return any(s in t for s in _OUT_OF_SCOPE_SUBSTRINGS)


def apply_scope(category_slug: Optional[str], title: str) -> Optional[str]:
    """Final scope gate for a (category, title) pair. Returns the category to
    store, or None if the listing is out of scope. Shared by the scrapers and
    the one-off DB cleanup so live data and re-scrapes stay consistent.

    Note: networking cabling (patch cords, loose LAN cables, etc.) is left in on
    purpose — separating it from real gear by title is too error-prone to risk
    silently dropping live routers/switches/NICs on the 12h re-scrape."""
    if category_slug is None:
        return None
    if title_out_of_scope(title):
        return None
    return category_slug
