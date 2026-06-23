"""Dashboard data access via services layer (no Streamlit)."""
from __future__ import annotations

from datetime import date
from typing import Any

import evolution as ev
import job_radar
from registry import Registry
from schemas import Prediction
from services.config_loader import load_config
from services.read_model import get_ood_assessment, get_scoreboard, search_jobs


def get_scoreboard_data() -> dict[str, Any]:
    return get_scoreboard()


def get_predictions() -> list[Prediction]:
    return Registry().load()


def build_evolution_prior(scenario: dict[str, Any], *, n_bootstrap: int | None = None) -> ev.EvolutionPrior:
    cfg = load_config()
    boot = n_bootstrap if n_bootstrap is not None else int(cfg.get("evolution", {}).get("n_bootstrap", 50))
    return ev.build_prior(current_scenario=scenario, n_bootstrap=boot)


def get_ood_for_scenario(scenario: dict[str, Any], *, n_bootstrap: int = 10) -> dict[str, Any]:
    return get_ood_assessment(scenario, n_bootstrap=n_bootstrap)


def hybrid_job_search(
    query: str,
    industry: str,
    scenario: dict[str, Any],
    *,
    limit: int = 50,
) -> list[dict]:
    cfg = load_config()
    jr = cfg.get("job_radar", {})
    kb_path = jr.get("kb_path", "data/jobs_kb.json")
    jobs = search_jobs(
        query=query,
        industry=industry,
        scenario_params=scenario,
        alpha=float(jr.get("alpha", 0.6)),
        beta=float(jr.get("beta", 0.4)),
        kb_path=kb_path,
        embedder=job_radar._default_embedder(),
    )
    jobs.sort(key=lambda j: j.get("hybrid_score", 0.0), reverse=True)
    return jobs[:limit]
