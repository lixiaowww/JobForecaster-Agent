"""Simulate retrieval improvement before applying a calibration proposal."""
from __future__ import annotations

import copy
from typing import Any

import job_radar
from services.job_query_agent.propose import CalibrationProposal


def _with_alias(jobs: list[dict], target_id: str, aliases: list[str]) -> list[dict]:
    out = copy.deepcopy(jobs)
    for j in out:
        if j.get("id") != target_id:
            continue
        existing = list(j.get("search_aliases") or [])
        merged = existing + [a for a in aliases if a not in existing]
        j["search_aliases"] = merged
        break
    return out


def simulate_alias_patch(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    job_radar_cfg: dict[str, Any] | None = None,
) -> tuple[float, str | None]:
    """Return (sim_after, best_id) if aliases were added to target_id."""
    if not proposal.target_id:
        return 0.0, None
    aliases = list(proposal.payload.get("add_aliases") or [])
    if not aliases:
        return 0.0, None
    patched = _with_alias(jobs, proposal.target_id, aliases)
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    sim, best = job_radar.find_best_match(
        proposal.query, patched, search_cfg=search_cfg,
    )
    return sim, best.get("id") if best else None


def simulate_title_alias(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    job_radar_cfg: dict[str, Any] | None = None,
) -> tuple[float, str | None]:
    """Return (sim_after, best_id) when query is mapped to canonical phrase."""
    canonical = proposal.payload.get("canonical")
    if not canonical:
        return 0.0, None
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    merged = dict(search_cfg.get("title_aliases") or {})
    merged[proposal.query.strip().lower()] = canonical
    cfg = {**(job_radar_cfg or {}), "search": {**search_cfg, "title_aliases": merged}}
    search_cfg = job_radar.resolve_search_config(cfg)
    sim, best = job_radar.find_best_match(
        proposal.query, jobs, search_cfg=search_cfg,
    )
    return sim, best.get("id") if best else None


def simulate_kb_profile_new(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    job_radar_cfg: dict[str, Any] | None = None,
) -> tuple[float, str | None]:
    """Simulate retrieval if a cached LLM profile were added to the KB."""
    cached = job_radar.get_cached_job_profile(proposal.query)
    if not cached:
        return 0.0, None
    profile = dict(cached)
    profile.pop("_from_cache", None)
    ids = {j.get("id") for j in jobs}
    pool = list(jobs)
    if profile.get("id") not in ids:
        pool = pool + [profile]
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    sim, best = job_radar.find_best_match(
        proposal.query, pool, search_cfg=search_cfg,
    )
    return sim, best.get("id") if best else None


def simulate_kb_profile_new(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    job_radar_cfg: dict[str, Any] | None = None,
) -> tuple[float, str | None]:
    """Simulate retrieval if a cached LLM profile were added to the KB."""
    cached = job_radar.get_cached_job_profile(proposal.query)
    if not cached:
        return 0.0, None
    profile = dict(cached)
    profile.pop("_from_cache", None)
    ids = {j.get("id") for j in jobs}
    pool = list(jobs)
    if profile.get("id") not in ids:
        pool = pool + [profile]
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    sim, best = job_radar.find_best_match(
        proposal.query, pool, search_cfg=search_cfg,
    )
    return sim, best.get("id") if best else None
