"""JOLTS labour-market tightness — the red/blue-ocean layer (offline, HR-1).

These tests never touch the network: ``fetch_jolts(allow_live=False)`` with no
cache falls through to the committed seed, which is the same path a fresh
clone takes.
"""
from __future__ import annotations

import json

import pytest

from services import labor_tightness as lt


@pytest.fixture()
def seed_data():
    """The committed offline seed — no cache, no network."""
    return lt.fetch_jolts(cache_path="/nonexistent/cache.json", allow_live=False)


# --- series construction ----------------------------------------------------
def test_series_id_matches_the_jolts_layout():
    # JTS + industry(6) + state(2) + area(5) + sizeclass(2) + element(3)
    assert lt.series_id("000000", "JOL") == "JTS000000000000000JOL"
    assert len(lt.series_id("620000", "QUR")) == 21


def test_every_required_series_is_in_the_committed_seed(seed_data):
    missing = [s for s in lt.required_series() if s not in seed_data]
    assert missing == [], f"seed is missing {len(missing)} series: {missing[:5]}"


def test_request_chunking_respects_the_bls_per_query_cap(monkeypatch):
    """Over the cap BLS answers 200 with a truncated result, not an error."""
    seen: list[list[str]] = []

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"Results": {"series": []}}

    def fake_post(url, json=None, timeout=None):
        seen.append(json["seriesid"])
        return _Resp()

    fake_requests = type("m", (), {"post": staticmethod(fake_post)})
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
    monkeypatch.setenv("BLS_API_KEY", "test-key")

    lt._fetch_live([f"S{i}" for i in range(73)], None, None)
    assert len(seen) == 2                      # 73 series -> 50 + 23
    assert all(len(chunk) <= lt._MAX_SERIES_REGISTERED for chunk in seen)
    assert sum(len(c) for c in seen) == 73     # nothing silently dropped


def test_anonymous_callers_get_the_smaller_chunk(monkeypatch):
    seen: list[list[str]] = []

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"Results": {"series": []}}

    fake_requests = type("m", (), {
        "post": staticmethod(lambda url, json=None, timeout=None:
                             (seen.append(json["seriesid"]), _Resp())[1])})
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)
    monkeypatch.delenv("BLS_API_KEY", raising=False)

    lt._fetch_live([f"S{i}" for i in range(60)], None, None)
    assert all(len(chunk) <= lt._MAX_SERIES_ANONYMOUS for chunk in seen)


# --- the numbers ------------------------------------------------------------
def test_market_tightness_is_vacancies_over_seekers(seed_data):
    m = lt.market_tightness(seed_data)
    assert m["theta"] is not None
    assert m["theta"] == pytest.approx(
        m["openings_thousands"] / m["unemployed_thousands"], rel=1e-3)
    assert 0.2 < m["theta"] < 5.0            # sanity, not a forecast
    assert m["openings_as_of"] and m["unemployment_as_of"]


def test_worker_leverage_is_relative_to_the_whole_economy():
    baseline = {"openings_rate": 4.0, "quits_rate": 2.0,
                "openings_per_hire": 1.5, "layoffs_rate": 1.0}
    assert lt.worker_leverage(dict(baseline), baseline) == pytest.approx(1.0)

    tight = {**baseline, "openings_rate": 8.0}       # twice the unmet demand
    assert lt.worker_leverage(tight, baseline) > 1.0

    slack = {**baseline, "openings_rate": 2.0, "quits_rate": 1.0}
    assert lt.worker_leverage(slack, baseline) < 1.0


def test_layoff_risk_penalises_but_only_above_the_baseline():
    baseline = {"openings_rate": 4.0, "quits_rate": 2.0,
                "openings_per_hire": 1.5, "layoffs_rate": 1.0}
    safer = lt.worker_leverage({**baseline, "layoffs_rate": 0.2}, baseline)
    assert safer == pytest.approx(1.0)               # below baseline: no bonus
    riskier = lt.worker_leverage({**baseline, "layoffs_rate": 2.0}, baseline)
    assert riskier < 1.0


def test_leverage_is_none_when_nothing_was_measured():
    assert lt.worker_leverage({}, {"openings_rate": 4.0}) is None


def test_classify_ocean_thresholds():
    assert lt.classify_ocean(1.30) == "blue_ocean"
    assert lt.classify_ocean(1.00) == "balanced"
    assert lt.classify_ocean(0.50) == "red_ocean"
    assert lt.classify_ocean(None) == "unknown"


# --- honesty about resolution ----------------------------------------------
def test_agriculture_is_reported_uncovered_not_approximated():
    """JOLTS is nonfarm; a neighbouring industry's number would be a fiction."""
    assert lt.JOLTS_INDUSTRY["Agriculture"][0] is None
    result = lt.industry_tightness(lt.fetch_jolts(
        cache_path="/nonexistent/cache.json", allow_live=False))
    agri = result["Agriculture"]
    assert agri.covered is False
    assert agri.verdict == "not_covered"
    assert agri.worker_leverage is None


def test_every_record_declares_industry_granularity(seed_data):
    """There is no occupational vacancy series; callers must not forget."""
    for t in lt.industry_tightness(seed_data).values():
        assert t.granularity == "industry"
    assert lt.tightness_report(data=seed_data)["granularity"] == "industry"


def test_occupations_sharing_an_industry_share_the_reading(seed_data):
    """Tech and Legal both map to Professional and business services."""
    jobs = [{"id": "a", "industry": "Tech"}, {"id": "b", "industry": "Legal"}]
    got = lt.tightness_for_jobs(jobs, seed_data)
    assert got["a"].jolts_code == got["b"].jolts_code == "540099"
    assert got["a"].worker_leverage == got["b"].worker_leverage


def test_unmapped_kb_industry_degrades_to_not_covered(seed_data):
    got = lt.tightness_for_jobs([{"id": "x", "industry": "Astrology"}], seed_data)
    assert got["x"].covered is False and got["x"].verdict == "not_covered"


def test_report_flags_the_composite_as_a_prior(seed_data):
    assert lt.tightness_report(data=seed_data)["worker_leverage_weights_are_a_prior"]


def test_every_kb_industry_has_a_mapping_decision():
    """A new KB industry must be mapped or explicitly marked uncovered."""
    jobs = json.load(open("data/jobs_kb.json", encoding="utf-8"))
    unmapped = {j["industry"] for j in jobs} - set(lt.JOLTS_INDUSTRY)
    assert unmapped == set(), f"KB industries with no JOLTS decision: {unmapped}"


# --- the dead-mapping regression -------------------------------------------
def test_bls_series_map_only_names_kb_rows_that_exist():
    """Five of seven entries pointed at ids that had drifted away, silently."""
    from services.job_market import BLS_SERIES_MAP

    jobs = json.load(open("data/jobs_kb.json", encoding="utf-8"))
    ids = {j["id"] for j in jobs}
    dangling = {sid: jid for sid, jid in BLS_SERIES_MAP.items() if jid not in ids}
    assert dangling == {}, f"BLS_SERIES_MAP points at missing KB rows: {dangling}"
