"""Seed demo predictions when the registry is empty (e.g. Hugging Face Space)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from paths import PROJECT_ROOT
from registry import Registry
from schemas import Prediction, Status


def _coerce(p: Prediction) -> Prediction:
    if p.status in (Status.resolved_true, Status.resolved_false) and p.outcome is not None:
        if p.brier is None:
            p.brier = (p.confidence - (1.0 if p.outcome else 0.0)) ** 2
        if p.resolved_at is None:
            p.resolved_at = datetime.now(timezone.utc)
    p.assign_id()
    return p


def _load_seed_rows(path: Path) -> list[Prediction]:
    """Curated illustrative seed (JSON array)."""
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [_coerce(Prediction.model_validate(row)) for row in raw]


def _load_live_rows(path: Path) -> list[Prediction]:
    """Real predictions accumulated by the daily LLM cron (JSONL, one per line).

    Committed back to the repo by the daily-pages workflow (real-LLM runs only),
    so the public demo's track record grows over time instead of staying frozen.
    """
    if not path.is_file():
        return []
    out: list[Prediction] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(_coerce(Prediction.model_validate_json(line)))
        except Exception:
            continue
    return out


def ensure_demo_registry(
    seed_path: str | Path | None = None,
    live_path: str | Path | None = None,
) -> bool:
    """Seed the registry when empty: curated seed + any accumulated live predictions.

    Returns True if anything was loaded.
    """
    reg = Registry()
    if reg.load():
        return False

    seed = Path(seed_path) if seed_path else PROJECT_ROOT / "data" / "predictions_seed.json"
    live = Path(live_path) if live_path else PROJECT_ROOT / "data" / "predictions_live.jsonl"

    preds = _load_seed_rows(seed) + _load_live_rows(live)
    if preds:
        # add_many dedups by id (statement + horizon), so seed/live overlap is safe.
        reg.add_many(preds)
    return bool(preds)
