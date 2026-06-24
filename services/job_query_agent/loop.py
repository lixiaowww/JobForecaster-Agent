"""Calibration loop — discover, evaluate, auto-apply safe fixes, re-audit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import job_radar
from services.job_query_agent.apply import try_auto_apply_proposal
from services.job_query_agent.discover import discover_queries
from services.job_query_agent.evaluate import QueryVerdict, evaluate_query
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
                )
                if action:
                    applied_actions.append(action)
                    if action.get("auto_applied"):
                        round_applied += 1
                        continue

            if not dry_run:
                queue_proposal(proposal, pending_dir)
                queued += 1

        if round_applied == 0:
            break

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

    return {
        "rounds": round_idx + 1 if round_idx >= 0 else 0,
        "auto_applied": sum(1 for a in applied_actions if a.get("auto_applied")),
        "apply_actions": applied_actions,
        "proposals_queued": queued,
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
