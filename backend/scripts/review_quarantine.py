"""Build a read-only review workspace for reports/quarantined_groups.csv.

The default mode enriches the report with current listing/shop data using Supabase
SELECT queries, then writes a self-contained HTML file. Review choices live only in
the browser and can be exported as an inert proposal CSV. This script has no DB
write path and does not change matcher rules.

    cd backend
    python scripts/review_quarantine.py
    python scripts/review_quarantine.py --group 9
    python scripts/review_quarantine.py --offline
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import sys
import webbrowser
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import identity  # noqa: E402

REQUIRED_COLUMNS = {
    "group", "category", "reasons", "listing_id", "shop_id", "raw_name",
}
LISTING_COLUMNS = (
    "id, shop_id, sku, raw_name, price_usd, price_raw, currency, in_stock, "
    "product_url, image_url, raw_specs, last_seen_at, product_id, "
    "shops(slug, name, url)"
)


def read_report(path: str | Path) -> tuple[list[dict], str]:
    report_path = Path(path)
    raw = report_path.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()[:12]
    with report_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"report is missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    grouped: dict[int, dict] = {}
    for row in rows:
        try:
            group_id = int(row["group"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid group id: {row.get('group')!r}") from exc
        group = grouped.setdefault(group_id, {
            "group": group_id,
            "category": row["category"],
            "reasons": [r for r in row["reasons"].split(";") if r],
            "listings": [],
        })
        if group["category"] != row["category"] or group["reasons"] != [
            r for r in row["reasons"].split(";") if r
        ]:
            raise ValueError(f"group {group_id} has inconsistent category/reasons")
        group["listings"].append({
            "id": row["listing_id"],
            "shop_id": row["shop_id"],
            "raw_name": row["raw_name"],
            "report_raw_name": row["raw_name"],
        })
    return [grouped[k] for k in sorted(grouped)], fingerprint


def _fetch_live_listings(sb, listing_ids: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for start in range(0, len(listing_ids), 200):
        chunk = (
            sb.table("listings")
            .select(LISTING_COLUMNS)
            .in_("id", listing_ids[start:start + 200])
            .execute()
            .data
            or []
        )
        for row in chunk:
            rows[row["id"]] = row
    return rows


def enrich_groups(groups: list[dict], sb) -> None:
    listing_ids = [
        listing["id"] for group in groups for listing in group["listings"]
    ]
    live = _fetch_live_listings(sb, listing_ids)
    for group in groups:
        for report_listing in group["listings"]:
            row = live.get(report_listing["id"])
            if row is None:
                report_listing["missing_live"] = True
                continue
            for key, value in row.items():
                report_listing[key] = value
            report_listing["missing_live"] = False
            report_listing["report_name_changed"] = (
                report_listing["report_raw_name"] != row.get("raw_name")
            )
            report_listing["identity"] = identity.describe(
                group["category"],
                row.get("raw_name") or "",
                row.get("raw_specs") or {},
                row.get("sku"),
            )


def summarize(groups: list[dict]) -> dict:
    listings = [listing for group in groups for listing in group["listings"]]
    return {
        "groups": len(groups),
        "listings": len(listings),
        "categories": Counter(group["category"] for group in groups),
        "reasons": Counter(
            reason for group in groups for reason in group["reasons"]
        ),
        "missing_live": sum(bool(row.get("missing_live")) for row in listings),
        "linked_live": sum(bool(row.get("product_id")) for row in listings),
        "renamed_live": sum(bool(row.get("report_name_changed")) for row in listings),
    }


def _price(row: dict) -> str:
    if row.get("price_usd") is not None:
        return f"${float(row['price_usd']):,.2f}"
    if row.get("price_raw") is None:
        return "Request Price"
    return f"{row['price_raw']} {row.get('currency') or ''}".strip()


def print_summary(groups: list[dict], fingerprint: str) -> None:
    summary = summarize(groups)
    print(f"report fingerprint : {fingerprint}")
    print(f"groups / listings  : {summary['groups']} / {summary['listings']}")
    print(f"categories         : {dict(summary['categories'].most_common())}")
    print(f"reasons            : {dict(summary['reasons'].most_common())}")
    print(f"missing live rows  : {summary['missing_live']}")
    print(f"already linked     : {summary['linked_live']}")
    print(f"renamed since CSV  : {summary['renamed_live']}")


def print_group(groups: list[dict], group_id: int) -> None:
    group = next((g for g in groups if g["group"] == group_id), None)
    if group is None:
        raise ValueError(f"group {group_id} is not present in the report")
    print(f"\nGroup {group_id} | {group['category']} | {', '.join(group['reasons'])}")
    for row in group["listings"]:
        shop = row.get("shops") or {}
        if "in_stock" not in row:
            stock = "stock unknown"
        else:
            stock = "in stock" if row.get("in_stock") else "out of stock"
        print(f"  [{shop.get('slug') or row.get('shop_id')}] {_price(row)} | {stock}")
        print(f"    {row.get('raw_name')}")
        print(f"    listing={row['id']} sku={row.get('sku') or '-'}")
        if row.get("product_url"):
            print(f"    {row['product_url']}")


def _json_text(value) -> str:
    return json.dumps(value or {}, indent=2, ensure_ascii=True, sort_keys=True)


def _listing_html(row: dict) -> str:
    esc = html.escape
    shop = row.get("shops") or {}
    title = esc(row.get("raw_name") or "")
    url = esc(row.get("product_url") or "", quote=True)
    image = esc(row.get("image_url") or "", quote=True)
    title_html = (
        f'<a href="{url}" target="_blank" rel="noreferrer">{title}</a>'
        if url else title
    )
    image_html = (
        f'<img src="{image}" alt="" loading="lazy">' if image else '<div class="no-image">No image</div>'
    )
    flags = []
    if row.get("missing_live"):
        flags.append('<span class="flag danger">Missing live row</span>')
    if row.get("product_id"):
        flags.append('<span class="flag danger">Currently linked</span>')
    if row.get("report_name_changed"):
        flags.append('<span class="flag warn">Name changed since report</span>')
    if "in_stock" not in row:
        stock = "Stock unknown (offline)"
    else:
        stock = "In stock" if row.get("in_stock") else "Out of stock"
    specs = esc(_json_text(row.get("raw_specs")))
    evidence = esc(_json_text(row.get("identity")))
    return f"""
      <section class="listing">
        <div class="image">{image_html}</div>
        <div class="listing-main">
          <div class="listing-top">
            <span class="shop">{esc(shop.get("name") or shop.get("slug") or row.get("shop_id") or "?")}</span>
            <span class="price">{esc(_price(row))}</span>
            <span class="stock">{stock}</span>
            {''.join(flags)}
          </div>
          <h3>{title_html}</h3>
          <div class="meta">SKU: {esc(str(row.get("sku") or "-"))} | Listing: <code>{esc(row["id"])}</code></div>
          <div class="meta">Last seen: {esc(str(row.get("last_seen_at") or "-"))}</div>
          <details><summary>Raw specs</summary><pre>{specs}</pre></details>
          <details><summary>Parsed identity evidence</summary><pre>{evidence}</pre></details>
        </div>
      </section>"""


def render_html(groups: list[dict], fingerprint: str, source_path: str) -> str:
    esc = html.escape
    summary = summarize(groups)
    categories = sorted(summary["categories"])
    reasons = sorted(summary["reasons"])
    cards = []
    for group in groups:
        search = " ".join(
            [group["category"], *group["reasons"]]
            + [row.get("raw_name") or "" for row in group["listings"]]
        ).lower()
        cards.append(f"""
    <article class="group-card"
      data-group="{group['group']}"
      data-category="{esc(group['category'], quote=True)}"
      data-reasons="{esc(' '.join(group['reasons']), quote=True)}"
      data-search="{esc(search, quote=True)}">
      <header class="group-header">
        <div>
          <span class="group-number">Group {group['group']}</span>
          <span class="category">{esc(group['category'])}</span>
          {''.join(f'<span class="reason">{esc(reason)}</span>' for reason in group['reasons'])}
        </div>
        <span>{len(group['listings'])} listings</span>
      </header>
      <div class="listings">{''.join(_listing_html(row) for row in group['listings'])}</div>
      <section class="proposal">
        <label>Proposed decision
          <select class="proposal-status">
            <option value="unreviewed">Unreviewed</option>
            <option value="keep_quarantined">Keep quarantined</option>
            <option value="merge_all">Propose merge all</option>
            <option value="split">Propose split</option>
            <option value="exclude_bad_listing">Exclude bad listing/source data</option>
            <option value="needs_research">Needs external research</option>
          </select>
        </label>
        <label>Split plan / listing IDs
          <input class="split-plan" placeholder="Example: [id1,id2] | [id3]">
        </label>
        <label>Rationale / notes
          <textarea class="proposal-notes" rows="3" placeholder="Evidence for the proposed decision"></textarea>
        </label>
      </section>
    </article>""")

    category_options = "".join(
        f'<option value="{esc(cat, quote=True)}">{esc(cat)} ({summary["categories"][cat]})</option>'
        for cat in categories
    )
    reason_options = "".join(
        f'<option value="{esc(reason, quote=True)}">{esc(reason)} ({summary["reasons"][reason]})</option>'
        for reason in reasons
    )
    listing_ids = {
        str(group["group"]): [row["id"] for row in group["listings"]]
        for group in groups
    }
    listing_ids_json = json.dumps(listing_ids).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Specsy quarantine review {fingerprint}</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1020; --card:#121a2d; --line:#27324a; --muted:#9aa7bd; --accent:#8b9cff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:#edf2ff; font:14px/1.5 system-ui,sans-serif; }}
main {{ max-width:1500px; margin:auto; padding:28px; }}
h1 {{ margin:0 0 6px; font-size:28px; }}
.muted,.meta {{ color:var(--muted); }}
.safety {{ margin:18px 0; padding:12px 16px; border:1px solid #315a48; background:#10281f; border-radius:10px; }}
.stats,.filters {{ display:flex; flex-wrap:wrap; gap:10px; margin:16px 0; }}
.stat,.filters input,.filters select,.filters button {{ border:1px solid var(--line); background:var(--card); color:inherit; border-radius:8px; padding:9px 12px; }}
.filters input {{ flex:1; min-width:240px; }}
button {{ cursor:pointer; }}
.group-card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; margin:18px 0; overflow:hidden; }}
.group-card.hidden {{ display:none; }}
.group-header {{ display:flex; justify-content:space-between; gap:12px; padding:14px 18px; background:#182238; border-bottom:1px solid var(--line); }}
.group-number {{ font-weight:800; margin-right:10px; }}
.category,.reason,.flag {{ display:inline-block; margin:2px 4px; padding:2px 7px; border-radius:999px; font-size:12px; }}
.category {{ background:#28365c; }} .reason {{ background:#4a2e42; }}
.flag.danger {{ background:#672d39; }} .flag.warn {{ background:#684f20; }}
.listing {{ display:grid; grid-template-columns:110px 1fr; gap:16px; padding:16px 18px; border-bottom:1px solid var(--line); }}
.image img,.no-image {{ width:100px; height:100px; object-fit:contain; border-radius:8px; background:white; }}
.no-image {{ display:grid; place-items:center; background:#202a40; color:var(--muted); font-size:12px; }}
.listing-top {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.shop {{ font-weight:700; }} .price {{ color:#8ee7b0; font-weight:700; }}
h3 {{ margin:8px 0; font-size:17px; }} a {{ color:#c9d2ff; }}
details {{ margin-top:8px; }} summary {{ cursor:pointer; color:var(--accent); }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#0c1323; padding:10px; border-radius:8px; }}
.proposal {{ display:grid; grid-template-columns:220px 1fr 1.4fr; gap:12px; padding:16px 18px; background:#0f1728; }}
.proposal label {{ display:flex; flex-direction:column; gap:5px; color:var(--muted); }}
.proposal select,.proposal input,.proposal textarea {{ width:100%; padding:8px; border:1px solid var(--line); border-radius:7px; background:#151f34; color:#fff; }}
code {{ user-select:all; }}
@media (max-width:800px) {{ main {{ padding:14px; }} .proposal {{ grid-template-columns:1fr; }} .listing {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
  <h1>Quarantined match review</h1>
  <div class="muted">Source: {esc(source_path)} | fingerprint: <code>{fingerprint}</code></div>
  <div class="safety"><strong>Read-only:</strong> live data was fetched with SELECT queries only. Choices below are local proposals and cannot alter matching rules or production mappings.</div>
  <div class="stats">
    <span class="stat">{summary['groups']} groups</span>
    <span class="stat">{summary['listings']} listings</span>
    <span class="stat">{summary['missing_live']} missing live</span>
    <span class="stat">{summary['linked_live']} already linked</span>
    <span class="stat">{summary['renamed_live']} renamed</span>
    <span class="stat" id="visible-count">{summary['groups']} visible</span>
  </div>
  <div class="filters">
    <input id="search" type="search" placeholder="Search titles, category, reason">
    <select id="category"><option value="">All categories</option>{category_options}</select>
    <select id="reason"><option value="">All reasons</option>{reason_options}</select>
    <select id="review-status">
      <option value="">All review states</option><option value="unreviewed">Unreviewed</option>
      <option value="reviewed">Any proposed decision</option>
    </select>
    <button id="export">Export proposals CSV</button>
    <button id="clear">Clear local proposals</button>
  </div>
  <div id="groups">{''.join(cards)}</div>
</main>
<script>
const REPORT = "{fingerprint}";
const STORAGE_KEY = "specsy-quarantine-" + REPORT;
const LISTING_IDS = {listing_ids_json};
const cards = [...document.querySelectorAll(".group-card")];
const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}");

function fields(card) {{
  return {{
    status: card.querySelector(".proposal-status"),
    split: card.querySelector(".split-plan"),
    notes: card.querySelector(".proposal-notes")
  }};
}}
for (const card of cards) {{
  const value = saved[card.dataset.group] || {{}};
  const f = fields(card);
  f.status.value = value.status || "unreviewed";
  f.split.value = value.split || "";
  f.notes.value = value.notes || "";
  for (const input of Object.values(f)) input.addEventListener("input", save);
}}
function save() {{
  const out = {{}};
  for (const card of cards) {{
    const f = fields(card);
    if (f.status.value !== "unreviewed" || f.split.value || f.notes.value) {{
      out[card.dataset.group] = {{status:f.status.value, split:f.split.value, notes:f.notes.value}};
    }}
  }}
  localStorage.setItem(STORAGE_KEY, JSON.stringify(out));
  filterCards();
}}
function filterCards() {{
  const query = document.querySelector("#search").value.toLowerCase();
  const category = document.querySelector("#category").value;
  const reason = document.querySelector("#reason").value;
  const review = document.querySelector("#review-status").value;
  let visible = 0;
  for (const card of cards) {{
    const status = fields(card).status.value;
    const show = (!query || card.dataset.search.includes(query))
      && (!category || card.dataset.category === category)
      && (!reason || card.dataset.reasons.split(" ").includes(reason))
      && (!review || (review === "unreviewed" ? status === "unreviewed" : status !== "unreviewed"));
    card.classList.toggle("hidden", !show);
    if (show) visible++;
  }}
  document.querySelector("#visible-count").textContent = visible + " visible";
}}
for (const id of ["search","category","reason","review-status"]) {{
  document.querySelector("#" + id).addEventListener("input", filterCards);
}}
function csvCell(value) {{
  const text = String(value ?? "");
  return '"' + text.replaceAll('"', '""') + '"';
}}
document.querySelector("#export").addEventListener("click", () => {{
  const rows = [["report_fingerprint","group","category","reasons","proposal","split_plan","notes","listing_ids"]];
  for (const card of cards) {{
    const f = fields(card);
    if (f.status.value === "unreviewed" && !f.split.value && !f.notes.value) continue;
    rows.push([REPORT, card.dataset.group, card.dataset.category, card.dataset.reasons,
      f.status.value, f.split.value, f.notes.value, LISTING_IDS[card.dataset.group].join(";")]);
  }}
  const csv = rows.map(row => row.map(csvCell).join(",")).join("\\r\\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], {{type:"text/csv;charset=utf-8"}}));
  link.download = "quarantine_proposals_" + REPORT + ".csv";
  link.click();
  URL.revokeObjectURL(link.href);
}});
document.querySelector("#clear").addEventListener("click", () => {{
  if (!confirm("Clear every local proposal for this report?")) return;
  localStorage.removeItem(STORAGE_KEY);
  location.reload();
}});
filterCards();
</script>
</body>
</html>"""


def run(args) -> None:
    groups, fingerprint = read_report(args.input)
    if not args.offline:
        from scraper.db import get_client
        enrich_groups(groups, get_client())
    print_summary(groups, fingerprint)
    if args.group is not None:
        print_group(groups, args.group)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_html(groups, fingerprint, str(Path(args.input).resolve())),
        encoding="utf-8",
    )
    print(f"review workspace   : {output.resolve()}")
    print("proposal exports are local review artifacts only; no DB apply path exists.")
    if args.open:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="reports/quarantined_groups.csv")
    parser.add_argument("--output", default="reports/quarantine_review.html")
    parser.add_argument("--offline", action="store_true", help="use CSV fields only; skip live SELECT enrichment")
    parser.add_argument("--group", type=int, help="also print one group in the terminal")
    parser.add_argument("--open", action="store_true", help="open the generated HTML in the default browser")
    parsed = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(parsed)
