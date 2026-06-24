"""Tests for job query calibration agent (Phase 9, HR-1 offline)."""
from __future__ import annotations

import json
from pathlib import Path

import job_radar
import pytest
from services.job_query_agent.audit import run_audit
from services.job_query_agent.discover import DiscoveredQuery, discover_from_core, discover_queries
from services.job_query_agent.evaluate import evaluate_query
from services.job_query_agent.propose import propose_from_verdict


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
