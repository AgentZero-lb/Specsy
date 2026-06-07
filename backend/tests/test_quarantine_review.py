"""Framework-free tests for the read-only quarantine review workflow."""
import os
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_BACKEND, "scripts"))

import review_quarantine as review  # noqa: E402


CSV = """group,category,reasons,listing_id,shop_id,raw_name
0,mouse,name-conflict,l1,s1,Mouse <One>
0,mouse,name-conflict,l2,s2,Mouse Two
1,storage,multi-model-code,l3,s1,Drive Three
"""


def sample_report():
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    try:
        handle.write(CSV)
        handle.close()
        return handle.name
    except Exception:
        os.unlink(handle.name)
        raise


def test_read_report_groups_rows_and_fingerprints():
    path = sample_report()
    try:
        groups, fingerprint = review.read_report(path)
        assert len(groups) == 2
        assert len(groups[0]["listings"]) == 2
        assert groups[1]["reasons"] == ["multi-model-code"]
        assert len(fingerprint) == 12
    finally:
        os.unlink(path)


def test_summary_counts_groups_reasons_and_stale_rows():
    path = sample_report()
    try:
        groups, _ = review.read_report(path)
        groups[0]["listings"][0]["product_id"] = "p1"
        groups[1]["listings"][0]["missing_live"] = True
        summary = review.summarize(groups)
        assert summary["groups"] == 2 and summary["listings"] == 3
        assert summary["reasons"]["name-conflict"] == 1
        assert summary["linked_live"] == 1 and summary["missing_live"] == 1
    finally:
        os.unlink(path)


def test_html_escapes_titles_and_contains_inert_proposals():
    path = sample_report()
    try:
        groups, fingerprint = review.read_report(path)
        page = review.render_html(groups, fingerprint, path)
        assert "Mouse &lt;One&gt;" in page
        assert "Propose merge all" in page
        assert "Export proposals CSV" in page
        assert "cannot alter matching rules or production mappings" in page
    finally:
        os.unlink(path)


class _Result:
    def __init__(self, data):
        self.data = data


class _SelectOnlyQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _columns):
        return self

    def in_(self, _column, _values):
        return self

    def execute(self):
        return _Result(self.rows)


class _SelectOnlySupabase:
    def __init__(self, rows):
        self.rows = rows
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return _SelectOnlyQuery(self.rows)


def test_enrichment_uses_select_only_and_detects_renames():
    path = sample_report()
    try:
        groups, _ = review.read_report(path)
        live = [{
            "id": "l1", "shop_id": "s1", "raw_name": "Mouse One Renamed",
            "sku": None, "raw_specs": {}, "shops": {"slug": "shop-one"},
        }]
        sb = _SelectOnlySupabase(live)
        review.enrich_groups(groups, sb)
        assert sb.tables == ["listings"]
        assert groups[0]["listings"][0]["report_name_changed"] is True
        assert groups[0]["listings"][1]["missing_live"] is True
    finally:
        os.unlink(path)


def test_script_exposes_no_database_write_or_rpc_calls():
    source = open(review.__file__, encoding="utf-8").read()
    assert source.count(".table(") == 1
    for forbidden in (".delete(", ".upsert(", ".rpc("):
        assert forbidden not in source, f"read-only review script contains {forbidden}"


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed} passed, {failed} failed, {len(tests)} total")
    raise SystemExit(1 if failed else 0)
