"""Append-only provenance ledger for self-mutating subsystems.

Every automatic write this project makes to a knowledge base or config file
(job KB aliases, new KB profiles, title-alias config entries, ...) should be
recorded here: what changed, why, and enough before/after state to reverse
it. A system that mutates itself without a paper trail is a liability, not
an asset — this module is the paper trail.

Ledger is append-only JSONL (one event per line), never rewritten in place,
so the log itself is auditable. Two event kinds:

  - "applied":  a patch was written. Carries before/after snapshots.
  - "reverted": a prior "applied" patch was rolled back. References patch_id.

A patch is *active* if it has an "applied" event and no later "reverted"
event with the same patch_id. See ``services/job_query_agent/apply.py``
(``rollback_patch``) for how an active patch is actually reversed, and
``services/job_query_agent/monitor.py`` for the post-apply regression sweep
that decides *when* to call it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LEDGER_PATH = "data/provenance_log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_patch_id(subsystem: str) -> str:
    return f"{subsystem}_{uuid.uuid4().hex[:12]}"


def _append(path: str | Path, event: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def record_patch(
    *,
    subsystem: str,
    patch_type: str,
    reason: str,
    before: Any = None,
    after: Any = None,
    target_id: str | None = None,
    query: str | None = None,
    extra: dict[str, Any] | None = None,
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> str:
    """Record a self-applied mutation. Returns the new patch_id.

    ``before``/``after`` should be the smallest JSON-serialisable snapshot
    that lets ``rollback_patch`` undo the change exactly (e.g. the full prior
    ``search_aliases`` list, not just the added alias).
    """
    patch_id = new_patch_id(subsystem)
    event = {
        "event": "applied",
        "patch_id": patch_id,
        "ts": _now(),
        "subsystem": subsystem,
        "type": patch_type,
        "target_id": target_id,
        "query": query,
        "reason": reason,
        "before": before,
        "after": after,
        "extra": extra or {},
    }
    _append(path, event)
    return patch_id


def mark_reverted(
    patch_id: str,
    *,
    reason: str,
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> None:
    _append(path, {
        "event": "reverted",
        "patch_id": patch_id,
        "ts": _now(),
        "reason": reason,
    })


def load_events(path: str | Path = DEFAULT_LEDGER_PATH) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def active_patches(
    path: str | Path = DEFAULT_LEDGER_PATH,
    *,
    subsystem: str | None = None,
) -> list[dict[str, Any]]:
    """Applied patches with no later revert event, most recent first."""
    events = load_events(path)
    applied: dict[str, dict[str, Any]] = {}
    reverted: set[str] = set()
    for e in events:
        pid = e.get("patch_id")
        if not pid:
            continue
        if e.get("event") == "applied":
            applied[pid] = e
        elif e.get("event") == "reverted":
            reverted.add(pid)
    out = [e for pid, e in applied.items() if pid not in reverted]
    if subsystem:
        out = [e for e in out if e.get("subsystem") == subsystem]
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out


def get_patch(
    patch_id: str,
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any] | None:
    for e in load_events(path):
        if e.get("event") == "applied" and e.get("patch_id") == patch_id:
            return e
    return None


def is_reverted(patch_id: str, path: str | Path = DEFAULT_LEDGER_PATH) -> bool:
    for e in load_events(path):
        if e.get("event") == "reverted" and e.get("patch_id") == patch_id:
            return True
    return False
