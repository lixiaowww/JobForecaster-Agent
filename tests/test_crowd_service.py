"""Offline tests for crowd contribution service (Phase 2, HR-1)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, delete

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry import Registry
from schemas import Contribution, CrowdSnapshot, Prediction, Status, engine
from services.crowd_service import (
    get_blind_contribution_target,
    get_crowd_result,
    process_open_prediction_crowds,
    resolve_contributions_for_prediction,
    submit_contribution,
)


def _clean():
    with Session(engine) as session:
        session.exec(delete(Contribution))
        session.exec(delete(CrowdSnapshot))
        session.exec(delete(Prediction))
        session.commit()


def _open_prediction(statement: str = "AI capex exceeds $500B in 2027") -> Prediction:
    p = Prediction(
        statement=statement,
        rationale="Agent prior rationale because demand compounds therefore spending rises.",
        confidence=0.72,
        horizon="2027-Q4",
        resolution_date=date.today() + timedelta(days=180),
        resolution_criteria="Official hyperscaler filings.",
        category="capital",
    ).assign_id()
    Registry().add_many([p])
    return p


def test_blind_target_hides_agent_prior():
    _clean()
    p = _open_prediction()
    blind = get_blind_contribution_target(p.id)
    assert blind["statement"] == p.statement
    assert "confidence" not in blind
    assert "rationale" not in blind
    assert "aggregate" not in blind
    _clean()


def test_submit_and_gate_offline():
    _clean()
    p = _open_prediction()
    cfg = {"crowd": {"offline_judge": True, "tau_soundness": 0.5, "tau_novelty": 0.25, "k": 3}}
    result = submit_contribution(
        p.id,
        "user_a",
        0.35,
        argument=(
            "However, grid bottlenecks will cap deployments because interconnection "
            "queues mean buildout lags budgets, so realized spending falls short."
        ),
        evidence_urls=["https://example.com/grid"],
        cfg=cfg,
    )
    assert result["contribution_id"]
    assert "aggregate_probability" not in result
    assert "your_decision" in result
    crowd = get_crowd_result(p.id, "user_a")
    assert "aggregate_probability" in crowd
    _clean()


def test_crowd_hidden_before_contribute():
    _clean()
    p = _open_prediction()
    with pytest.raises(PermissionError):
        get_crowd_result(p.id, "stranger")
    _clean()


def test_duplicate_contributor_rejected():
    _clean()
    p = _open_prediction()
    args = dict(
        target_id=p.id,
        contributor_id="dup_user",
        probability=0.4,
        argument="Because supply constraints persist therefore spending slows however demand remains.",
        evidence_urls=["https://example.com/a"],
        cfg={"crowd": {"offline_judge": True}},
    )
    submit_contribution(**args)
    with pytest.raises(ValueError, match="already submitted"):
        submit_contribution(**args)
    _clean()


def test_process_open_crowds_in_loop():
    _clean()
    p = _open_prediction()
    submit_contribution(
        p.id,
        "loop_user",
        0.4,
        argument="Because energy limits apply however budgets are announced therefore lag occurs.",
        evidence_urls=["https://example.com/e"],
        cfg={"crowd": {"offline_judge": True}},
    )
    n = process_open_prediction_crowds({"crowd": {"offline_judge": True}}, Registry())
    assert n >= 1
    _clean()


def test_resolve_contributions_brier():
    _clean()
    p = _open_prediction()
    submit_contribution(
        p.id,
        "scorer",
        0.8,
        argument="Because trends continue therefore threshold is met however risks remain since data shows growth.",
        evidence_urls=["https://example.com/b"],
        cfg={"crowd": {"offline_judge": True}},
    )
    n = resolve_contributions_for_prediction(p.id, True)
    assert n == 1
    _clean()
