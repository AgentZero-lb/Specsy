# Quarantined Group Review

This workflow is read-only. It does not change matcher rules, `product_id`,
`match_decisions`, or any other database row.

## Build the review workspace

From `backend/`:

```powershell
python scripts/review_quarantine.py --open
```

The command reads `reports/quarantined_groups.csv`, fetches current listing data
with Supabase `SELECT` queries, and creates
`reports/quarantine_review.html`. Generated reports remain gitignored.

Useful variants:

```powershell
# Inspect one group in the terminal as well as HTML
python scripts/review_quarantine.py --group 9

# Review the CSV without database access
python scripts/review_quarantine.py --offline
```

## Review decisions

The HTML workspace supports search and category/reason/review-state filters. Each
group can be marked with one local proposal:

- Keep quarantined
- Propose merge all
- Propose split
- Exclude bad listing/source data
- Needs external research

Notes and split plans are stored in browser local storage under the report
fingerprint. **Export proposals CSV** downloads only reviewed groups, including
the fingerprint and exact listing IDs.

The proposal CSV is intentionally inert. No script consumes or applies it. Review
the exported decisions together before changing identity rules or production
mappings. Re-run the matcher dry run after any approved rule change because
quarantine group numbers can change between reports.

## Safety checks

The workspace highlights:

- Listings missing from the live database
- Quarantined listings that are currently linked
- Listing names that changed since the CSV was generated

Any of these means the report may be stale. Regenerate it with:

```powershell
python -m scraper.match
```

That command is also dry-run unless both `--reset --apply` are supplied.

## Tests

```powershell
python tests/test_quarantine_review.py
```
