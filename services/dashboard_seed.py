"""Seed demo predictions when the registry is empty (e.g. Hugging Face Space)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from paths import PROJECT_ROOT
from registry import Registry
from schemas import Prediction, Status


def ensure_demo_registry(seed_path: str | Path | None = None) -> bool:
    """Load seed predictions if the SQLite registry has no rows. Returns True if seeded."""
    reg = Registry()
    if reg.load():
        return False

    path = Path(seed_path) if seed_path else PROJECT_ROOT / "data" / "predictions_seed.json"
    if not path.is_file():
        return False

    raw = json.loads(path.read_text(encoding="utf-8"))
    preds: list[Prediction] = []
    for row in raw:
        p = Prediction.model_validate(row)
        if p.status in (Status.resolved_true, Status.resolved_false) and p.outcome is not None:
            if p.brier is None:
                p.brier = (p.confidence - (1.0 if p.outcome else 0.0)) ** 2
            if p.resolved_at is None:
                p.resolved_at = datetime.now(timezone.utc)
        p.assign_id()
        preds.append(p)

    if preds:
        reg.add_many(preds)
    return bool(preds)
