"""Propose calibration actions from query verdicts (queued, not auto-applied by default)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.job_query_agent.evaluate import QueryVerdict


@dataclass(frozen=True)
class CalibrationProposal:
    proposal_id: str
    type: str
    query: str
    target_id: str | None
    payload: dict[str, Any]
    evidence: dict[str, Any]
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:48] or "query"


def propose_from_verdict(verdict: QueryVerdict) -> CalibrationProposal | None:
    """Return a reviewable proposal for non-ok verdicts."""
    if verdict.ok or verdict.is_regression:
        if verdict.status == "weak_core" and verdict.expected_id:
            return CalibrationProposal(
                proposal_id=f"alias_{_slug(verdict.query)}",
                type="alias_patch",
                query=verdict.query,
                target_id=verdict.expected_id,
                payload={"add_aliases": [verdict.query]},
                evidence={
                    "sim": verdict.sim,
                    "tier": verdict.tier,
                    "reason": verdict.message,
                },
            )
        return None

    if verdict.status == "kb_gap":
        return CalibrationProposal(
            proposal_id=f"kb_gap_{_slug(verdict.query)}",
            type="kb_profile_new",
            query=verdict.query,
            target_id=verdict.best_id,
            payload={"query": verdict.query, "nearest_id": verdict.best_id},
            evidence={"sim": verdict.sim, "tier": verdict.tier, "best_title": verdict.best_title},
        )

    if verdict.status == "weak_match" and verdict.best_id:
        return CalibrationProposal(
            proposal_id=f"alias_{_slug(verdict.query)}",
            type="alias_patch",
            query=verdict.query,
            target_id=verdict.best_id,
            payload={"add_aliases": [verdict.query]},
            evidence={"sim": verdict.sim, "tier": verdict.tier, "best_title": verdict.best_title},
        )

    return None


def queue_proposal(proposal: CalibrationProposal, pending_dir: str | Path) -> Path:
    """Write proposal JSON to pending dir (HR-5 review gate)."""
    root = Path(pending_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{proposal.proposal_id}.json"
    body = proposal.to_dict()
    body["queued_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
