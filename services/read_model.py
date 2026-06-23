"""Read-only service layer — shared by CLI, dashboard, and future MCP/API.

All functions here are side-effect free except SQLite reads. Nondeterministic
components (embeddings) accept injectable stubs for offline use (HR-1).
"""
from __future__ import annotations

from typing import Any, Optional

try:
    import evolution as ev
    import job_radar
    from registry import Registry
except ImportError:
    import evolution as ev
    import job_radar
    from registry import Registry


def get_scoreboard() -> dict:
    return Registry().scoreboard()


def get_ood_assessment(scenario: Optional[dict] = None, *, n_bootstrap: int = 50) -> dict:
    """Return OOD metrics and nearest historical regime for a scenario vector."""
    prior = ev.build_prior(
        current_scenario=scenario or ev.CURRENT_AI_SCENARIO,
        n_bootstrap=n_bootstrap,
    )
    ood = prior.current_scenario_ood
    nc = prior.nearest_cluster
    return {
        "is_ood": ood["is_ood"],
        "min_mahalanobis": ood["min_mahalanobis"],
        "threshold": ood["threshold"],
        "nearest_regime": nc.name,
        "mean_job_multiplier": nc.mean_multiplier,
        "mean_lag_years": nc.mean_lag_years,
        "bootstrap_stability": prior.bootstrap_stability,
        "conditional_rules": prior.conditional_rules,
        "prompt_context": prior.to_prompt_context(),
    }


def search_jobs(
    query: str = "",
    industry: str = "All",
    scenario_params: Optional[dict] = None,
    *,
    alpha: float = 0.6,
    beta: float = 0.4,
    kb_path: str = "data/jobs_kb.json",
    embedder=None,
) -> list[dict]:
    """Hybrid RAG job search ranked by impact + semantic similarity."""
    jobs = job_radar.load_knowledge_base(kb_path)
    scenario = scenario_params or ev.CURRENT_AI_SCENARIO
    scored = job_radar.compute_impact_scores(jobs, scenario)
    filtered = job_radar.filter_by_industry(scored, industry)
    return job_radar.get_hybrid_scores(filtered, query, alpha, beta, embedder=embedder)


def list_open_predictions() -> list[dict]:
    reg = Registry()
    return [p.model_dump(mode="json") for p in reg.open_predictions()]
