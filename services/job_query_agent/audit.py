"""Run a full query-agent audit cycle."""
from __future__ import annotations

import json
from typing import Any

import job_radar
from services.job_query_agent.discover import discover_queries
from services.job_query_agent.evaluate import QueryVerdict, evaluate_query
from services.job_query_agent.propose import propose_from_verdict, queue_proposal
from services.job_query_agent.traces import append_trace


def run_audit(
    cfg: dict[str, Any],
    *,
    write_traces: bool = True,
    queue_proposals: bool = False,
) -> dict[str, Any]:
    """Discover queries, evaluate retrieval, optionally trace and queue fixes.

    Returns a summary dict. Raises AssertionError when P0 regressions exist
    (used by CI ``run.py query-agent audit``).
    """
    agent_cfg = cfg.get("job_query_agent", {})
    job_radar_cfg = cfg.get("job_radar", {})
    kb_path = job_radar_cfg.get("kb_path", "data/jobs_kb.json")
    jobs = job_radar.load_knowledge_base(kb_path)

    discovered = discover_queries(cfg)
    verdicts: list[QueryVerdict] = []
    proposals_queued = 0

    for item in discovered:
        verdict = evaluate_query(item, jobs, job_radar_cfg=job_radar_cfg)
        verdicts.append(verdict)

        if write_traces:
            traces_path = agent_cfg.get("traces_path", "data/query_agent_traces.jsonl")
            append_trace(traces_path, {
                "query": verdict.query,
                "source": verdict.source,
                "status": verdict.status,
                "sim": verdict.sim,
                "tier": verdict.tier,
                "expected_id": verdict.expected_id,
                "best_id": verdict.best_id,
                "message": verdict.message,
            })

        if queue_proposals and not verdict.ok:
            jobs_by_id = {j["id"]: j for j in jobs}
            proposal = propose_from_verdict(verdict, jobs_by_id)
            if proposal:
                pending = agent_cfg.get("review", {}).get(
                    "pending_dir", "pending/job_calibration",
                )
                queue_proposal(proposal, pending)
                proposals_queued += 1

    regressions = [v for v in verdicts if v.is_regression]
    weak_core = [v for v in verdicts if v.status == "weak_core"]
    kb_gaps = [v for v in verdicts if v.status == "kb_gap"]
    weak_matches = [v for v in verdicts if v.status == "weak_match"]
    ok_count = sum(1 for v in verdicts if v.ok)

    summary = {
        "queries": len(verdicts),
        "ok": ok_count,
        "p0_regressions": len(regressions),
        "weak_core": len(weak_core),
        "kb_gaps": len(kb_gaps),
        "weak_matches": len(weak_matches),
        "proposals_queued": proposals_queued,
        "failures": [
            {"query": v.query, "message": v.message, "status": v.status}
            for v in regressions + weak_core
        ],
    }

    if regressions:
        lines = "\n".join(f"  - {v.query}: {v.message}" for v in regressions)
        raise AssertionError(
            f"Query agent P0 regression ({len(regressions)}):\n{lines}"
        )

    if weak_core and agent_cfg.get("evaluate", {}).get("fail_on_weak_core", True):
        lines = "\n".join(f"  - {v.query}: {v.message}" for v in weak_core)
        raise AssertionError(
            f"Query agent weak core match ({len(weak_core)}):\n{lines}"
        )

    return summary


def audit_report_json(cfg: dict[str, Any]) -> str:
    return json.dumps(run_audit(cfg), indent=2)
