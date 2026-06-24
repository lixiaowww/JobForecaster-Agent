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
    # Keep ASCII alphanumeric; replace non-ASCII runs with a short hash so that
    # CJK queries (e.g. 人工智能工程师) don't all collapse to "query".
    ascii_part = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]
    if ascii_part:
        return ascii_part
    import hashlib
    return "q_" + hashlib.md5(text.encode()).hexdigest()[:8]


def propose_from_verdict(
    verdict: QueryVerdict,
    jobs_by_id: dict[str, dict] | None = None,
) -> CalibrationProposal | None:
    """Return a reviewable proposal for non-ok verdicts."""
    jobs_by_id = jobs_by_id or {}

    if verdict.is_regression and verdict.expected_id:
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

    if verdict.ok:
        return None

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

    return propose_title_alias(verdict, jobs_by_id)


def propose_title_alias(
    verdict: QueryVerdict,
    jobs_by_id: dict[str, dict],
) -> CalibrationProposal | None:
    """Map alternate query phrasing to the canonical KB job title."""
    target_id = verdict.expected_id or verdict.best_id
    if not target_id:
        return None
    job = jobs_by_id.get(target_id)
    if not job:
        return None
    canonical = str(job.get("title") or "").strip()
    if not canonical or verdict.query.strip().lower() == canonical.lower():
        return None
    return CalibrationProposal(
        proposal_id=f"title_{_slug(verdict.query)}",
        type="title_alias",
        query=verdict.query,
        target_id=target_id,
        payload={"canonical": canonical},
        evidence={
            "sim": verdict.sim,
            "tier": verdict.tier,
            "canonical": canonical,
        },
    )


def queue_proposal(proposal: CalibrationProposal, pending_dir: str | Path) -> Path:
    """Write proposal JSON to pending dir (HR-5 review gate)."""
    root = Path(pending_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{proposal.proposal_id}.json"
    body = proposal.to_dict()
    body["queued_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def proposal_from_dict(data: dict) -> CalibrationProposal:
    return CalibrationProposal(
        proposal_id=str(data["proposal_id"]),
        type=str(data["type"]),
        query=str(data["query"]),
        target_id=data.get("target_id"),
        payload=dict(data.get("payload") or {}),
        evidence=dict(data.get("evidence") or {}),
        status=str(data.get("status", "pending")),
    )


def load_pending_proposals(pending_dir: str | Path) -> list[tuple[Path, CalibrationProposal]]:
    """Load all pending calibration JSON files."""
    root = Path(pending_dir)
    if not root.is_dir():
        return []
    out: list[tuple[Path, CalibrationProposal]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append((path, proposal_from_dict(data)))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return out
