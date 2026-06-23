"""MCP tool handlers — pure JSON in/out, no MCP runtime dependency (HR-1).

Called by `mcp_server.py` and covered by offline tests in `tests/test_mcp_handlers.py`.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import evolution as ev
from crowd import HashingEmbedder

from services.config_loader import load_config
from services.read_model import (
    get_ood_assessment,
    get_scoreboard,
    list_open_predictions,
    search_jobs,
)

INDUSTRIES = [
    "All", "Agriculture", "Construction", "Education", "Finance", "Government",
    "Healthcare", "Hospitality", "Legal", "Logistics", "Manufacturing", "Media",
    "Retail", "Tech",
]

_SCENARIO_KEYS = tuple(ev.CURRENT_AI_SCENARIO.keys())


def merge_scenario_overrides(overrides: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge optional overrides onto CURRENT_AI_SCENARIO."""
    if not overrides:
        return None
    unknown = set(overrides) - set(_SCENARIO_KEYS)
    if unknown:
        raise ValueError(f"unknown scenario keys: {sorted(unknown)}")
    merged = dict(ev.CURRENT_AI_SCENARIO)
    merged.update(overrides)
    return merged


def parse_scenario_json(scenario_json: Optional[str]) -> Optional[dict[str, Any]]:
    """Merge optional JSON string overrides onto CURRENT_AI_SCENARIO."""
    if not scenario_json or not scenario_json.strip():
        return None
    overrides = json.loads(scenario_json)
    if not isinstance(overrides, dict):
        raise ValueError("scenario_json must be a JSON object")
    return merge_scenario_overrides(overrides)


def _slim_job(job: dict) -> dict:
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "title_zh": job.get("title_zh"),
        "industry": job.get("industry"),
        "category": job.get("category"),
        "impact_score": job.get("impact_score"),
        "hybrid_score": job.get("hybrid_score"),
        "semantic_similarity": job.get("semantic_similarity"),
        "displacement_risk": job.get("displacement_risk"),
    }


def _slim_prediction(pred: dict) -> dict:
    return {
        "id": pred.get("id"),
        "statement": pred.get("statement"),
        "category": pred.get("category"),
        "confidence": pred.get("confidence"),
        "horizon": pred.get("horizon"),
        "resolution_date": pred.get("resolution_date"),
        "status": pred.get("status"),
        "resolution_criteria": pred.get("resolution_criteria"),
    }


def handle_get_calibration_scoreboard() -> dict:
    sb = get_scoreboard()
    sb["disclaimer"] = (
        "Speculative AI-generated forecasts. Not financial or investment advice. "
        "Confidence values are model estimates; verify against primary sources."
    )
    return sb


def handle_get_ood_assessment(
    scenario_json: Optional[str] = None,
    n_bootstrap: Optional[int] = None,
    *,
    scenario: Optional[dict[str, Any]] = None,
) -> dict:
    cfg = load_config()
    merged = merge_scenario_overrides(scenario) if scenario is not None else parse_scenario_json(scenario_json)
    boot = n_bootstrap if n_bootstrap is not None else int(
        cfg.get("evolution", {}).get("n_bootstrap", 50)
    )
    result = get_ood_assessment(merged, n_bootstrap=boot)
    result["disclaimer"] = (
        "OOD signal indicates distance from historical tech transitions (n≈15 cases). "
        "When is_ood is true, widen confidence intervals and avoid precise extrapolation."
    )
    return result


def handle_search_jobs(
    query: str = "",
    industry: str = "All",
    limit: int = 10,
    scenario_json: Optional[str] = None,
    *,
    scenario: Optional[dict[str, Any]] = None,
) -> dict:
    if industry not in INDUSTRIES:
        raise ValueError(f"industry must be one of: {', '.join(INDUSTRIES)}")
    limit = max(1, min(50, limit))
    cfg = load_config()
    jr = cfg.get("job_radar", {})
    merged = merge_scenario_overrides(scenario) if scenario is not None else parse_scenario_json(scenario_json)
    kb_path = jr.get("kb_path", "data/jobs_kb.json")
    if not str(kb_path).startswith("/"):
        from paths import PROJECT_ROOT
        kb_path = str(PROJECT_ROOT / kb_path)

    jobs = search_jobs(
        query=query,
        industry=industry,
        scenario_params=merged,
        alpha=float(jr.get("alpha", 0.6)),
        beta=float(jr.get("beta", 0.4)),
        kb_path=kb_path,
        embedder=HashingEmbedder(),
    )
    ranked = sorted(jobs, key=lambda j: j.get("hybrid_score", 0.0), reverse=True)
    return {
        "query": query,
        "industry": industry,
        "count": len(ranked[:limit]),
        "jobs": [_slim_job(j) for j in ranked[:limit]],
        "disclaimer": (
            "Job impact scores are model estimates grounded in sensitivity weights and "
            "historical transition priors. Not career or employment advice."
        ),
    }


def handle_list_open_predictions(limit: int = 20) -> dict:
    limit = max(1, min(100, limit))
    preds = list_open_predictions()
    preds.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)
    return {
        "count": len(preds[:limit]),
        "predictions": [_slim_prediction(p) for p in preds[:limit]],
        "disclaimer": (
            "Open predictions are speculative LLM outputs pending resolution. "
            "Not financial or economic advice."
        ),
    }
