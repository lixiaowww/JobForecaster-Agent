"""Apply approved or auto-eligible calibration proposals to KB / config."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

import job_radar
from services import provenance
from services.job_query_agent.propose import CalibrationProposal, load_pending_proposals
from services.job_query_agent.simulate import (
    simulate_alias_patch,
    simulate_kb_profile_new,
    simulate_title_alias,
)


def load_kb(kb_path: str | Path) -> list[dict]:
    path = Path(kb_path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_kb(kb_path: str | Path, jobs: list[dict]) -> None:
    path = Path(kb_path)
    path.write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def apply_alias_patch_to_jobs(
    jobs: list[dict],
    target_id: str,
    aliases: list[str],
) -> list[dict]:
    out = copy.deepcopy(jobs)
    for j in out:
        if j.get("id") != target_id:
            continue
        existing = [str(a) for a in j.get("search_aliases") or []]
        for alias in aliases:
            if alias and alias not in existing:
                existing.append(alias)
        j["search_aliases"] = existing
        break
    return out


def apply_alias_patch_file(
    kb_path: str | Path,
    target_id: str,
    aliases: list[str],
) -> bool:
    jobs = load_kb(kb_path)
    before = next((j for j in jobs if j.get("id") == target_id), None)
    if before is None:
        return False
    save_kb(kb_path, apply_alias_patch_to_jobs(jobs, target_id, aliases))
    return True


def load_config_yaml(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def save_config_yaml(path: str | Path, cfg: dict) -> None:
    Path(path).write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def apply_title_alias_config(
    config_path: str | Path,
    query: str,
    canonical: str,
) -> bool:
    path = Path(config_path)
    cfg = load_config_yaml(path)
    search = cfg.setdefault("job_radar", {}).setdefault("search", {})
    aliases = dict(search.get("title_aliases") or {})
    key = query.strip().lower()
    if aliases.get(key) == canonical:
        return False
    aliases[key] = canonical
    search["title_aliases"] = aliases
    save_config_yaml(path, cfg)
    return True


def can_auto_apply(
    proposal: CalibrationProposal,
    *,
    sim_before: float,
    sim_after: float,
    best_id_after: str | None,
    agent_cfg: dict[str, Any],
    expected_id: str | None = None,
) -> tuple[bool, str]:
    """Decide if a proposal is safe to apply without human review."""
    auto = agent_cfg.get("auto_apply", {})
    if not auto.get("enabled", False):
        return False, "auto_apply disabled"
    allowed = set(auto.get("types", ["alias_patch", "title_alias"]))
    if proposal.type not in allowed:
        return False, f"type {proposal.type} not auto-eligible"

    job_radar_cfg = agent_cfg.get("_job_radar_cfg") or {}
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    min_sim = float(auto.get("min_sim_after", search_cfg.get("tier_weak", 0.55)))
    if sim_after < min_sim:
        return False, f"sim_after {sim_after:.3f} < {min_sim}"

    if expected_id and proposal.target_id and proposal.target_id != expected_id:
        return False, "target_id != expected_id"

    if expected_id and best_id_after and best_id_after != expected_id:
        return False, f"after apply best_id {best_id_after} != expected {expected_id}"

    if proposal.type == "alias_patch" and sim_after <= sim_before:
        return False, "no improvement"

    return True, "ok"


def _kb_profile_preview(query: str) -> dict | None:
    """Return cached LLM profile for gating without persisting."""
    cached = job_radar.get_cached_job_profile(query)
    return dict(cached) if cached else None


def apply_kb_profile_new(
    query: str,
    *,
    kb_path: str | Path,
    allow_llm: bool = True,
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
    reason: str = "auto_apply: kb_profile_new",
) -> dict[str, Any]:
    """Generate or reuse LLM profile and append to KB. Returns action metadata."""
    kb_path = str(kb_path)
    profile = job_radar.get_cached_job_profile(query)
    from_cache = profile is not None
    if profile is None and allow_llm:
        profile = job_radar.generate_job_profile_via_llm(query, kb_path=kb_path)
        from_cache = bool(profile and profile.get("_from_cache"))
    if profile is None:
        return {"applied": False, "reason": "no profile (cache miss and LLM unavailable)"}

    profile = dict(profile)
    profile.pop("_from_cache", None)
    existing_ids = {j.get("id") for j in job_radar.load_knowledge_base(kb_path, apply_calibration=False)}
    already_present = profile.get("id") in existing_ids
    job_radar._append_to_kb(profile, kb_path)

    jobs = job_radar.load_knowledge_base(kb_path, apply_calibration=False)
    search_cfg = job_radar.resolve_search_config()
    sim, best = job_radar.find_best_match(query, jobs, search_cfg=search_cfg)

    patch_id = None
    # _append_to_kb is idempotent by id — only ledger a patch if this call
    # actually created the entry, so a cache-hit replay doesn't spawn a
    # rollback-able "patch" that has nothing new to undo.
    if not already_present and profile.get("id") in {j.get("id") for j in jobs}:
        patch_id = provenance.record_patch(
            subsystem="job_query_agent",
            patch_type="kb_profile_new",
            reason=reason,
            before=None,
            after=profile,
            target_id=profile.get("id"),
            query=query,
            path=ledger_path,
        )

    return {
        "applied": True,
        "profile_id": profile.get("id"),
        "from_cache": from_cache,
        "sim_after": sim,
        "best_id_after": best.get("id") if best else None,
        "patch_id": patch_id,
    }


def can_auto_apply_kb_profile_new(
    proposal: CalibrationProposal,
    *,
    sim_after: float,
    best_id_after: str | None,
    agent_cfg: dict[str, Any],
    discovered_occurrences: int | None = None,
    profile: dict | None = None,
) -> tuple[bool, str]:
    auto = agent_cfg.get("auto_apply", {})
    kb_cfg = auto.get("kb_profile_new", {})
    if not auto.get("enabled", False):
        return False, "auto_apply disabled"
    if not kb_cfg.get("enabled", False):
        return False, "kb_profile_new auto disabled"

    search_cfg = job_radar.resolve_search_config(
        agent_cfg.get("_job_radar_cfg") or {},
    )
    min_sim = float(auto.get("min_sim_after", search_cfg.get("tier_weak", 0.55)))
    if sim_after < min_sim:
        return False, f"sim_after {sim_after:.3f} < {min_sim}"

    min_log = int(kb_cfg.get("min_search_log_occurrences", 3))
    if discovered_occurrences is not None and discovered_occurrences < min_log:
        return False, f"occurrences {discovered_occurrences} < {min_log}"

    preview = profile or _kb_profile_preview(proposal.query)
    if kb_cfg.get("require_cache_or_llm", True):
        if preview is None and not kb_cfg.get("allow_llm_generate", True):
            return False, "no cached profile and LLM generate disabled"

    if preview and not preview.get("sources"):
        return False, "profile missing sources (HR-7)"

    if preview and best_id_after and best_id_after != preview.get("id"):
        return False, f"best_id {best_id_after} != new profile id"

    return True, "ok"


def apply_proposal(
    proposal: CalibrationProposal,
    *,
    kb_path: str | Path,
    config_path: str | Path = "config.yaml",
    dry_run: bool = False,
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
    reason: str = "applied",
) -> dict[str, Any]:
    """Persist proposal. Returns metadata about the change.

    Every real (non-dry-run) mutation is recorded to the provenance ledger
    with a before/after snapshot so ``rollback_patch`` can undo it later if
    the post-apply monitor finds it regressed retrieval quality.
    """
    if proposal.type == "alias_patch":
        aliases = list(proposal.payload.get("add_aliases") or [])
        if dry_run:
            return {"type": proposal.type, "dry_run": True, "aliases": aliases}
        target_id = proposal.target_id or ""
        jobs_before = load_kb(kb_path)
        job_before = next((j for j in jobs_before if j.get("id") == target_id), None)
        before_aliases = list(job_before.get("search_aliases") or []) if job_before else None
        ok = apply_alias_patch_file(kb_path, target_id, aliases)
        patch_id = None
        if ok:
            jobs_after = load_kb(kb_path)
            job_after = next((j for j in jobs_after if j.get("id") == target_id), None)
            after_aliases = list(job_after.get("search_aliases") or []) if job_after else None
            patch_id = provenance.record_patch(
                subsystem="job_query_agent",
                patch_type="alias_patch",
                reason=reason,
                before={"search_aliases": before_aliases},
                after={"search_aliases": after_aliases},
                target_id=target_id,
                query=proposal.query,
                path=ledger_path,
            )
        return {"type": proposal.type, "applied": ok, "aliases": aliases, "patch_id": patch_id}

    if proposal.type == "title_alias":
        canonical = proposal.payload.get("canonical", "")
        if dry_run:
            return {"type": proposal.type, "dry_run": True, "canonical": canonical}
        key = proposal.query.strip().lower()
        cfg_before = load_config_yaml(config_path) if Path(config_path).is_file() else {}
        before_canonical = (
            cfg_before.get("job_radar", {}).get("search", {}).get("title_aliases", {}).get(key)
        )
        ok = apply_title_alias_config(
            config_path,
            proposal.query,
            canonical,
        )
        patch_id = None
        if ok:
            patch_id = provenance.record_patch(
                subsystem="job_query_agent",
                patch_type="title_alias",
                reason=reason,
                before={"key": key, "canonical": before_canonical},
                after={"key": key, "canonical": canonical},
                target_id=proposal.target_id,
                query=proposal.query,
                path=ledger_path,
            )
        return {"type": proposal.type, "applied": ok, "canonical": canonical, "patch_id": patch_id}

    if proposal.type == "kb_profile_new":
        query = proposal.query or str(proposal.payload.get("query") or "")
        if dry_run:
            preview = _kb_profile_preview(query)
            return {
                "type": proposal.type,
                "dry_run": True,
                "query": query,
                "cached": preview is not None,
            }
        return {
            "type": proposal.type,
            **apply_kb_profile_new(
                query, kb_path=kb_path, allow_llm=True,
                ledger_path=ledger_path, reason=reason,
            ),
        }

    return {"type": proposal.type, "applied": False, "reason": "unsupported type"}


def rollback_patch(
    patch_id: str,
    *,
    kb_path: str | Path,
    config_path: str | Path = "config.yaml",
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
    reason: str = "manual rollback",
) -> dict[str, Any]:
    """Undo a previously-applied, still-active patch using its ledger snapshot.

    This is the other half of the provenance ledger: ``record_patch`` proves
    what changed, ``rollback_patch`` is what makes that record load-bearing
    rather than decorative. Idempotent — rolling back an already-reverted or
    unknown patch_id is a no-op that reports why.
    """
    event = provenance.get_patch(patch_id, path=ledger_path)
    if event is None:
        return {"reverted": False, "patch_id": patch_id, "reason": "unknown patch_id"}
    if provenance.is_reverted(patch_id, path=ledger_path):
        return {"reverted": False, "patch_id": patch_id, "reason": "already reverted"}

    patch_type = event.get("type")
    before = event.get("before") or {}
    after = event.get("after") or {}
    target_id = event.get("target_id")

    if patch_type == "alias_patch":
        jobs = load_kb(kb_path)
        found = False
        for j in jobs:
            if j.get("id") == target_id:
                restored = before.get("search_aliases")
                if restored is None:
                    j.pop("search_aliases", None)
                else:
                    j["search_aliases"] = list(restored)
                found = True
                break
        if not found:
            return {"reverted": False, "patch_id": patch_id, "reason": f"target {target_id} not in KB"}
        save_kb(kb_path, jobs)

    elif patch_type == "title_alias":
        cfg = load_config_yaml(config_path)
        aliases = cfg.setdefault("job_radar", {}).setdefault("search", {}).setdefault("title_aliases", {})
        key = before.get("key") or event.get("query", "").strip().lower()
        prior_canonical = before.get("canonical")
        if prior_canonical is None:
            aliases.pop(key, None)
        else:
            aliases[key] = prior_canonical
        save_config_yaml(config_path, cfg)

    elif patch_type == "kb_profile_new":
        jobs = load_kb(kb_path)
        profile_id = after.get("id") or target_id
        remaining = [j for j in jobs if j.get("id") != profile_id]
        if len(remaining) == len(jobs):
            return {"reverted": False, "patch_id": patch_id, "reason": f"profile {profile_id} not in KB"}
        save_kb(kb_path, remaining)

    else:
        return {"reverted": False, "patch_id": patch_id, "reason": f"unsupported type {patch_type}"}

    provenance.mark_reverted(patch_id, reason=reason, path=ledger_path)
    return {"reverted": True, "patch_id": patch_id, "type": patch_type, "reason": reason}


def try_auto_apply_proposal(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    kb_path: str | Path,
    config_path: str | Path,
    job_radar_cfg: dict[str, Any] | None,
    agent_cfg: dict[str, Any],
    expected_id: str | None = None,
    sim_before: float = 0.0,
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
) -> dict[str, Any] | None:
    """Simulate, gate, and apply if safe. Returns action record or None."""
    agent_cfg = {
        **agent_cfg,
        "_job_radar_cfg": job_radar_cfg,
    }
    if proposal.type == "alias_patch":
        sim_after, best_after = simulate_alias_patch(
            proposal, jobs, job_radar_cfg=job_radar_cfg,
        )
    elif proposal.type == "title_alias":
        sim_after, best_after = simulate_title_alias(
            proposal, jobs, job_radar_cfg=job_radar_cfg,
        )
    elif proposal.type == "kb_profile_new":
        return try_auto_apply_kb_profile_new(
            proposal,
            jobs,
            kb_path=kb_path,
            job_radar_cfg=job_radar_cfg,
            agent_cfg=agent_cfg,
            discovered_occurrences=agent_cfg.get("_discovered_occurrences"),
            sim_before=sim_before,
            ledger_path=ledger_path,
        )
    else:
        return None

    ok, reason = can_auto_apply(
        proposal,
        sim_before=sim_before,
        sim_after=sim_after,
        best_id_after=best_after,
        agent_cfg=agent_cfg,
        expected_id=expected_id,
    )
    if not ok:
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": reason,
            "sim_before": sim_before,
            "sim_after": sim_after,
        }

    result = apply_proposal(
        proposal,
        kb_path=kb_path,
        config_path=config_path,
        dry_run=False,
        ledger_path=ledger_path,
        reason=f"auto_apply: sim {sim_before:.3f} -> {sim_after:.3f}",
    )
    return {
        "proposal_id": proposal.proposal_id,
        "type": proposal.type,
        "auto_applied": result.get("applied", False),
        "sim_before": sim_before,
        "sim_after": sim_after,
        "best_id_after": best_after,
        **result,
    }


def try_auto_apply_kb_profile_new(
    proposal: CalibrationProposal,
    jobs: list[dict],
    *,
    kb_path: str | Path,
    job_radar_cfg: dict[str, Any] | None,
    agent_cfg: dict[str, Any],
    discovered_occurrences: int | None = None,
    sim_before: float = 0.0,
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Auto-apply new KB profile when search-log frequency + sim gates pass."""
    auto = agent_cfg.get("auto_apply", {})
    if not auto.get("enabled", False):
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": "auto_apply disabled",
            "sim_before": sim_before,
            "sim_after": 0.0,
        }
    kb_cfg = auto.get("kb_profile_new", {})
    if not kb_cfg.get("enabled", False):
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": "kb_profile_new auto disabled",
            "sim_before": sim_before,
            "sim_after": 0.0,
        }
    allowed = set(auto.get("types", []))
    if "kb_profile_new" not in allowed:
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": "kb_profile_new not in auto_apply.types",
            "sim_before": sim_before,
            "sim_after": 0.0,
        }

    agent_cfg = {**agent_cfg, "_job_radar_cfg": job_radar_cfg}
    allow_llm = bool(kb_cfg.get("allow_llm_generate", True))
    preview = _kb_profile_preview(proposal.query)

    sim_after, best_after = simulate_kb_profile_new(
        proposal, jobs, job_radar_cfg=job_radar_cfg,
    )

    if preview is not None:
        ok, reason = can_auto_apply_kb_profile_new(
            proposal,
            sim_after=sim_after,
            best_id_after=best_after,
            agent_cfg=agent_cfg,
            discovered_occurrences=discovered_occurrences,
            profile=preview,
        )
        if not ok:
            return {
                "proposal_id": proposal.proposal_id,
                "type": proposal.type,
                "auto_applied": False,
                "reason": reason,
                "sim_before": sim_before,
                "sim_after": sim_after,
            }
        result = apply_kb_profile_new(
            proposal.query, kb_path=kb_path, allow_llm=False,
            ledger_path=ledger_path,
            reason=f"auto_apply: kb_profile_new (cached, sim_after={sim_after:.3f})",
        )
    else:
        min_log = int(kb_cfg.get("min_search_log_occurrences", 3))
        if discovered_occurrences is not None and discovered_occurrences < min_log:
            return {
                "proposal_id": proposal.proposal_id,
                "type": proposal.type,
                "auto_applied": False,
                "reason": f"occurrences {discovered_occurrences} < {min_log}",
                "sim_before": sim_before,
                "sim_after": 0.0,
            }
        if not allow_llm:
            return {
                "proposal_id": proposal.proposal_id,
                "type": proposal.type,
                "auto_applied": False,
                "reason": "no cached profile and LLM generate disabled",
                "sim_before": sim_before,
                "sim_after": 0.0,
            }
        result = apply_kb_profile_new(
            proposal.query, kb_path=kb_path, allow_llm=True,
            ledger_path=ledger_path,
            reason=f"auto_apply: kb_profile_new (llm, occurrences={discovered_occurrences})",
        )

    if not result.get("applied"):
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": result.get("reason", "apply failed"),
            "sim_before": sim_before,
            "sim_after": result.get("sim_after", 0.0),
        }

    post_sim = float(result.get("sim_after", 0.0))
    search_cfg = job_radar.resolve_search_config(job_radar_cfg)
    min_sim = float(
        agent_cfg.get("auto_apply", {}).get(
            "min_sim_after", search_cfg.get("tier_weak", 0.55),
        ),
    )
    if post_sim < min_sim:
        return {
            "proposal_id": proposal.proposal_id,
            "type": proposal.type,
            "auto_applied": False,
            "reason": f"post-apply sim {post_sim:.3f} < {min_sim}",
            "sim_before": sim_before,
            "sim_after": post_sim,
        }

    return {
        "proposal_id": proposal.proposal_id,
        "type": proposal.type,
        "auto_applied": True,
        "sim_before": sim_before,
        "sim_after": post_sim,
        "best_id_after": result.get("best_id_after"),
        **result,
    }


def run_apply_pending(
    cfg: dict[str, Any],
    *,
    dry_run: bool = False,
    proposal_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Apply human-reviewed proposals from pending/job_calibration/."""
    agent_cfg = cfg.get("job_query_agent", {})
    job_radar_cfg = cfg.get("job_radar", {})
    kb_path = job_radar_cfg.get("kb_path", "data/jobs_kb.json")
    config_path = cfg.get("_config_path", "config.yaml")
    ledger_path = agent_cfg.get("provenance_path", provenance.DEFAULT_LEDGER_PATH)
    pending_dir = agent_cfg.get("review", {}).get(
        "pending_dir", "pending/job_calibration",
    )

    results: list[dict[str, Any]] = []
    applied = 0
    for path, proposal in load_pending_proposals(pending_dir):
        if proposal_ids and proposal.proposal_id not in proposal_ids:
            continue
        result = apply_proposal(
            proposal,
            kb_path=kb_path,
            config_path=config_path,
            dry_run=dry_run,
            ledger_path=ledger_path,
            reason="human_approved: run_apply_pending",
        )
        result["proposal_id"] = proposal.proposal_id
        result["path"] = str(path)
        if result.get("applied") and not dry_run:
            path.unlink(missing_ok=True)
            applied += 1
        results.append(result)

    return {
        "pending_scanned": len(results),
        "applied": applied,
        "dry_run": dry_run,
        "results": results,
    }
