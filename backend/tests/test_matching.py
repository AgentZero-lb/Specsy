"""Focused tests for the hardened matcher — strict identity, SKU conflicts, fail-closed
group validation, transitive-merge prevention, staged/atomic apply, restore, and unmatch.

No pytest required:  cd backend && python tests/test_matching.py
"""
import contextlib
import io
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_BACKEND, "scripts"))

from scraper import identity, match                                       # noqa: E402
from scraper.match import (sku_pass, build_groups, norm_sku, validate_group,  # noqa: E402
                           quarantine_aliases, supersede_pending_queue, stage_rebuild,
                           validate_staging, brand_of)
import unmatch                                                            # noqa: E402
import restore_mapping                                                    # noqa: E402


def L(i, shop, name, cat, sku=None, specs=None, pid=None):
    return {"id": f"l{i}", "shop_id": shop, "raw_name": name, "category_slug": cat,
            "sku": sku, "raw_specs": specs or {}, "product_id": pid, "price_usd": None}


def keys(name, cat, specs=None):
    return identity.identity_keys(cat, name, specs or {}, None)


# ───────────────────────────── strict identity ─────────────────────────────────


def test_gpu_variant_distinct():
    assert not (keys("ASUS Dual GeForce RTX 5070 OC 12GB", "gpu")
                & keys("Zotac Gaming GeForce RTX 5070 Solid 12GB", "gpu"))


def test_gpu_same_product_via_code():
    assert (keys("ASUS DUAL Geforce RTX 5070 12GB GDDR7 90YV0M17-M0NA00", "gpu")
            & keys("Asus Dual RTX 5070 12GB 90YV0M17-M0NA00 OC", "gpu"))


def test_cpu_suffix_distinct():
    assert not (keys("Intel Core i7-14700K", "cpu") & keys("Intel Core i7-14700KF", "cpu"))


def test_ram_kit_distinct():
    assert not (keys("Kingston Fury Beast 32GB (2x16GB) DDR5 6000MHz", "ram")
                & keys("Kingston Fury Beast 32GB (1x32GB) DDR5 6000MHz", "ram"))


def test_unknown_gpu_chip_yields_no_key():
    # deterministic (previously a tautological `== set() or True`)
    assert keys("RTX graphics card", "gpu") == set()


# ── identity edge cases (item 5) ──


def test_unsafe_aliases_removed():
    assert identity.brand("d random cable", {}) is None         # no lone "d"
    assert identity.brand("rgb cpu cooler fan", {}) is None     # no lone "cooler"
    assert identity.brand(identity._clean("D-Link DIR-X"), {}) == "dlink"
    assert identity.brand(identity._clean("G.Skill Trident"), {}) == "gskill"


def test_hyperx_kingston_only_for_ram():
    # RAM: HyperX Fury == Kingston Fury (valid rebrand)
    assert keys("HyperX Fury 32GB (2x16GB) DDR5 6000MHz", "ram") \
        & keys("Kingston Fury 32GB (2x16GB) DDR5 6000MHz", "ram")
    # mouse: HyperX stays HyperX (must NOT collapse to Kingston)
    assert brand_of(L(1, "A", "HyperX Pulsefire Mouse", "mouse")) == "hyperx"


def test_laptop_requires_exact_cpu():
    assert keys("Lenovo V15 83HF i7 16GB 512GB SSD", "laptop") == set()      # coarse i7 -> none
    assert keys("Lenovo V15 83HF00EMIG i7-13620H 16GB 512GB SSD", "laptop")  # exact -> keys


def test_laptop_ssd_and_cpu_gen_differences():
    base = "Lenovo V15 83HF00EMIG {cpu} 16GB {ssd} SSD"
    assert not (keys(base.format(cpu="i7-13620H", ssd="512GB"), "laptop")
                & keys(base.format(cpu="i7-13620H", ssd="1TB"), "laptop"))   # SSD differs
    assert not (keys(base.format(cpu="i7-13620H", ssd="512GB"), "laptop")
                & keys(base.format(cpu="i7-1355U", ssd="512GB"), "laptop"))  # CPU gen differs


def test_title_spec_conflict_detected():
    assert identity.title_spec_conflict("gpu", "ASUS RTX 5070 8GB", {"MEMORY SIZE": "12GB"})
    assert not identity.title_spec_conflict("gpu", "ASUS RTX 5070 12GB", {"MEMORY SIZE": "12GB"})


def test_motherboard_identity_is_variant_aware():
    wifi_ddr5 = keys("MSI PRO B760M-A WIFI DDR5 LGA1700", "motherboard")
    same = keys("MSI Pro B760M-A WiFi DDR5 Motherboard", "motherboard")
    assert wifi_ddr5 & same
    assert not (wifi_ddr5 & keys("MSI PRO B760M-A WIFI DDR4", "motherboard"))
    assert not (wifi_ddr5 & keys("MSI PRO B760M-A DDR5", "motherboard"))
    assert not (wifi_ddr5 & keys("MSI PRO B760M-A WIFI DDR5 II", "motherboard"))


def test_motherboard_real_b760ma_group_keeps_only_proven_equivalents():
    ls = [
        L(1, "P", "MSI PRO B760M-A DDR4 II (TAX included)", "motherboard"),
        L(2, "P", "MSI PRO B760M-A WIFI DDR5 LGA1700 (TAX included)", "motherboard"),
        L(3, "A", "MSI Pro B760M-A WiFi DDR5 Motherboard", "motherboard"),
        L(4, "P", "MSI PRO B760M-A WIFI DDR4", "motherboard"),
        L(5, "A", "MSI Pro B760M-A Wifi MotherBoard | 911-7D99-057", "motherboard"),
    ]
    accepted, _quarantined, *_ = build_groups(ls)
    accepted_sets = [set(idxs) for _method, idxs in accepted]
    assert {1, 2} in accepted_sets
    assert all(not ({0, 3, 4} & idxs) for idxs in accepted_sets)


def test_motherboard_biostar_editions_do_not_merge():
    ls = [
        L(1, "P", "Biostar TB360-BTC PRO for Mining", "motherboard"),
        L(2, "M", "Biostar TB360-BTC Pro 2.0 Crypto Mining ATX Motherboard", "motherboard"),
        L(3, "A", "Biostar TB360-BTC D+ for Mining", "motherboard"),
    ]
    accepted, _quarantined, *_ = build_groups(ls)
    assert accepted == []


def test_motherboard_group_validation_treats_known_unknown_as_conflict():
    ls = [
        L(1, "A", "MSI PRO B760M-A WIFI DDR5", "motherboard"),
        L(2, "B", "MSI PRO B760M-A DDR5", "motherboard"),
    ]
    ok, reasons = validate_group([0, 1], ls)
    assert not ok and "wifi-conflict" in reasons


def test_motherboard_signature_parses_aliases_without_mistaking_specs_for_revisions():
    ddr, wireless, revision, line = identity.motherboard_signature(
        "Gigabyte B760 DS3H AX D4 PCIe 5.0 Bluetooth 5.4", {}
    )
    assert (ddr, wireless, revision) == ("ddr4", "wifi", None)
    assert identity.motherboard_revision("ASRock H610M-HDV/M.2 R2.0 DDR4") == "2.0"
    assert identity.motherboard_revision("Gigabyte B650M S2H (1.2) DDR5") == "1.2"
    assert line is None


# ──────────────────────────────── SKU conflicts ────────────────────────────────


def test_norm_sku():
    assert norm_sku("ZT-B50600F-10M") == "ztb50600f10m"
    assert norm_sku(None) == ""


def test_sku_conflict_brand_and_category():
    g, c = sku_pass([L(1, "A", "Asus Widget", "mouse", sku="SHARED123"),
                     L(2, "B", "MSI Widget", "mouse", sku="SHARED123")])
    assert g == [] and any(r == "brand" for r, *_ in c)
    g, c = sku_pass([L(1, "A", "Corsair Thing", "mouse", sku="DUP9"),
                     L(2, "B", "Corsair Thing", "keyboard", sku="DUP9")])
    assert any(r == "category" for r, *_ in c)


# ─────────────────────── fail-closed validation + transitive ───────────────────


def test_validate_group_rejects_incoherent():
    g = [L(1, "A", "ASUS RTX 5070 12GB", "gpu"), L(2, "B", "ASUS RTX 5080 16GB", "gpu")]
    ok, reasons = validate_group([0, 1], g)
    assert not ok and "cross-chip" in reasons


def test_transitive_chain_not_overmerged():
    # B is a bundle bridging a 5070 code and a 5080 code; chip-qualified keys stop the
    # cross-chip union, and the bundle component is quarantined (fail closed).
    ls = [L(1, "A", "Zotac RTX 5070 SOLID ZT-B50700D-10P", "gpu"),
          L(2, "B", "Zotac RTX 5070 ZT-B50700D-10P ZT-B50800D-10P", "gpu"),
          L(3, "C", "Zotac RTX 5080 SOLID ZT-B50800D-10P", "gpu")]
    accepted, quarantined, *_ = build_groups(ls)
    for _m, idxs in accepted:                       # no accepted group mixes chips
        chips = {identity.gpu_chip(identity._clean(ls[i]["raw_name"]), {}) for i in idxs}
        assert len(chips - {None}) <= 1
    assert not any({0, 2} <= set(idxs) for _m, idxs in accepted)   # 5070 never merged with 5080


def test_wrong_mpn_pulsefire_quarantined():
    # Ayoub mislabels the Surge with the Saga's MPN -> same code, conflicting name.
    ls = [L(1, "A", "HyperX Pulsefire Saga Gaming Mouse A2PB3AA", "mouse"),
          L(2, "B", "HyperX Pulsefire Surge RGB Gaming Mouse A2PB3AA", "mouse")]
    accepted, quarantined, *_ = build_groups(ls)
    assert accepted == [], "wrong-MPN pair must NOT auto-apply"
    assert any("name-conflict" in r for r, _ in quarantined)


def test_suspicious_excluded_from_apply():
    # a multi-model bundle group is quarantined, never accepted
    ls = [L(1, "A", "Seagate 4TB ST4000VX015 / ST4000VX013 Surveillance HDD", "storage"),
          L(2, "B", "Seagate 4TB ST4000VX013 HDD", "storage")]
    accepted, quarantined, *_ = build_groups(ls)
    q_listings = {i for _r, idxs in quarantined for i in idxs}
    a_listings = {i for _m, idxs in accepted for i in idxs}
    assert q_listings and not (q_listings & a_listings)


# ───────────────────────────── FakeSupabase ────────────────────────────────────


class _Res:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _RPC:
    def __init__(self, sb):
        self.sb = sb

    def execute(self):
        if self.sb.rpc_raises:
            raise RuntimeError("activation boom")
        return _Res(None)


class _Q:
    def __init__(self, sb, t):
        self.sb, self.t, self.verb, self._count, self._result = sb, t, "select", None, None
        self._range = None

    def select(self, *a, **k):
        self.verb, self._count = "select", k.get("count")
        return self

    def insert(self, rows):
        self.verb = "insert"
        self.sb.ops.append(("insert", self.t))
        rows = rows if isinstance(rows, list) else [rows]
        base = len(self.sb.data.get(self.t, []))
        stored = [{**r, "id": r.get("id", f"{self.t}-{base + i}")} for i, r in enumerate(rows)]
        self.sb.data.setdefault(self.t, []).extend(stored)
        self._result = stored
        return self

    def update(self, d):
        self.verb = "update"
        self.sb.ops.append(("update", self.t, d))
        return self

    def delete(self):
        self.verb = "delete"
        self.sb.ops.append(("delete", self.t))
        return self

    def eq(self, *a):
        return self

    def in_(self, *a):
        return self

    def is_(self, *a):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, *a):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        if self.t in self.sb.missing:
            raise RuntimeError("relation missing")
        if self.verb == "insert":
            return _Res(self._result)
        data = self.sb.data.get(self.t, [])
        if self._count == "exact":
            return _Res(data[:1], count=len(data))
        if self._range is not None:
            start, end = self._range
            data = data[start:end + 1]
        return _Res(data)


class FakeSupabase:
    def __init__(self, data=None, missing=(), rpc_raises=False):
        self.data = {k: list(v) for k, v in (data or {}).items()}
        self.missing, self.ops, self.rpc_calls, self.rpc_raises = set(missing), [], [], rpc_raises

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _RPC(self)


def _ops(fake, op, table):
    return [o for o in fake.ops if o[0] == op and o[1] == table]


# ───────────────────── staged / atomic apply + failure safety ───────────────────


def test_stage_rebuild_keeps_listings_live():
    ls = [L(1, "A", "ASUS DUAL RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None),
          L(2, "B", "Asus Dual RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None)]
    accepted, _q, _c, kk, _conf, msku = build_groups(ls)
    fake = FakeSupabase(data={"products": [], "match_decisions": []})
    n = stage_rebuild(fake, ls, accepted, kk, msku, {"gpu": 2}, "run-1")
    assert n == 2
    assert _ops(fake, "insert", "products"), "fresh products created"
    assert _ops(fake, "insert", "match_decisions"), "decisions staged"
    assert not _ops(fake, "update", "listings"), "staging must NOT repoint listings (stay live)"
    assert all(l["product_id"] is None for l in ls)
    staged = fake.data["match_decisions"]
    assert staged and all(d["status"] == "staged" and d["rebuild_run_id"] == "run-1" for d in staged)
    assert all(d["identity_key"] for d in staged), "per-listing identity_key recorded"


def test_apply_is_atomic_and_no_python_listing_writes(monkeypatch=None):
    ls = [L(1, "A", "ASUS DUAL RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None),
          L(2, "B", "Asus Dual RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None)]
    fake = FakeSupabase(data={
        "categories": [{"id": 1, "slug": "gpu"}], "shops": [{"id": "A", "slug": "A"}, {"id": "B", "slug": "B"}],
        "listings": ls, "products": [], "product_aliases": [], "match_decisions": []})
    match.get_client = lambda: fake
    match.export_mapping = lambda *a, **k: "noop"
    match.write_quarantine_report = lambda *a, **k: "noop"
    with contextlib.redirect_stdout(io.StringIO()):
        match.run(apply=True, reset=True)
    assert fake.rpc_calls and fake.rpc_calls[0][0] == "activate_rebuild", "must activate atomically"
    assert not _ops(fake, "update", "listings"), "listings repointed only by the SQL function"
    assert not [o for o in fake.ops if o[0] == "delete"], "nothing deleted"


def test_activation_sql_rejects_unknown_or_empty_runs():
    migrations = os.path.join(_BACKEND, "db", "migrations")
    for name in ("003_match_decisions.sql", "004_harden_activate_rebuild.sql"):
        src = open(os.path.join(migrations, name), encoding="utf-8").read().lower()
        guard = src.index("if v_staged_count = 0")
        unlink = src.index("set product_id = null")
        assert guard < unlink, f"{name} must reject an empty staged run before unlinking"
        assert "count(distinct listing_id)" in src


def test_activation_failure_leaves_production_untouched():
    ls = [L(1, "A", "ASUS DUAL RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None),
          L(2, "B", "Asus Dual RTX 5070 12GB 90YV0M17-M0NA00", "gpu", pid=None)]
    fake = FakeSupabase(data={
        "categories": [{"id": 1, "slug": "gpu"}], "shops": [{"id": "A", "slug": "A"}, {"id": "B", "slug": "B"}],
        "listings": ls, "products": [], "product_aliases": [], "match_decisions": []}, rpc_raises=True)
    match.get_client = lambda: fake
    match.export_mapping = lambda *a, **k: "noop"
    match.write_quarantine_report = lambda *a, **k: "noop"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            match.run(apply=True, reset=True)
        assert False, "should have exited on activation failure"
    except SystemExit as e:
        assert e.code == 3
    assert not _ops(fake, "update", "listings"), "no listing was repointed by Python on failure"


def test_quarantine_aliases_updates_not_deletes():
    fake = FakeSupabase(data={"product_aliases": [
        {"id": "a1", "source": "confirmed"}, {"id": "a2", "source": "quarantined"}]})
    assert quarantine_aliases(fake) == 1
    assert ("update", "product_aliases", {"source": "quarantined"}) in fake.ops
    assert not [o for o in fake.ops if o[0] == "delete"]


def test_staging_validation_and_alias_quarantine_page_past_1000():
    decisions = [
        {"listing_id": f"l{i}", "product_id": f"p{i // 5}"}
        for i in range(1025)
    ]
    aliases = [{"id": f"a{i}", "source": "confirmed"} for i in range(1205)]
    fake = FakeSupabase(data={"match_decisions": decisions, "product_aliases": aliases})
    validate_staging(fake, "run-1", {f"l{i}" for i in range(1025)}, 205)
    assert quarantine_aliases(fake) == 1205


def test_pending_queue_is_superseded_without_deleting_history():
    queue = [{"id": f"q{i}", "status": "pending"} for i in range(1205)]
    fake = FakeSupabase(data={"match_queue": queue})
    assert supersede_pending_queue(fake) == 1205
    assert ("update", "match_queue", fake.ops[-1][2]) in fake.ops
    assert fake.ops[-1][2]["status"] == "superseded"
    assert not [o for o in fake.ops if o[0] == "delete"]


def test_match_has_no_python_listing_repoint_and_no_deletes():
    src = open(match.__file__, encoding="utf-8").read()
    assert ".delete()" not in src, "match.py must not delete rows"
    assert 'update({"product_id"' not in src, "listings.product_id is repointed only by activate_rebuild()"


# ──────────────────────────── restore / unmatch ────────────────────────────────


def test_restore_plan():
    rows = [{"listing_id": "l1", "product_id": "P1"}, {"listing_id": "l2", "product_id": None},
            {"listing_id": "l3", "product_id": "P3"}]
    current = {"l1": "PX", "l2": "P2", "l3": "P3"}      # l3 already correct
    changes = restore_mapping.plan_restore(rows, current)
    assert ("l1", "P1") in changes and ("l2", None) in changes
    assert all(lid != "l3" for lid, _ in changes)


def test_unmatch_plan_preserves_unrelated():
    active = [{"id": "d1", "listing_id": "l1", "product_id": "P1"},
              {"id": "d2", "listing_id": "l2", "product_id": "P1"}]
    rev, unlink, preserved = unmatch.plan_reversal(active, {"l1": "P1", "l2": "P9"})
    assert set(rev) == {"d1", "d2"} and unlink == ["l1"] and preserved == [("l2", "P9")]


def test_unmatch_apply_requires_reviewer_and_reason():
    for reviewer, reason in [(None, "x"), ("me", None), (None, None)]:
        try:
            unmatch.run(product_id="P1", decision_id=None, apply=True, reviewer=reviewer, reason=reason)
            assert False, "apply without reviewer+reason must fail"
        except SystemExit:
            pass


# ───────────────────── queue-only vector + llm (unchanged guards) ───────────────


def test_match_llm_failure_not_cached_as_rejection():
    import scraper.match_llm as ml

    class _Boom:
        class messages:
            @staticmethod
            def parse(*a, **k):
                raise RuntimeError("api down")
    assert ml._judge_batch(_Boom(), [{"id": 0, "a": "x", "b": "y"}]) == {}


def test_vector_and_llm_have_no_merge_code():
    for mod in ("match_vector", "match_llm"):
        src = open(os.path.join(os.path.dirname(match.__file__), f"{mod}.py"), encoding="utf-8").read()
        assert "_ensure_product(" not in src
        assert '.table("products")' not in src
        assert 'update({"product_id"' not in src


# ───────────────────────────────── runner ──────────────────────────────────────

if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)
