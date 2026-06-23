"""Crowd contribution service — anti-anchoring submit flow + gate processing (Phase 2).

Submit path never exposes agent confidence/rationale or crowd aggregate before
the contributor has posted their own forecast.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from crowd import (
    Contribution,
    ContributionStore,
    CrowdGate,
    GateConfig,
    GateResult,
    HashingEmbedder,
    HeuristicSoundnessJudge,
    LLMSoundnessJudge,
    log_trace,
)
from registry import Registry
from schemas import CrowdSnapshot, Prediction, Status, engine
from services.config_loader import load_config
from sqlmodel import Session, select


def _gate_config(cfg: dict) -> GateConfig:
    c = cfg.get("crowd", {})
    return GateConfig(
        tau_soundness=float(c.get("tau_soundness", 0.55)),
        tau_novelty=float(c.get("tau_novelty", 0.35)),
        k=int(c.get("k", 3)),
        alpha=float(c.get("alpha", 0.4)),
        skill_floor=float(c.get("skill_floor", 0.25)),
        extremize=float(c.get("extremize", 1.0)),
        prior_weight=float(c.get("prior_weight", 1.0)),
    )


def build_crowd_gate(cfg: dict, store: ContributionStore) -> CrowdGate:
    """Construct gate with offline judge by default (HR-1)."""
    crowd_cfg = cfg.get("crowd", {})
    offline = crowd_cfg.get("offline_judge", True)
    judge = HeuristicSoundnessJudge() if offline else LLMSoundnessJudge(
        model=cfg.get("model")
    )
    return CrowdGate(
        HashingEmbedder(),
        judge,
        skill_fn=store.skill_fn(),
        cfg=_gate_config(cfg),
    )


def _require_open_prediction(pred: Prediction | None) -> Prediction:
    if pred is None:
        raise ValueError("prediction not found")
    if pred.status not in (Status.open, Status.due):
        raise ValueError("prediction is not open for contributions")
    return pred


def get_blind_contribution_target(target_id: str) -> dict[str, Any]:
    """Anti-anchoring: statement + resolution criteria only — no agent prior."""
    pred = _require_open_prediction(Registry().get(target_id))
    return {
        "id": pred.id,
        "statement": pred.statement,
        "category": pred.category,
        "horizon": pred.horizon,
        "resolution_date": pred.resolution_date.isoformat(),
        "resolution_criteria": pred.resolution_criteria,
        "instructions": (
            "Submit your probability, argument, and at least one evidence URL "
            "before requesting the crowd aggregate."
        ),
    }


def _contribution_id(target_id: str, contributor_id: str) -> str:
    raw = f"{target_id}|{contributor_id}|{datetime.now(timezone.utc).isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _decision_for_contributor(result: GateResult, contribution_id: str) -> dict[str, Any]:
    for d in result.decisions:
        if d.contribution_id == contribution_id:
            return {
                "admitted": d.admitted,
                "reason": d.reason,
                "soundness": d.soundness,
                "novelty": d.novelty,
                "weight": d.weight,
            }
    return {"admitted": False, "reason": "not_processed", "soundness": None, "novelty": None, "weight": 0.0}


def _save_snapshot(result: GateResult) -> None:
    snap = CrowdSnapshot(
        target_id=result.target_id,
        prior_probability=result.prior_probability,
        aggregate_probability=result.aggregate_probability,
        selected_contribution_ids=result.selected,
        updated_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        session.merge(snap)
        session.commit()


def run_gate_for_prediction(pred: Prediction, cfg: dict, store: ContributionStore | None = None) -> GateResult | None:
    store = store or ContributionStore()
    contribs = store.list_for_target(pred.id)
    if not contribs:
        return None
    gate = build_crowd_gate(cfg, store)
    result = gate.process(
        pred.statement,
        pred.id,
        pred.confidence,
        pred.rationale,
        contribs,
    )
    _save_snapshot(result)
    trace_path = cfg.get("crowd", {}).get("trace_path", "data/crowd_traces.jsonl")
    log_trace(result, trace_path)
    return result


def process_open_prediction_crowds(cfg: dict, reg: Registry | None = None) -> int:
    """Run crowd gate on every open prediction that has contributions."""
    reg = reg or Registry()
    store = ContributionStore()
    processed = 0
    for target_id in store.target_ids_with_contributions():
        pred = reg.get(target_id)
        if pred is None or pred.status not in (Status.open, Status.due):
            continue
        if run_gate_for_prediction(pred, cfg, store) is not None:
            processed += 1
    return processed


def submit_contribution(
    target_id: str,
    contributor_id: str,
    probability: float,
    argument: str,
    evidence_urls: list[str],
    *,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Record contribution and run gate; response hides aggregate (anti-anchoring)."""
    cfg = cfg or load_config()
    pred = _require_open_prediction(Registry().get(target_id))
    store = ContributionStore()

    if store.get_by_contributor(target_id, contributor_id):
        raise ValueError("contributor already submitted for this prediction")

    if not evidence_urls:
        raise ValueError("at least one evidence URL is required")

    probability = max(0.01, min(0.99, float(probability)))
    cid = _contribution_id(target_id, contributor_id)
    contrib = Contribution(
        id=cid,
        target_id=target_id,
        contributor_id=contributor_id,
        probability=probability,
        argument=argument.strip(),
        evidence_urls=[u.strip() for u in evidence_urls if u.strip()],
    )
    if not contrib.evidence_urls:
        raise ValueError("at least one evidence URL is required")

    store.add(contrib)
    result = run_gate_for_prediction(pred, cfg, store)
    if result is None:
        raise RuntimeError("gate failed after submission")

    return {
        "contribution_id": cid,
        "target_id": target_id,
        "status": "received",
        "your_decision": _decision_for_contributor(result, cid),
        "message": (
            "Submission recorded. Request GET /v1/predictions/{id}/crowd with your "
            "contributor_id to see the crowd aggregate."
        ),
        "disclaimer": "Crowd forecasts are speculative and not investment advice.",
    }


def get_crowd_result(target_id: str, contributor_id: str) -> dict[str, Any]:
    """Return aggregate only if contributor_id has already submitted."""
    store = ContributionStore()
    if store.get_by_contributor(target_id, contributor_id) is None:
        raise PermissionError(
            "crowd aggregate is available only after you have submitted a contribution"
        )

    with Session(engine) as session:
        snap = session.get(CrowdSnapshot, target_id)

    if snap is None:
        pred = Registry().get(target_id)
        if pred is None:
            raise ValueError("prediction not found")
        result = run_gate_for_prediction(pred, load_config(), store)
        if result is None:
            raise ValueError("no crowd data for this prediction")
        snap = CrowdSnapshot(
            target_id=result.target_id,
            prior_probability=result.prior_probability,
            aggregate_probability=result.aggregate_probability,
            selected_contribution_ids=result.selected,
            updated_at=datetime.now(timezone.utc),
        )

    return {
        "target_id": target_id,
        "aggregate_probability": snap.aggregate_probability,
        "selected_contribution_count": len(snap.selected_contribution_ids),
        "updated_at": snap.updated_at.isoformat() if snap.updated_at else None,
        "disclaimer": (
            "Aggregate is a weighted blend of admitted contributions and the agent prior. "
            "Not financial advice."
        ),
    }


def resolve_contributions_for_prediction(target_id: str, outcome: bool) -> int:
    return ContributionStore().resolve_target(target_id, outcome)
