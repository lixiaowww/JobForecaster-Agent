"""Tests for job query calibration agent (Phase 9, HR-1 offline)."""
from __future__ import annotations

import json
from pathlib import Path

import job_radar
import pytest
from services.job_query_agent.audit import run_audit
from services.job_query_agent.apply import (
    apply_alias_patch_file,
    apply_kb_profile_new,
    can_auto_apply,
    run_apply_pending,
    try_auto_apply_proposal,
)
from services.job_query_agent.discover import (
    DiscoveredQuery,
    discover_from_core,
    discover_from_search_log,
    discover_queries,
)
from services.job_query_agent.evaluate import evaluate_query
from services.job_query_agent.loop import run_calibration_cycle
from services.job_query_agent.propose import CalibrationProposal, propose_from_verdict, queue_proposal
from services.job_query_agent.search_log import merge_search_logs, record_search_log
from services.job_query_agent.simulate import simulate_alias_patch, simulate_kb_profile_new


@pytest.fixture
def cfg():
    return {
        "job_radar": {"kb_path": "data/jobs_kb.json"},
        "job_query_agent": {
            "traces_path": "data/query_agent_traces_test.jsonl",
            "discover": {
                "include_core": True,
                "include_seed": False,
                "include_feedback_titles": False,
                "include_variants": False,
            },
            "evaluate": {"fail_on_weak_core": True},
        },
    }


def test_discover_from_core_includes_product_manager():
    queries = {d.query for d in discover_from_core()}
    assert "software developer" in queries
    assert "产品经理" in queries


def test_evaluate_core_query_ok():
    jobs = job_radar.load_knowledge_base()
    item = DiscoveredQuery("software developer", "core_hot", "tech_software_eng")
    verdict = evaluate_query(item, jobs)
    assert verdict.ok
    assert verdict.best_id == "tech_software_eng"


def test_evaluate_regression_detected():
    jobs = job_radar.load_knowledge_base()
    item = DiscoveredQuery("software developer", "core_hot", "tech_product_manager")
    verdict = evaluate_query(item, jobs)
    assert verdict.is_regression


def test_propose_alias_on_weak_match():
    jobs = job_radar.load_knowledge_base()
    item = DiscoveredQuery("obscure made up title xyz", "seed")
    verdict = evaluate_query(item, jobs)
    proposal = propose_from_verdict(verdict)
    if verdict.status == "kb_gap":
        assert proposal is not None
        assert proposal.type == "kb_profile_new"
    elif verdict.status == "weak_match":
        assert proposal is not None
        assert proposal.type == "alias_patch"


def test_run_audit_passes_on_real_kb(cfg, tmp_path):
    cfg = dict(cfg)
    cfg["job_query_agent"] = {
        **cfg["job_query_agent"],
        "traces_path": str(tmp_path / "traces.jsonl"),
    }
    summary = run_audit(cfg, write_traces=True)
    assert summary["p0_regressions"] == 0
    assert summary["ok"] >= len(job_radar.CORE_HOT_ROLE_QUERIES)
    assert Path(cfg["job_query_agent"]["traces_path"]).is_file()


def test_run_audit_fails_on_regression(cfg, tmp_path):
    cfg = dict(cfg)
    cfg["job_query_agent"]["traces_path"] = str(tmp_path / "traces.jsonl")

    original = job_radar.CORE_HOT_ROLE_QUERIES
    bad = (("software developer", "tech_product_manager"),) + original[1:]
    job_radar.CORE_HOT_ROLE_QUERIES = bad
    try:
        with pytest.raises(AssertionError, match="P0 regression"):
            run_audit(cfg, write_traces=False)
    finally:
        job_radar.CORE_HOT_ROLE_QUERIES = original


def test_discover_queries_respects_max(cfg):
    cfg = dict(cfg)
    cfg["job_query_agent"]["discover"]["max_queries_per_run"] = 3
    items = discover_queries(cfg)
    assert len(items) <= 3


def _mini_eng_job():
    return {
        "id": "tech_software_eng",
        "title": "Software Engineer",
        "industry": "Tech",
        "category": "transforming",
        "description": "Builds and maintains software systems.",
        "required_skills": ["python", "apis"],
        "search_aliases": [],
    }


def test_simulate_alias_patch_improves_match():
    jobs = [_mini_eng_job()]
    proposal = CalibrationProposal(
        proposal_id="alias_swe",
        type="alias_patch",
        query="swe ic",
        target_id="tech_software_eng",
        payload={"add_aliases": ["swe ic"]},
        evidence={},
    )
    sim_before, _ = job_radar.find_best_match("swe ic", jobs)
    sim_after, best_id = simulate_alias_patch(proposal, jobs)
    assert best_id == "tech_software_eng"
    assert sim_after > sim_before


def test_apply_alias_patch_file(tmp_path):
    kb_path = tmp_path / "jobs_kb.json"
    kb_path.write_text(json.dumps([_mini_eng_job()]), encoding="utf-8")
    ok = apply_alias_patch_file(kb_path, "tech_software_eng", ["swe ic"])
    assert ok
    saved = json.loads(kb_path.read_text(encoding="utf-8"))
    assert "swe ic" in saved[0]["search_aliases"]


def test_can_auto_apply_requires_improvement():
    proposal = CalibrationProposal(
        proposal_id="x",
        type="alias_patch",
        query="q",
        target_id="tech_software_eng",
        payload={"add_aliases": ["q"]},
        evidence={},
    )
    agent_cfg = {
        "auto_apply": {"enabled": True, "types": ["alias_patch"], "min_sim_after": 0.55},
        "_job_radar_cfg": {},
    }
    ok, reason = can_auto_apply(
        proposal,
        sim_before=0.6,
        sim_after=0.6,
        best_id_after="tech_software_eng",
        agent_cfg=agent_cfg,
        expected_id="tech_software_eng",
    )
    assert not ok
    assert "improvement" in reason


def test_run_calibration_cycle_dry_run(cfg, tmp_path):
    cfg = dict(cfg)
    cfg["_config_path"] = str(tmp_path / "config.yaml")
    cfg["job_query_agent"] = {
        **cfg["job_query_agent"],
        "traces_path": str(tmp_path / "traces.jsonl"),
        "auto_apply": {"enabled": True, "max_rounds": 1},
    }
    summary = run_calibration_cycle(cfg, write_traces=False, dry_run=True)
    assert summary["final"]["p0_regressions"] == 0
    assert summary["auto_applied"] == 0


def test_try_auto_apply_on_real_weak_alias(tmp_path):
    """End-to-end: alias patch that clears a weak-core verdict."""
    kb_path = tmp_path / "jobs_kb.json"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("job_radar:\n  search:\n    tier_weak: 0.55\n", encoding="utf-8")
    job = _mini_eng_job()
    kb_path.write_text(json.dumps([job]), encoding="utf-8")
    jobs = json.loads(kb_path.read_text(encoding="utf-8"))
    query = "swe ic"
    item = DiscoveredQuery(query, "seed")
    verdict = evaluate_query(item, jobs)
    proposal = propose_from_verdict(verdict, {job["id"]: job})
    if proposal is None or proposal.type != "alias_patch":
        pytest.skip("query already matches strongly on this KB")
    action = try_auto_apply_proposal(
        proposal,
        jobs,
        kb_path=kb_path,
        config_path=config_path,
        job_radar_cfg={"search": {"tier_weak": 0.55}},
        agent_cfg={"auto_apply": {"enabled": True, "types": ["alias_patch"], "min_sim_after": 0.55}},
        expected_id=None,
        sim_before=verdict.sim,
    )
    assert action is not None
    if action.get("auto_applied"):
        saved = json.loads(kb_path.read_text(encoding="utf-8"))
        assert query in saved[0]["search_aliases"]


def test_discover_from_search_log_weighted(tmp_path):
    log_path = tmp_path / "search.jsonl"
    for _ in range(4):
        record_search_log("cloud architect", path=log_path, tier="none")
    record_search_log("rare title", path=log_path, tier="weak")
    items = discover_from_search_log(log_path, min_occurrences=2, max_queries=10)
    assert items[0].query == "cloud architect"
    assert items[0].occurrences == 4
    assert items[0].weight == 4.0


def test_merge_search_logs_dedupes(tmp_path):
    dest = tmp_path / "main.jsonl"
    src = tmp_path / "hf_export.jsonl"
    record_search_log("nurse", path=dest, tier="weak")
    record_search_log("nurse", path=src, tier="weak")
    record_search_log("new query", path=src, tier="none")
    merged = merge_search_logs(src, dest)
    assert merged == 2
    rows = dest.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 3


def _cached_kb_profile(query: str) -> dict:
    return {
        "id": "gen_cloud_architect",
        "title": "Cloud Architect",
        "title_zh": "云架构师",
        "industry": "Tech",
        "category": "transforming",
        "description": f"Designs cloud systems. Query: {query}",
        "description_zh": "云架构",
        "sensitivity": {
            "augmentation_ratio": 0.2,
            "demand_elasticity": 0.1,
            "oring_leverage": 0.0,
            "skill_distance": 0.1,
            "diffusion_years": 0.1,
            "absorbing_sector": 0.0,
            "productivity_capture": 0.1,
            "task_frontier_open": 0.2,
        },
        "base_demand_trend": 0.05,
        "displacement_risk": 0.25,
        "required_skills": ["aws", "kubernetes", "networking"],
        "skill_vector": [0.7, 0.6, 0.5, 0.4, 0.5, 0.3, 0.4, 0.5],
        "sources": ["https://www.onetonline.org/link/summary/15-1299.08"],
        "search_aliases": [query, "cloud architect"],
        "transition_targets": [],
    }


def test_simulate_and_apply_kb_profile_from_cache(tmp_path, monkeypatch):
    kb_path = tmp_path / "jobs_kb.json"
    kb_path.write_text(json.dumps([_mini_eng_job()]), encoding="utf-8")
    cache_file = str(tmp_path / "llm_cache.json")
    monkeypatch.setattr(job_radar, "_LLM_CACHE_PATH", cache_file)
    query = "cloud architect"
    profile = _cached_kb_profile(query)
    job_radar._save_llm_cache({job_radar._query_signature(query): profile})

    jobs = json.loads(kb_path.read_text(encoding="utf-8"))
    proposal = CalibrationProposal(
        proposal_id="kb_gap_cloud",
        type="kb_profile_new",
        query=query,
        target_id=None,
        payload={"query": query},
        evidence={},
    )
    sim_after, best_id = simulate_kb_profile_new(proposal, jobs)
    assert sim_after >= job_radar.resolve_search_config()["tier_weak"]
    assert best_id == profile["id"]

    result = apply_kb_profile_new(query, kb_path=kb_path, allow_llm=False)
    assert result["applied"]
    saved = json.loads(kb_path.read_text(encoding="utf-8"))
    assert any(j["id"] == profile["id"] for j in saved)


def test_run_apply_pending_kb_profile(tmp_path, monkeypatch):
    kb_path = tmp_path / "jobs_kb.json"
    kb_path.write_text(json.dumps([_mini_eng_job()]), encoding="utf-8")
    cache_file = str(tmp_path / "llm_cache.json")
    monkeypatch.setattr(job_radar, "_LLM_CACHE_PATH", cache_file)
    query = "cloud architect"
    job_radar._save_llm_cache({
        job_radar._query_signature(query): _cached_kb_profile(query),
    })

    pending = tmp_path / "pending"
    proposal = CalibrationProposal(
        proposal_id="kb_gap_cloud",
        type="kb_profile_new",
        query=query,
        target_id=None,
        payload={"query": query},
        evidence={},
    )
    queue_proposal(proposal, pending)

    cfg = {
        "job_radar": {"kb_path": str(kb_path)},
        "job_query_agent": {
            "review": {"pending_dir": str(pending)},
        },
        "_config_path": str(tmp_path / "config.yaml"),
    }
    summary = run_apply_pending(cfg, dry_run=False)
    assert summary["applied"] == 1
    assert not list(pending.glob("*.json"))
