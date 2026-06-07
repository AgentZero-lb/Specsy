"""Framework-free tests for public API launch safety."""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from fastapi import HTTPException  # noqa: E402
from api.main import app  # noqa: E402
from api import retry  # noqa: E402


class _TransientQuery:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def execute(self):
        import httpx

        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("temporary reset")
        return "ok"


def test_admin_routes_disabled_by_default():
    paths = {route.path for route in app.routes}
    assert "/admin/matches" not in paths
    assert "/admin/match-queue" not in paths


def test_transient_supabase_failure_is_retried():
    query = _TransientQuery(failures=2)
    original_sleep = retry.time.sleep
    retry.time.sleep = lambda _seconds: None
    try:
        assert retry.execute_query(query) == "ok"
        assert query.calls == 3
    finally:
        retry.time.sleep = original_sleep


def test_exhausted_supabase_failure_returns_503():
    query = _TransientQuery(failures=3)
    original_sleep = retry.time.sleep
    retry.time.sleep = lambda _seconds: None
    try:
        try:
            retry.execute_query(query)
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 503
    finally:
        retry.time.sleep = original_sleep


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
