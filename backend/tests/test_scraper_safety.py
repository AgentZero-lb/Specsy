"""Framework-free tests for full-catalog scrape safety."""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from scraper.db import plan_missing_listings  # noqa: E402


def test_healthy_full_scrape_marks_only_missing():
    existing = {f"l{i}" for i in range(10)}
    seen = {f"l{i}" for i in range(9)}
    assert plan_missing_listings(existing, seen) == ["l9"]


def test_partial_scrape_cannot_mark_catalog_unavailable():
    existing = {f"l{i}" for i in range(10)}
    seen = {"l0", "l1", "l2"}
    assert plan_missing_listings(existing, seen) == []


def test_new_listings_do_not_reduce_coverage():
    existing = {"old-1", "old-2"}
    seen = {"old-1", "old-2", "new-1"}
    assert plan_missing_listings(existing, seen) == []


def test_empty_existing_catalog_is_safe():
    assert plan_missing_listings(set(), {"new-1"}) == []


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
