"""Occupation-level entry competition (offline, HR-1).

The committed data/onet_related.json is the graph; nothing here touches the
network.
"""
from __future__ import annotations

import json

import pytest

from services import occupation_graph as og
from services.labor_tightness import IndustryTightness

_GRAPH = {
    "15-2051": [["15-1252", "Primary-Short"], ["13-2051", "Primary-Long"],
                ["15-1211", "Supplemental"]],
    "47-2152": [["47-2111", "Primary-Short"]],
    "99-9999": [["11-1011", "Primary-Short"]],      # feeder has no employment
}
_EMPLOYMENT = {
    "15-1252": {"title": "Software Developers", "employment": 1_500_000},
    "13-2051": {"title": "Financial Analysts", "employment": 300_000},
    "15-1211": {"title": "Systems Analysts", "employment": 500_000},
    "47-2111": {"title": "Electricians", "employment": 700_000},
    "11-1011": {"title": "Chief Executives", "employment": None},
}
_TIGHT = {
    "Tech": IndustryTightness("Tech", "540099", "Prof & business", True,
                              openings_rate=5.0),
    "Construction": IndustryTightness("Construction", "230000", "Construction",
                                      True, openings_rate=4.0),
    "Agriculture": IndustryTightness("Agriculture", None, "not covered", False),
}


def _job(jid, soc, emp, industry="Tech", title="T"):
    return {"id": jid, "title": title, "soc_code": soc,
            "bls_employment": emp, "industry": industry}


def _run(jobs, **kw):
    return og.entry_competition(jobs, tightness=_TIGHT, graph=_GRAPH,
                                employment=_EMPLOYMENT, **kw)


# --- graph shape ------------------------------------------------------------
def test_onet_soc_codes_collapse_to_soc():
    assert og._soc7("13-2011.00") == "13-2011"
    assert og._soc7("13-2011.03") == "13-2011"


def test_committed_graph_is_directed_and_joins_to_the_kb():
    graph = og.onet_related()
    assert len(graph) > 500, "committed O*NET graph missing or truncated"

    jobs = json.load(open("data/jobs_kb.json", encoding="utf-8"))
    socs = {j["soc_code"] for j in jobs if j.get("soc_code")}
    joined = socs & set(graph)
    assert len(joined) >= 40, f"only {len(joined)} KB rows join to O*NET"

    # Direction carries information: O*NET is only ~56% symmetric, so the
    # in-edge graph must not have been flattened into a symmetric one.
    forward = {(src, dst) for dst, feeders in graph.items() for src, _t in feeders}
    asymmetric = sum(1 for a, b in forward if (b, a) not in forward)
    assert asymmetric > 0


# --- the pool ---------------------------------------------------------------
def test_adjacent_pool_weights_feeders_by_tier():
    pool, feeders = og.adjacent_pool("15-2051", graph=_GRAPH, employment=_EMPLOYMENT)
    expected = 1_500_000 * 1.0 + 300_000 * 0.6 + 500_000 * 0.3
    assert pool == pytest.approx(expected)
    assert feeders == 3


def test_feeders_without_employment_are_skipped_not_imputed():
    pool, feeders = og.adjacent_pool("99-9999", graph=_GRAPH, employment=_EMPLOYMENT)
    assert pool is None and feeders == 0


def test_unknown_soc_has_no_pool():
    assert og.adjacent_pool("00-0000", graph=_GRAPH, employment=_EMPLOYMENT) == (None, 0)


def test_estimate_openings_inverts_the_jolts_rate():
    # JOLTS defines rate = V / (E + V), so V = E * r / (100 - r)
    assert og.estimate_openings(100_000, 5.0) == pytest.approx(100_000 * 5 / 95, abs=0.1)
    assert og.estimate_openings(None, 5.0) is None
    assert og.estimate_openings(100_000, None) is None
    assert og.estimate_openings(100_000, 100.0) is None


# --- silence is not good news ----------------------------------------------
def test_missing_soc_is_not_modelled_never_blue_ocean():
    (row,) = _run([_job("x", None, 50_000)])
    assert row.verdict == "not_modelled" and row.competition_ratio is None
    assert "no SOC anchor" in row.reason


def test_industry_without_jolts_coverage_is_not_modelled():
    (row,) = _run([_job("x", "15-2051", 50_000, industry="Agriculture")])
    assert row.verdict == "not_modelled"
    assert "not covered by JOLTS" in row.reason


def test_missing_employment_is_not_modelled():
    (row,) = _run([_job("x", "15-2051", None)])
    assert row.verdict == "not_modelled"
    assert "no employment figure" in row.reason


def test_occupation_with_no_feeders_is_not_modelled():
    (row,) = _run([_job("x", "11-1011", 50_000)])
    assert row.verdict == "not_modelled"
    assert "no related occupations" in row.reason


# --- ranking ----------------------------------------------------------------
def test_verdicts_are_ranks_within_the_cohort():
    jobs = [_job("a", "15-2051", 5_000), _job("b", "15-2051", 500_000),
            _job("c", "47-2152", 60_000, industry="Construction")]
    rows = {r.job_id: r for r in _run(jobs)}
    # 'a' is tiny against the same pool, so it must be the most contested
    assert rows["a"].competition_ratio > rows["b"].competition_ratio
    assert rows["a"].verdict == "red_ocean"
    assert rows["b"].verdict == "blue_ocean"
    assert all(0.0 <= r.percentile <= 1.0 for r in rows.values())


def test_ranking_is_invariant_to_the_tier_weight_prior(monkeypatch):
    """Verdicts must survive the weights being wrong — that is why ranks are used."""
    jobs = [_job("a", "15-2051", 5_000), _job("b", "15-2051", 500_000),
            _job("c", "47-2152", 60_000, industry="Construction")]
    before = {r.job_id: r.verdict for r in _run(jobs)}
    monkeypatch.setitem(og.TIER_WEIGHT, "Primary-Long", 0.95)
    monkeypatch.setitem(og.TIER_WEIGHT, "Supplemental", 0.8)
    assert {r.job_id: r.verdict for r in _run(jobs)} == before


def test_classify_by_rank_splits_into_terciles():
    got = og.classify_by_rank([float(i) for i in range(9)])
    assert got[0.0] == "blue_ocean" and got[8.0] == "red_ocean"
    assert got[4.0] == "balanced"
    assert og.classify_by_rank([]) == {}


# --- the report -------------------------------------------------------------
def test_report_accounts_for_everything_it_could_not_model():
    jobs = [_job("a", "15-2051", 5_000), _job("b", None, 10_000)]
    rep = og.competition_report(jobs, tightness=_TIGHT, graph=_GRAPH,
                                employment=_EMPLOYMENT)
    assert rep["modelled"] + rep["not_modelled"] == len(jobs)
    assert rep["granularity"] == "occupation"
    assert rep["tier_weights_are_a_prior"] is True
    assert rep["inflow_channel"] == "occupational_switchers_only"
    assert len(rep["skipped"]) == rep["not_modelled"]
    assert any("graduates" in c for c in rep["caveats"])


def test_report_differentiates_within_one_industry():
    """The whole point of this module: industry tightness cannot do this."""
    jobs = [_job("small", "15-2051", 5_000), _job("large", "15-2051", 500_000)]
    rep = og.competition_report(jobs, tightness=_TIGHT, graph=_GRAPH,
                                employment=_EMPLOYMENT)
    verdicts = {o["job_id"]: o["verdict"] for o in rep["occupations"]}
    assert verdicts["small"] != verdicts["large"]


# --- the graph this module deliberately does NOT use ------------------------
def test_kb_transition_graph_is_still_the_biased_thing_we_rejected():
    """Guards the reason for the design: if the KB graph ever becomes usable,
    this test fails and the choice can be revisited on evidence."""
    import collections

    jobs = json.load(open("data/jobs_kb.json", encoding="utf-8"))
    indeg = collections.Counter(
        t["target_id"] for j in jobs for t in (j.get("transition_targets") or []))
    total = sum(indeg.values())
    top3 = sum(n for _tid, n in indeg.most_common(3))
    assert top3 / total > 0.15, "KB transition graph looks less concentrated now"
    assert len(indeg) < len(jobs) * 0.75, "KB transition graph still misses most rows"
