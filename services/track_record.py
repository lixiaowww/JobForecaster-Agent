"""Track-record helpers: seed vs live origin, scoreboards, export verification (HR-11)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from paths import PROJECT_ROOT
from schemas import Prediction, Status

Origin = Literal["seed", "live"]

_RESOLVED = (Status.resolved_true, Status.resolved_false)
_OPEN = (Status.open, Status.due)


def seed_prediction_ids(seed_path: str | Path | None = None) -> set[str]:
    """Fingerprint IDs of curated benchmark rows in predictions_seed.json."""
    from services.dashboard_seed import _load_seed_rows

    path = Path(seed_path) if seed_path else PROJECT_ROOT / "data" / "predictions_seed.json"
    return {p.id for p in _load_seed_rows(path)}


def prediction_origin(p: Prediction, seed_ids: set[str]) -> Origin:
    return "seed" if p.id in seed_ids else "live"


def partition_by_origin(
    preds: list[Prediction],
    seed_ids: set[str] | None = None,
) -> tuple[list[Prediction], list[Prediction]]:
    """Split predictions into (seed, live) lists."""
    if seed_ids is None:
        seed_ids = seed_prediction_ids()
    seed: list[Prediction] = []
    live: list[Prediction] = []
    for p in preds:
        if prediction_origin(p, seed_ids) == "seed":
            seed.append(p)
        else:
            live.append(p)
    return seed, live


def scoreboard_subset(preds: list[Prediction]) -> dict:
    """Same shape as ``Registry.scoreboard()`` for an arbitrary prediction list."""
    scored = [p for p in preds if p.brier is not None]
    n = len(scored)
    mean_brier = sum(p.brier for p in scored) / n if n else None

    buckets: dict[int, list[Prediction]] = {}
    for p in scored:
        b = min(9, int(p.confidence * 10))
        buckets.setdefault(b, []).append(p)

    calibration = []
    for b in sorted(buckets):
        grp = buckets[b]
        avg_conf = sum(x.confidence for x in grp) / len(grp)
        hit_rate = sum(1 for x in grp if x.outcome) / len(grp)
        calibration.append({
            "bucket": f"{b*10}-{b*10+10}%",
            "n": len(grp),
            "avg_confidence": round(avg_conf, 3),
            "actual_hit_rate": round(hit_rate, 3),
        })

    return {
        "total": len(preds),
        "open": sum(1 for p in preds if p.status in _OPEN),
        "resolved": n,
        "ambiguous": sum(1 for p in preds if p.status == Status.ambiguous),
        "mean_brier": round(mean_brier, 4) if mean_brier is not None else None,
        "calibration": calibration,
    }


def upcoming_resolutions(
    preds: list[Prediction],
    *,
    today: date | None = None,
    limit: int = 10,
) -> list[Prediction]:
    """Open/due predictions sorted by resolution_date (soonest first)."""
    today = today or date.today()
    open_preds = [p for p in preds if p.status in _OPEN]
    open_preds.sort(key=lambda p: (p.resolution_date, p.created_at))
    return open_preds[:limit]


def days_until_resolution(p: Prediction, today: date | None = None) -> int:
    today = today or date.today()
    return (p.resolution_date - today).days


def verify_live_export_sync(
    db_live: list[Prediction],
    jsonl_live: list[Prediction],
) -> list[str]:
    """Return human-readable error strings; empty list means OK."""
    by_id = {p.id: p for p in jsonl_live}
    db_ids = {p.id for p in db_live}
    errors: list[str] = []

    for p in db_live:
        j = by_id.get(p.id)
        if j is None:
            errors.append(f"missing in JSONL: [{p.id[:8]}] {p.statement[:50]}")
            continue
        if p.status != j.status:
            errors.append(
                f"status mismatch [{p.id[:8]}]: db={p.status.value} jsonl={j.status.value}"
            )
        if p.outcome != j.outcome:
            errors.append(
                f"outcome mismatch [{p.id[:8]}]: db={p.outcome} jsonl={j.outcome}"
            )
        if p.brier is not None and j.brier is not None:
            if abs(p.brier - j.brier) > 1e-6:
                errors.append(
                    f"brier mismatch [{p.id[:8]}]: db={p.brier} jsonl={j.brier}"
                )

    for jid, j in by_id.items():
        if jid not in db_ids:
            errors.append(f"orphan in JSONL (not in DB live set): [{jid[:8]}]")

    return errors


def prediction_to_csv_row(p: Prediction, origin: Origin) -> dict:
    return {
        "origin": origin,
        "id": p.fingerprint(),
        "statement": p.statement,
        "category": p.category,
        "confidence": p.confidence,
        "horizon": p.horizon,
        "status": p.status.value,
        "resolution_date": p.resolution_date.isoformat() if p.resolution_date else "",
        "outcome": p.outcome,
        "brier": p.brier,
        "judged_rationale": p.judged_rationale,
        "sources": " | ".join(p.sources or []),
        "resolved_at": (
            p.resolved_at.isoformat() if p.resolved_at else ""
        ),
    }
