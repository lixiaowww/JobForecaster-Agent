"""Offline harness tests for registry scoring and dedup (HR-1, HR-2)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete

from registry import Registry
from schemas import Prediction, engine


def _clean_predictions():
    with Session(engine) as session:
        session.exec(delete(Prediction))
        session.commit()


def test_fingerprint_dedup():
    _clean_predictions()
    reg = Registry()
    p = Prediction(
        statement="Test claim A",
        rationale="Because reasons apply therefore outcome follows.",
        confidence=0.6,
        horizon="2026-Q4",
        resolution_date=date.today() + timedelta(days=90),
        resolution_criteria="Official data source confirms threshold.",
    ).assign_id()
    added = reg.add_many([p])
    assert len(added) == 1
    dup = Prediction(
        statement="Test claim A",
        rationale="Different rationale should not create duplicate.",
        confidence=0.7,
        horizon="2026-Q4",
        resolution_date=p.resolution_date,
        resolution_criteria="Other criteria.",
    ).assign_id()
    assert reg.add_many([dup]) == []
    _clean_predictions()


def test_brier_on_resolve():
    p = Prediction(
        statement="Brier math check",
        rationale="Test only.",
        confidence=0.7,
        horizon="2026-Q1",
        resolution_date=date.today(),
        resolution_criteria="N/A",
    )
    p.resolve(True, "resolved true for test")
    assert p.brier == pytest.approx(0.09)
    p2 = Prediction(
        statement="Brier math check false",
        rationale="Test only.",
        confidence=0.3,
        horizon="2026-Q1",
        resolution_date=date.today(),
        resolution_criteria="N/A",
    )
    p2.resolve(False, "resolved false for test")
    assert p2.brier == pytest.approx(0.09)


def test_scoreboard_empty():
    _clean_predictions()
    sb = Registry().scoreboard()
    assert sb["total"] == 0
    assert sb["mean_brier"] is None
    assert sb["calibration"] == []
    _clean_predictions()


def test_due_detection():
    _clean_predictions()
    reg = Registry()
    past = Prediction(
        statement="Due prediction",
        rationale="Should appear in due().",
        confidence=0.5,
        horizon="2025-Q1",
        resolution_date=date.today() - timedelta(days=1),
        resolution_criteria="Public data.",
    ).assign_id()
    future = Prediction(
        statement="Future prediction",
        rationale="Should not be due yet.",
        confidence=0.5,
        horizon="2030-Q1",
        resolution_date=date.today() + timedelta(days=365),
        resolution_criteria="Public data.",
    ).assign_id()
    reg.add_many([past, future])
    due_ids = {p.id for p in reg.due()}
    assert past.id in due_ids
    assert future.id not in due_ids
    _clean_predictions()
