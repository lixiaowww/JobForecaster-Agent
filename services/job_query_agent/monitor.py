"""Post-apply regression monitor — the immune system half of self-evolution.

``apply.py`` already gates every auto-applied patch *before* it lands (see
``can_auto_apply`` / ``can_auto_apply_kb_profile_new``): a patch only ships if
it clears ``min_sim_after`` against the KB *at that moment*. What nothing
previously checked is whether it *stays* good as the KB keeps changing under
it — a later alias_patch or kb_profile_new can silently steal a query's best
match away from an earlier patch's target, and nothing would notice.

This module re-evaluates every active (non-reverted) provenance-ledger patch
against the *current* KB, using the same ``evaluate_query`` signal already
trusted for pre-apply gating and CI audits. Anything that now regresses gets
rolled back via ``apply.rollback_patch`` and the ledger records why.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import job_radar
from services import provenance
from services.job_query_agent.apply import rollback_patch
from services.job_query_agent.discover import DiscoveredQuery
from services.job_query_agent.evaluate import evaluate_query


def _expected_id_for(patch: dict[str, Any]) -> str | None:
    """The id a patch's query should resolve to, for regression purposes.

    For alias_patch / title_alias the target_id recorded at apply time *is*
    the expected match. For kb_profile_new, target_id is the nearest
    *pre-existing* neighbor recorded as evidence in the proposal — success is
    the query resolving to the newly created profile instead, so use
    ``after.id``.
    """
    if patch.get("type") == "kb_profile_new":
        return (patch.get("after") or {}).get("id")
    return patch.get("target_id")


def check_active_patches(
    cfg: dict[str, Any],
    *,
    kb_path: str | Path | None = None,
    config_path: str | Path = "config.yaml",
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-check every active job_query_agent patch; revert regressions.

    Returns a summary with per-patch verdicts so callers (CLI, calibration
    loop, tests) can see exactly what was checked and what was reverted —
    the monitor should never revert silently.
    """
    job_radar_cfg = cfg.get("job_radar", {})
    kb_path = kb_path or job_radar_cfg.get("kb_path", "data/jobs_kb.json")
    jobs = job_radar.load_knowledge_base(str(kb_path))

    checked: list[dict[str, Any]] = []
    reverted: list[dict[str, Any]] = []

    for patch in provenance.active_patches(ledger_path, subsystem="job_query_agent"):
        query = patch.get("query")
        if not query:
            continue
        expected_id = _expected_id_for(patch)
        item = DiscoveredQuery(query, "provenance_recheck", expected_id)
        verdict = evaluate_query(item, jobs, job_radar_cfg=job_radar_cfg)

        record = {
            "patch_id": patch["patch_id"],
            "type": patch.get("type"),
            "query": query,
            "expected_id": expected_id,
            "status": verdict.status,
            "sim": round(verdict.sim, 4),
            "best_id": verdict.best_id,
        }
        checked.append(record)

        # p0_regression: query no longer resolves to the id this patch earned.
        # weak_core: still resolves correctly, but sim decayed below the gate
        # that justified auto-applying it in the first place — same signal
        # can_auto_apply used pre-apply, now applied post-apply.
        should_revert = expected_id is not None and verdict.status in (
            "p0_regression", "weak_core",
        )
        if not should_revert:
            continue

        record["regression_reason"] = verdict.message
        if dry_run:
            record["would_revert"] = True
            reverted.append(record)
            continue

        result = rollback_patch(
            patch["patch_id"],
            kb_path=kb_path,
            config_path=config_path,
            ledger_path=ledger_path,
            reason=f"post-apply regression: {verdict.status} ({verdict.message})",
        )
        record["rollback"] = result
        reverted.append(record)
        if result.get("reverted"):
            # KB (or config) shape changed — reload so subsequent patches in
            # this same sweep are checked against the post-rollback state.
            jobs = job_radar.load_knowledge_base(str(kb_path))

    return {
        "checked": len(checked),
        "reverted": sum(1 for r in reverted if r.get("rollback", {}).get("reverted") or r.get("would_revert")),
        "dry_run": dry_run,
        "details": checked,
        "reverted_patches": reverted,
    }
