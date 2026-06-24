"""Test suite for Job Forecast Radar — pure logic + regression coverage."""
from __future__ import annotations

import math

import evolution as ev
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
        assert j["combined_similarity"] == 0.0
        assert j["hybrid_score"] == round(0.6 * j["impact_score"], 3)


def test_hybrid_query_adds_similarity():
    jobs = job_radar.compute_impact_scores(_kb(), {})
    out = job_radar.get_hybrid_scores(jobs, "machine learning engineer", 0.6, 0.4)
    assert all("semantic_similarity" in j for j in out)
    assert all("combined_similarity" in j for j in out)
    assert any(j["combined_similarity"] > 0 for j in out)


# --------------------------------------------------------------------------- #
# find_best_match (relevance regressions)
# --------------------------------------------------------------------------- #

def test_core_hot_roles_match_kb():
    """Popular roles must resolve to curated KB entries, not LLM fallback."""
    job_radar.assert_core_hot_role_coverage(_kb())


def test_software_product_manager_strong_match():
    sim, best = job_radar.find_best_match("software product manager", _kb())
    assert best is not None
    assert best["id"] == "tech_product_manager"
    assert sim >= job_radar.resolve_search_config()["tier_weak"]


def test_software_developer_matches_engineer():
    sim, best = job_radar.find_best_match("software developer", _kb())
    assert best is not None
    assert best["id"] == "tech_software_eng"
    assert sim >= job_radar.resolve_search_config()["tier_weak"]


def test_normalize_search_query_aliases():
    assert job_radar.normalize_search_query("software developer") == "software engineer"
    assert job_radar.normalize_search_query("Software Developer") == "software engineer"


def test_finance_query_matches_finance_industry():
    _, best = job_radar.find_best_match("finance", _kb())
    assert best is not None and best["industry"] == "Finance"
    assert not job_radar.is_ai_role(best)


def test_finance_process_improvement_below_confidence_threshold():
    sim, best = job_radar.find_best_match("finance process improvement", _kb())
    assert sim < job_radar._SIMILARITY_THRESHOLD
    if best is not None:
        assert best["title"] != "Algorithmic AI Trading Specialist"


def test_finance_process_improvement_not_sorted_by_ai_trading_impact():
    import evolution as ev
    jobs = job_radar.compute_impact_scores(_kb(), dict(ev.CURRENT_AI_SCENARIO))
    hybrid = job_radar.get_hybrid_scores(jobs, "finance process improvement", 0.6, 0.4)
    top = max(hybrid, key=lambda j: j.get("hybrid_score", 0))
    assert top["title"] != "Algorithmic AI Trading Specialist"


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


def test_transition_includes_reasoning_signals():
    jobs = _mini_jobs()
    tr = job_radar.get_transition_details("role_a", jobs)[0]
    assert "is_ai" in tr and "skill_overlap" in tr
    assert tr["current_displacement_risk"] == 0.8
    assert tr["target_displacement_risk"] == 0.2
    assert tr["skill_overlap"] == 0  # Role A {Python,SQL} vs Role B {ML}


def test_is_ai_role():
    assert job_radar.is_ai_role({"title": "AI Infrastructure Architect"})
    assert job_radar.is_ai_role({"title": "Autonomous Fleet Coordinator"})
    assert not job_radar.is_ai_role({"title": "Mixed Arable Farmer"})
    assert not job_radar.is_ai_role({"title": "Palliative & Hospice Care Nurse"})


def test_compute_transition_paths_basic_contract():
    kb = _kb()
    cur = next(j for j in kb if j["id"] == "fin_credit_analyst")
    paths = job_radar.compute_transition_paths(cur, kb, dict(ev.CURRENT_AI_SCENARIO), top_k=3)
    assert len(paths) == 3
    # excludes self and at_risk targets
    assert all(p["id"] != cur["id"] for p in paths)
    assert all(p["category"] != "at_risk" for p in paths)
    # sorted by transition_score desc
    scores = [p["transition_score"] for p in paths]
    assert scores == sorted(scores, reverse=True)


def test_compute_transition_paths_derived_fields_sane():
    kb = _kb()
    cur = next(j for j in kb if j["id"] == "fin_credit_analyst")
    for p in job_radar.compute_transition_paths(cur, kb, dict(ev.CURRENT_AI_SCENARIO)):
        assert 0.0 <= p["skill_distance"] <= 1.0
        assert 0.0 <= p["skill_proximity"] <= 1.0
        assert 3 <= p["retrain_months"] <= 24
        assert isinstance(p["skill_bridge_skills"], list)
        assert p["current_displacement_risk"] == cur["displacement_risk"]


def test_compute_transition_paths_scenario_sensitive():
    """Genuine model derivation: demand_outlook responds to the scenario."""
    kb = _kb()
    cur = next(j for j in kb if j["id"] == "fin_credit_analyst")
    base = job_radar.compute_transition_paths(cur, kb, {"diffusion_years": 5.0})
    agi = job_radar.compute_transition_paths(
        cur, kb, {"augmentation_ratio": 0.9, "task_frontier_open": 1.0, "diffusion_years": 3.0},
    )
    base_d = {p["id"]: p["demand_outlook"] for p in base}
    agi_d = {p["id"]: p["demand_outlook"] for p in agi}
    shared = set(base_d) & set(agi_d)
    assert shared and any(base_d[i] != agi_d[i] for i in shared)


def test_skill_distance_self_is_zero():
    job = {"skill_vector": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]}
    assert job_radar._skill_distance(job, job) == 0.0


def test_kb_not_ai_dominated():
    """Guardrail: the opportunity set must not be overwhelmingly AI-native."""
    kb = _kb()
    emerging = [j for j in kb if j["category"] == "emerging"]
    ai = [j for j in emerging if job_radar.is_ai_role(j)]
    assert len(ai) / len(emerging) < 0.7, "emerging roles skew too AI-heavy"


# --------------------------------------------------------------------------- #
# LLM profile cache (token-saving)
# --------------------------------------------------------------------------- #

def test_query_signature_order_independent():
    sig = job_radar._query_signature
    assert sig("Data Scientist") == sig("scientist, data!")
    assert sig("Senior Project Manager") == sig("manager project senior")
    assert sig("") == ""


def test_llm_cache_round_trip(tmp_path, monkeypatch):
    cache_file = str(tmp_path / "llm_cache.json")
    monkeypatch.setattr(job_radar, "_LLM_CACHE_PATH", cache_file)
    assert job_radar.get_cached_job_profile("quantum chef") is None
    cache = {job_radar._query_signature("quantum chef"): {"id": "qc", "title": "Quantum Chef"}}
    job_radar._save_llm_cache(cache)
    hit = job_radar.get_cached_job_profile("Chef, Quantum")  # different order/case
    assert hit is not None and hit["id"] == "qc"


def test_generate_uses_cache_and_skips_llm(tmp_path, monkeypatch):
    cache_file = str(tmp_path / "llm_cache.json")
    monkeypatch.setattr(job_radar, "_LLM_CACHE_PATH", cache_file)
    monkeypatch.setattr(job_radar, "_append_to_kb", lambda *a, **k: None)

    profile = {"id": "astro_farmer", "title": "Astro Farmer", "industry": "Agriculture",
               "category": "emerging", "description": "d", "sensitivity": {},
               "displacement_risk": 0.2, "required_skills": ["x"]}
    job_radar._save_llm_cache({job_radar._query_signature("astro farmer"): profile})

    # If the LLM were called, this would raise — proving zero-token cache hit.
    import forecast
    monkeypatch.setattr(forecast, "call_llm",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    out = job_radar.generate_job_profile_via_llm("Astro Farmer")
    assert out is not None and out["id"] == "astro_farmer"
    assert out.get("_from_cache") is True


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


# --------------------------------------------------------------------------- #
# Phase 8 — search config, tiers, personalization (HR-3 / HR-12 / HR-13)
# --------------------------------------------------------------------------- #

def test_search_match_tier_from_config():
    cfg = {"tier_no_match": 0.42, "tier_strong": 0.65}
    assert job_radar.search_match_tier(0.30, cfg) == "none"
    assert job_radar.search_match_tier(0.50, cfg) == "weak"
    assert job_radar.search_match_tier(0.70, cfg) == "strong"


def test_resolve_search_config_merges_yaml_shape():
    cfg = job_radar.resolve_search_config({
        "search": {"tier_strong": 0.68, "embed_weight": 0.5},
    })
    assert cfg["tier_strong"] == 0.68
    assert cfg["embed_weight"] == 0.5
    assert cfg["tier_no_match"] == 0.42


def test_personalization_weights_sum_to_one():
    w = job_radar.personalization_weights(experience_level="junior")
    assert abs(sum(w.values()) - 1.0) < 0.01
    w2 = job_radar.personalization_weights(experience_level="senior")
    assert abs(sum(w2.values()) - 1.0) < 0.01


def test_transition_paths_respect_retrain_cap():
    kb = _kb()
    cur = next(j for j in kb if j["id"] == "fin_credit_analyst")
    paths = job_radar.compute_transition_paths(
        cur,
        kb,
        dict(ev.CURRENT_AI_SCENARIO),
        top_k=10,
        experience_level="junior",
        max_retrain_months=6,
        job_radar_cfg={"personalization": {"junior_retrain_cap_months": 6}},
    )
    assert paths
    assert all(p["retrain_months"] <= 6 for p in paths)


def test_rank_jobs_by_transition_score_orders_by_fit():
    kb = _kb()
    anchor = next(j for j in kb if j["id"] == "fin_credit_analyst")
    pool = [j for j in kb if j["category"] in ("emerging", "transforming")][:20]
    ranked = job_radar.rank_jobs_by_transition_score(anchor, pool, dict(ev.CURRENT_AI_SCENARIO))
    scores = [j["transition_score"] for j in ranked]
    assert scores == sorted(scores, reverse=True)


def test_empirical_metrics_stratified_by_experience(tmp_path, monkeypatch):
    from schemas import JobFeedback, make_engine
    from sqlmodel import Session

    eng = make_engine(tmp_path / "fb.db")
    monkeypatch.setattr("schemas.engine", eng)

    with Session(eng) as session:
        for _ in range(5):
            session.add(JobFeedback(
                job_title="Role A", industry="Tech", status="employed",
                confidence=0.8, experience_level="junior",
            ))
        for _ in range(3):
            session.add(JobFeedback(
                job_title="Role A", industry="Tech", status="unemployed",
                confidence=0.5, experience_level="senior",
            ))
        session.commit()

    all_metrics = job_radar.get_empirical_metrics()
    assert all_metrics["Role A"]["total_responses"] == 8

    junior_metrics = job_radar.get_empirical_metrics("junior")
    assert junior_metrics["Role A"]["total_responses"] == 5
    assert junior_metrics["Role A"]["stratified"] is True

    senior_metrics = job_radar.get_empirical_metrics("senior")
    assert senior_metrics["Role A"]["total_responses"] == 8
    assert senior_metrics["Role A"]["stratified"] is False
