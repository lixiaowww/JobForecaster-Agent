"""Dashboard seed data for empty registry (HF Spaces)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete

from registry import Registry
from schemas import Prediction, engine, Status
from services.dashboard_seed import ensure_demo_registry


def _clean_predictions():
    with Session(engine) as session:
        session.exec(delete(Prediction))
        session.commit()


def test_ensure_demo_registry_loads_when_empty():
    _clean_predictions()
    assert ensure_demo_registry() is True
    sb = Registry().scoreboard()
    assert sb["total"] >= 5
    assert sb["resolved"] >= 3
    assert sb["calibration"]
    _clean_predictions()


def test_ensure_demo_registry_skips_when_populated():
    _clean_predictions()
    p = Prediction(
        statement="Existing row",
        rationale="Should block re-seed.",
        confidence=0.5,
        horizon="2026-Q4",
        resolution_date=date(2026, 12, 31),
        resolution_criteria="Test.",
        status=Status.open,
    ).assign_id()
    Registry().add_many([p])
    assert ensure_demo_registry() is False
    assert Registry().scoreboard()["total"] == 1
    _clean_predictions()
