"""Calibration loop — discover, evaluate, auto-apply safe fixes, re-audit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import job_radar
from services import provenance
from services.job_query_agent import claims
from services.job_query_agent.apply import try_auto_apply_proposal
from services.job_query_agent.discover import discover_queries
from services.job_query_agent.evaluate import QueryVerdict, evaluate_query
from services.job_query_agent.monitor import check_active_patches
from services.job_query_agent.propose import propose_from_verdict, queue_proposal
from services.job_query_agent.traces import append_trace


def run_calibration_cycle(
    cfg: dict[str, Any],
    *,
    write_traces: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Closed loop: find gaps → simulate → auto-apply safe patches → re-check.

    Unlike ``run_audit``, does not raise on first failure; iterates up to
    ``max_rounds`` applying eligible fixes, then returns a summary.
    """
    agent_cfg = cfg.get("job_query_agent", {})
    job_radar_cfg = cfg.get("job_radar", {})
    kb_path = Path(job_radar_cfg.get("kb_path", "data/jobs_kb.json"))
    config_path = Path(cfg.get("_config_path", "config.yaml"))
    max_rounds = int(agent_cfg.get("auto_apply", {}).get("max_rounds", 3))
    pending_dir = agent_cfg.get("review", {}).get(
        "pending_dir", "pending/job_calibration",
    )
    traces_path = agent_cfg.get("traces_path", "data/query_agent_traces.jsonl")
    ledger_path = agent_cfg.get("provenance_path", provenance.DEFAULT_LEDGER_PATH)

    applied_actions: list[dict] = []
    queued = 0
    round_idx = -1

    for round_idx in range(max_rounds):
        jobs = job_radar.load_knowledge_base(str(kb_path))
        jobs_by_id = {j["id"]: j for j in jobs}
        discovered = discover_queries(cfg)
        round_applied = 0

        for item in discovered:
            verdict = evaluate_query(item, jobs, job_radar_cfg=job_radar_cfg)
            if write_traces:
                append_trace(traces_path, {
                    "phase": "calibrate",
                    "round": round_idx + 1,
                    "query": verdict.query,
                    "status": verdict.status,
                    "sim": verdict.sim,
                    "tier": verdict.tier,
                    "expected_id": verdict.expected_id,
                    "best_id": verdict.best_id,
                })

            if verdict.ok:
                continue

            proposal = propose_from_verdict(verdict, jobs_by_id)
            if proposal is None:
                continue

            auto_enabled = agent_cfg.get("auto_apply", {}).get("enabled", False)
            if auto_enabled and not dry_run:
                ctx_agent = {
                    **agent_cfg,
                    "_discovered_occurrences": item.occurrences,
                    "_cfg": cfg,   # lets the gate reach the claims DB
                }
                action = try_auto_apply_proposal(
                    proposal,
                    jobs,
                    kb_path=kb_path,
                    config_path=config_path,
                    job_radar_cfg=job_radar_cfg,
                    agent_cfg=ctx_agent,
                    expected_id=verdict.expected_id,
                    sim_before=verdict.sim,
                    ledger_path=ledger_path,
                )
                if action:
                    # Context the claim needs but the apply layer does not
                    # return: what was asked, whether a human-labelled anchor
                    # existed, and how much organic demand backed it.
                    action["_query"] = verdict.query
                    action["_expected_id"] = verdict.expected_id
                    action["_occurrences"] = item.occurrences
                    action["_source"] = verdict.source
                    applied_actions.append(action)
                    if action.get("auto_applied"):
                        round_applied += 1
                        continue

            if not dry_run:
                queue_proposal(proposal, pending_dir)
                queued += 1

        if round_applied == 0:
            break

    # Stake a dated, falsifiable claim on every patch just auto-applied.
    # The gate that let these through scored them against the KB they edit;
    # these claims are how the same patches get scored against the world
    # instead, ~horizon_days from now. See services/job_query_agent/claims.py.
    staked: list[dict[str, Any]] = []
    if not dry_run and claims.is_enabled(agent_cfg):
        jobs_now = {j["id"]: j for j in job_radar.load_knowledge_base(str(kb_path))}
        staked = [
            {
                "claim_id": c.id,
                "patch_type": c.patch_type,
                "query": c.query,
                "target_id": c.target_id,
                "confidence": c.confidence,
                "resolution_date": c.resolution_date.isoformat(),
            }
            for c in claims.open_claims_for_actions(
                applied_actions,
                cfg=cfg,
                agent_cfg=agent_cfg,
                jobs_by_id=jobs_now,
            )
        ]

    # Post-apply regression sweep: re-check every previously auto-applied,
    # still-active patch against the KB as it stands *now* (including
    # whatever this cycle's own rounds just changed) and auto-revert any
    # that regressed. Pre-apply gating above only proves a patch looked safe
    # the moment it landed; this is what keeps it honest afterwards.
    regression_monitor: dict[str, Any] = {}
    if agent_cfg.get("auto_apply", {}).get("enabled", False):
        try:
            regression_monitor = check_active_patches(
                cfg,
                kb_path=kb_path,
                config_path=config_path,
                ledger_path=ledger_path,
                dry_run=dry_run,
            )
        except Exception:
            pass  # non-fatal; a monitor bug should never block the cycle

    # Final audit pass (raises only on P0 if called from strict mode elsewhere)
    jobs = job_radar.load_knowledge_base(str(kb_path))
    discovered = discover_queries(cfg)
    final_verdicts: list[QueryVerdict] = [
        evaluate_query(item, jobs, job_radar_cfg=job_radar_cfg)
        for item in discovered
    ]
    regressions = [v for v in final_verdicts if v.is_regression]
    weak_core = [v for v in final_verdicts if v.status == "weak_core"]
    kb_gaps = [v for v in final_verdicts if v.status == "kb_gap"]

    # Coverage enrichment pass: proactively fill KB for high-employment roles.
    coverage_summary: dict[str, Any] = {}
    enrich_cfg = agent_cfg.get("coverage_enrichment", {})
    if not dry_run and enrich_cfg.get("enabled", False):
        try:
            from services.bls_coverage import run_coverage_enrichment
            daily_budget = int(enrich_cfg.get("tavily_daily_budget", 20))
            coverage_summary = run_coverage_enrichment(cfg, daily_budget=daily_budget)
        except Exception:
            pass  # non-fatal

    # Transition evaluation pass: fill empty transition_targets via LLM judge.
    transition_summary: dict[str, Any] = {}
    if not dry_run and agent_cfg.get("auto_apply", {}).get("enabled", False):
        try:
            from services.transition_evaluator.evaluate import run_evaluation_pass
            fresh_jobs = job_radar.load_knowledge_base(str(kb_path))
            transition_summary = run_evaluation_pass(
                fresh_jobs,
                kb_path=str(kb_path),
                # Follow the configured cache, not the module default: a cycle
                # pointed at a sandbox KB must not write pair verdicts for
                # sandbox job ids into the production cache.
                cache_path=str(agent_cfg.get(
                    "transition_eval_cache_path", "data/transition_eval_cache.json")),
                max_pairs=int(agent_cfg.get("transition_eval_max_pairs", 40)),
            )
        except Exception:
            pass  # non-fatal; transitions improve incrementally

    # Judge claims whose horizon has elapsed against external evidence. This
    # is the only step in the whole cycle whose verdict the KB cannot sway —
    # its inputs are user search behaviour, human feedback, and BLS data.
    claim_resolution: dict[str, Any] = {}
    if claims.is_enabled(agent_cfg):
        try:
            claim_resolution = claims.resolve_due_claims(
                cfg,
                agent_cfg=agent_cfg,
                jobs_by_id={j["id"]: j for j in jobs},
                dry_run=dry_run,
            )
        except Exception:
            pass  # non-fatal, same policy as the regression monitor

    return {
        "rounds": round_idx + 1 if round_idx >= 0 else 0,
        "auto_applied": sum(1 for a in applied_actions if a.get("auto_applied")),
        "apply_actions": applied_actions,
        "proposals_queued": queued,
        "coverage_enrichment": coverage_summary,
        "transition_eval": transition_summary,
        "regression_monitor": regression_monitor,
        "claims_staked": staked,
        "claims_resolved": claim_resolution,
        "final": {
            "queries": len(final_verdicts),
            "ok": sum(1 for v in final_verdicts if v.ok),
            "p0_regressions": len(regressions),
            "weak_core": len(weak_core),
            "kb_gaps": len(kb_gaps),
            "weak_matches": sum(1 for v in final_verdicts if v.status == "weak_match"),
        },
        "remaining_failures": [
            {"query": v.query, "status": v.status, "message": v.message}
            for v in regressions + weak_core + kb_gaps
        ],
    }
