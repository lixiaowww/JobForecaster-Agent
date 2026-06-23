"""Test suite for Job Forecast Radar — pure logic + regression coverage."""
from __future__ import annotations

import math

import job_radar


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _kb():
    return job_radar.load_knowledge_base("data/jobs_kb.json")


def _mini_jobs():
    return [
        {
            "id": "role_a",
            "title": "Role A",
            "title_zh": "角色A",
            "industry": "Tech",
            "category": "at_risk",
            "description": "desc a",
            "description_zh": "描述a",
            "base_demand_trend": -0.1,
            "displacement_risk": 0.8,
            "sensitivity": {"augmentation_ratio": -0.5, "diffusion_years": 0.2},
            "required_skills": ["Python", "SQL"],
            "transition_targets": [
                {"target_id": "role_b", "skill_bridge": "bridge", "retrain_months": 6, "salary_delta": 0.1},
            ],
        },
        {
            "id": "role_b",
            "title": "Role B",
            "title_zh": "角色B",
            "industry": "Tech",
            "category": "emerging",
            "description": "desc b",
            "description_zh": "描述b",
            "base_demand_trend": 0.2,
            "displacement_risk": 0.2,
            "sensitivity": {},
            "required_skills": ["ML"],
            "emergence_year": 2030,
            "transition_targets": [],
        },
    ]


# --------------------------------------------------------------------------- #
# compute_impact_scores
# --------------------------------------------------------------------------- #

def test_impact_score_formula():
    jobs = [{
        "id": "x", "title": "X", "base_demand_trend": 0.1,
        "sensitivity": {"augmentation_ratio": 0.5},
    }]
    scored = job_radar.compute_impact_scores(jobs, {"augmentation_ratio": 0.4})
    assert scored[0]["impact_score"] == round(0.1 + 0.4 * 0.5, 3)


def test_impact_score_diffusion_normalised():
    jobs = [{"id": "x", "title": "X", "base_demand_trend": 0.0,
             "sensitivity": {"diffusion_years": 1.0}}]
    scored = job_radar.compute_impact_scores(jobs, {"diffusion_years": 10.0})
    assert scored[0]["impact_score"] == round(math.log1p(10.0) / math.log1p(50), 3)


def test_impact_score_missing_fields_default_zero():
    scored = job_radar.compute_impact_scores([{"id": "x", "title": "X"}], {})
    assert scored[0]["impact_score"] == 0.0


def test_impact_score_does_not_mutate_input():
    jobs = [{"id": "x", "title": "X", "base_demand_trend": 0.1, "sensitivity": {}}]
    job_radar.compute_impact_scores(jobs, {})
    assert "impact_score" not in jobs[0]


# --------------------------------------------------------------------------- #
# filter_by_industry
# --------------------------------------------------------------------------- #

def test_filter_by_industry_all_returns_everything():
    jobs = _mini_jobs()
    assert job_radar.filter_by_industry(jobs, "All") == jobs
    assert job_radar.filter_by_industry(jobs, "") == jobs


def test_filter_by_industry_specific():
    jobs = _mini_jobs() + [{"id": "z", "title": "Z", "industry": "Finance"}]
    out = job_radar.filter_by_industry(jobs, "Finance")
    assert len(out) == 1 and out[0]["id"] == "z"


# --------------------------------------------------------------------------- #
# get_hybrid_scores
# --------------------------------------------------------------------------- #

def test_hybrid_empty_query_uses_impact_only():
    jobs = job_radar.compute_impact_scores(_mini_jobs(), {})
    out = job_radar.get_hybrid_scores(jobs, "", 0.6, 0.4)
    for j in out:
        assert j["semantic_similarity"] == 0.0
        assert j["hybrid_score"] == round(0.6 * j["impact_score"], 3)


def test_hybrid_query_adds_similarity():
    jobs = job_radar.compute_impact_scores(_kb(), {})
    out = job_radar.get_hybrid_scores(jobs, "machine learning engineer", 0.6, 0.4)
    assert all("semantic_similarity" in j for j in out)
    assert any(j["semantic_similarity"] > 0 for j in out)


# --------------------------------------------------------------------------- #
# find_best_match (relevance regressions)
# --------------------------------------------------------------------------- #

def test_finance_query_matches_finance_industry():
    _, best = job_radar.find_best_match("finance", _kb())
    assert best is not None and best["industry"] == "Finance"


def test_find_best_match_empty_inputs():
    assert job_radar.find_best_match("", _kb()) == (0.0, None)
    assert job_radar.find_best_match("anything", []) == (0.0, None)


# --------------------------------------------------------------------------- #
# get_transition_details (BUG-1 regression)
# --------------------------------------------------------------------------- #

def test_get_transition_details_accepts_string_targets():
    jobs = [
        {"id": "role_a", "title": "Role A", "transition_targets": ["role_b", "missing"]},
        {"id": "role_b", "title": "Role B", "description": "Target", "industry": "Tech",
         "category": "emerging", "required_skills": ["Python"]},
    ]
    details = job_radar.get_transition_details("role_a", jobs)
    assert len(details) == 1
    assert details[0]["id"] == "role_b"


def test_transition_none_numerics_coerced_safe():
    """BUG-1: bare-string targets must yield UI-safe numeric defaults, not None."""
    jobs = [
        {"id": "a", "title": "A", "transition_targets": ["b"]},
        {"id": "b", "title": "B", "industry": "Tech", "category": "emerging",
         "description": "d", "required_skills": ["x"]},
    ]
    tr = job_radar.get_transition_details("a", jobs)[0]
    assert tr["salary_delta"] == 0.0
    assert tr["retrain_months"] == 0
    # The UI performs these operations — they must not raise.
    _ = "#55ff55" if tr["salary_delta"] > 0 else "#ff5555"
    _ = f"{tr['salary_delta'] * 100:+.0f}%"
    _ = f"{tr['retrain_months']} months"


def test_transition_unknown_job_returns_empty():
    assert job_radar.get_transition_details("nope", _mini_jobs()) == []


def test_normalize_transition_targets_skips_invalid_entries():
    out = job_radar._normalize_transition_targets([
        "fin_risk_manager",
        {"target_id": "tech_ai_infra_eng", "skill_bridge": "bridge"},
        42, None,
    ])
    assert [o["target_id"] for o in out] == ["fin_risk_manager", "tech_ai_infra_eng"]


# --------------------------------------------------------------------------- #
# compute_timeline
# --------------------------------------------------------------------------- #

def test_timeline_only_emerging_with_year():
    jobs = _mini_jobs()
    tl = job_radar.compute_timeline(jobs, 10.0)
    assert len(tl) == 1 and tl[0]["id"] == "role_b"
    # baseline diffusion 10 → no shift
    assert tl[0]["projected_emergence_year"] == 2030


def test_timeline_diffusion_scaling():
    jobs = _mini_jobs()
    fast = job_radar.compute_timeline(jobs, 5.0)[0]["projected_emergence_year"]
    slow = job_radar.compute_timeline(jobs, 20.0)[0]["projected_emergence_year"]
    assert fast < 2030 < slow


def test_timeline_never_before_current_year():
    jobs = [{"id": "p", "title": "P", "category": "emerging", "emergence_year": 2020}]
    tl = job_radar.compute_timeline(jobs, 10.0)
    assert tl[0]["projected_emergence_year"] >= 2026


# --------------------------------------------------------------------------- #
# KB integrity (data contract used by render)
# --------------------------------------------------------------------------- #

def test_kb_required_fields_present():
    required = ["id", "title", "industry", "category", "description",
                "required_skills", "displacement_risk", "base_demand_trend"]
    for j in _kb():
        for field in required:
            assert field in j, f"{j.get('id')} missing {field}"


def test_kb_ids_unique():
    ids = [j["id"] for j in _kb()]
    assert len(ids) == len(set(ids))


def test_kb_categories_valid():
    valid = {"at_risk", "transforming", "emerging"}
    for j in _kb():
        assert j["category"] in valid, f"{j['id']} bad category {j['category']}"


def test_kb_transition_targets_resolve():
    kb = _kb()
    ids = {j["id"] for j in kb}
    for j in kb:
        for raw in j.get("transition_targets", []):
            norm = job_radar._normalize_transition_target(raw)
            assert norm is not None
            assert norm["target_id"] in ids, f"{j['id']} -> missing {norm['target_id']}"
