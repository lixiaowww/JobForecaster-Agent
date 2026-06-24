"""Pure evaluation of a single job-search query against the KB (HR-2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import job_radar


@dataclass(frozen=True)
class QueryVerdict:
    query: str
    source: str
    expected_id: str | None
    best_id: str | None
    best_title: str | None
    sim: float
    tier: str
    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def is_regression(self) -> bool:
        return self.status == "p0_regression"


def _core_expected_map() -> dict[str, str]:
    return {q: eid for q, eid in job_radar.CORE_HOT_ROLE_QUERIES}


def evaluate_query(
    discovered,
    jobs: list[dict],
    *,
    job_radar_cfg: dict[str, Any] | None = None,
) -> QueryVerdict:
    """Score one query and classify the retrieval outcome."""
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    tier_no = float(search_cfg["tier_no_match"])
    tier_weak = float(search_cfg["tier_weak"])

    sim, best = job_radar.find_best_match(
        discovered.query, jobs, search_cfg=search_cfg,
    )
    tier = job_radar.search_match_tier(sim, search_cfg)
    best_id = best.get("id") if best else None
    best_title = best.get("title") if best else None
    expected = discovered.expected_id or _core_expected_map().get(discovered.query)

    if expected:
        if best_id != expected:
            return QueryVerdict(
                discovered.query, discovered.source, expected, best_id, best_title,
                sim, tier, "p0_regression",
                f"expected {expected}, got {best_id} (sim={sim:.3f})",
            )
        if sim < tier_weak:
            return QueryVerdict(
                discovered.query, discovered.source, expected, best_id, best_title,
                sim, tier, "weak_core",
                f"correct id but sim {sim:.3f} < tier_weak {tier_weak}",
            )
        return QueryVerdict(
            discovered.query, discovered.source, expected, best_id, best_title,
            sim, tier, "ok", "core guard satisfied",
        )

    if tier == "none" or sim < tier_no:
        return QueryVerdict(
            discovered.query, discovered.source, None, best_id, best_title,
            sim, tier, "kb_gap",
            f"no confident KB match (sim={sim:.3f})",
        )

    if tier == "weak":
        return QueryVerdict(
            discovered.query, discovered.source, None, best_id, best_title,
            sim, tier, "weak_match",
            f"weak match to {best_title!r}",
        )

    return QueryVerdict(
        discovered.query, discovered.source, None, best_id, best_title,
        sim, tier, "ok", f"strong match to {best_title!r}",
    )
