"""Discover candidate job-search queries from core guards, seeds, and feedback."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import job_radar


@dataclass(frozen=True)
class DiscoveredQuery:
    query: str
    source: str
    expected_id: str | None = None


def _variant_queries(query: str) -> list[str]:
    """Generate cheap orthographic variants for audit coverage."""
    base = query.strip()
    if not base:
        return []
    variants = {base, base.lower(), base.title()}
    if base.islower():
        variants.add(base.upper())
    return sorted(variants)


def discover_from_core() -> list[DiscoveredQuery]:
    out: list[DiscoveredQuery] = []
    for query, expected_id in job_radar.CORE_HOT_ROLE_QUERIES:
        out.append(DiscoveredQuery(query, "core_hot", expected_id))
    return out


def discover_from_seed(seed_path: str | Path) -> list[DiscoveredQuery]:
    path = Path(seed_path)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[DiscoveredQuery] = []
    for row in raw:
        if isinstance(row, str):
            out.append(DiscoveredQuery(row, "seed"))
            continue
        if not isinstance(row, dict) or not row.get("query"):
            continue
        out.append(DiscoveredQuery(
            str(row["query"]),
            str(row.get("source", "seed")),
            row.get("expected_id"),
        ))
    return out


def discover_from_feedback(*, min_count: int = 1) -> list[DiscoveredQuery]:
    """Titles users submitted in JobFeedback (offline-safe: returns [] if DB empty)."""
    try:
        metrics = job_radar.get_empirical_metrics()
    except Exception:
        return []
    out: list[DiscoveredQuery] = []
    for title, m in metrics.items():
        if int(m.get("total_responses", 0)) >= min_count and title.strip():
            out.append(DiscoveredQuery(title.strip(), "feedback"))
    return out


def discover_queries(cfg: dict[str, Any]) -> list[DiscoveredQuery]:
    """Merge and dedupe discovery sources per config."""
    agent_cfg = cfg.get("job_query_agent", {})
    discover_cfg = agent_cfg.get("discover", {})
    seen: set[str] = set()
    merged: list[DiscoveredQuery] = []

    def _add(items: list[DiscoveredQuery]) -> None:
        for item in items:
            key = item.query.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)

    if discover_cfg.get("include_core", True):
        _add(discover_from_core())
    seed_path = discover_cfg.get("seed_path", "data/query_seed.json")
    if discover_cfg.get("include_seed", True):
        _add(discover_from_seed(seed_path))
    if discover_cfg.get("include_feedback_titles", True):
        _add(discover_from_feedback(
            min_count=int(discover_cfg.get("feedback_min_responses", 1)),
        ))
    if discover_cfg.get("include_variants", True):
        base = list(merged)
        for item in base:
            for variant in _variant_queries(item.query):
                if variant.lower() != item.query.lower():
                    _add([DiscoveredQuery(variant, "variant", item.expected_id)])

    max_q = int(discover_cfg.get("max_queries_per_run", 200))
    return merged[:max_q]
