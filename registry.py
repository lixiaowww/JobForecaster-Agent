"""Persistent registry: stores predictions, dedups, finds due ones, scores calibration.

This is the memory of the loop. The track record it produces is fed back into the
next forecasting prompt so the agent can see how well-calibrated it has been.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from sqlmodel import Session, select, SQLModel

try:
    from .schemas import engine, Prediction, Status
except ImportError:
    from schemas import engine, Prediction, Status


class Registry:
    def __init__(self, path: str | Path | None = None):
        # path is kept for backward compatibility but unused as engine is configured centrally
        SQLModel.metadata.create_all(engine)

    # ---- io ---------------------------------------------------------------
    def load(self) -> list[Prediction]:
        with Session(engine) as session:
            statement = select(Prediction)
            return list(session.exec(statement).all())

    def _write_all(self, preds: Iterable[Prediction]) -> None:
        """Bulk overwrite table. Kept for compatibility."""
        with Session(engine) as session:
            # Delete existing
            session.query(Prediction).delete()
            # Add all
            for p in preds:
                session.add(p)
            session.commit()

    # ---- mutations --------------------------------------------------------
    def add_many(self, preds: Iterable[Prediction]) -> list[Prediction]:
        """Append new predictions, skipping duplicates (same statement + horizon)."""
        fresh = []
        with Session(engine) as session:
            for p in preds:
                p.assign_id()
                # Check if exists
                db_pred = session.get(Prediction, p.id)
                if db_pred is not None:
                    continue
                session.add(p)
                fresh.append(p)
            session.commit()
            
            # Refresh items in fresh list
            for p in fresh:
                session.refresh(p)
                
        return fresh

    def update(self, pred: Prediction) -> None:
        with Session(engine) as session:
            db_pred = session.get(Prediction, pred.id)
            if db_pred:
                # Update attributes
                for k, v in pred.model_dump().items():
                    setattr(db_pred, k, v)
                session.add(db_pred)
                session.commit()

    # ---- queries ----------------------------------------------------------
    def due(self, today: date | None = None) -> list[Prediction]:
        today = today or date.today()
        with Session(engine) as session:
            statement = select(Prediction).where(
                Prediction.status.in_([Status.open, Status.due]),
                Prediction.resolution_date <= today
            )
            return list(session.exec(statement).all())

    def recent_resolved(self, limit: int = 25) -> list[Prediction]:
        with Session(engine) as session:
            statement = select(Prediction).where(
                Prediction.status.in_([Status.resolved_true, Status.resolved_false])
            ).order_by(Prediction.resolved_at.desc()).limit(limit)
            return list(session.exec(statement).all())

    def open_predictions(self) -> list[Prediction]:
        with Session(engine) as session:
            statement = select(Prediction).where(
                Prediction.status.in_([Status.open, Status.due])
            )
            return list(session.exec(statement).all())

    def get(self, pred_id: str) -> Prediction | None:
        with Session(engine) as session:
            return session.get(Prediction, pred_id)

    # ---- scoring ----------------------------------------------------------
    def scoreboard(self) -> dict:
        preds = self.load()
        scored = [p for p in preds if p.brier is not None]
        n = len(scored)
        mean_brier = sum(p.brier for p in scored) / n if n else None

        # 10-bucket reliability curve: predicted confidence vs realised frequency
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
            "open": sum(1 for p in preds if p.status in (Status.open, Status.due)),
            "resolved": n,
            "ambiguous": sum(1 for p in preds if p.status == Status.ambiguous),
            "mean_brier": round(mean_brier, 4) if mean_brier is not None else None,
            "calibration": calibration,
        }

    def track_record_summary(self, limit: int = 15) -> str:
        """Compact, model-readable feedback for the next forecasting prompt.

        WRONG entries show more of judged_rationale so ROOT_CAUSE labels and
        CONTRAST_PAIR cross-references are not truncated — the model needs to see
        *why* a prediction failed, not just that it failed.
        """
        sb = self.scoreboard()
        lines = [
            f"Resolved predictions: {sb['resolved']}  |  mean Brier: {sb['mean_brier']} "
            f"(0=perfect, 0.25=coin-flip-at-50%, lower is better)",
            "LESSON: When a WRONG entry carries ROOT_CAUSE: it means that specific "
            "failure mode should be avoided in new predictions. CONTRAST_PAIR entries "
            "show the precise reframing that would have converted a MISS into a HIT.",
        ]
        for p in self.recent_resolved(limit):
            if p.outcome:
                verdict = "CORRECT"
                rationale_limit = 160
            else:
                verdict = "WRONG"
                rationale_limit = 280  # wider so ROOT_CAUSE label is never cut off
            lines.append(
                f"- [{verdict} @ conf {p.confidence:.2f}] {p.statement}"
                f"  -> {p.judged_rationale[:rationale_limit]}"
            )
        return "\n".join(lines)
