"""Offline harness tests for registry scoring and dedup (HR-1, HR-2).

All tests use the ``isolated_registry`` fixture (tmp SQLite per test) so
they never touch the production DB and can run in any order without cleanup.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry import Registry
from schemas import Prediction, make_engine


# ---------------------------------------------------------------------------
# Isolation smoke-test
# ---------------------------------------------------------------------------

def test_isolated_registry_is_empty(isolated_registry):
    """Each test gets a fresh, empty DB — no cross-test pollution."""
    assert isolated_registry.scoreboard()["total"] == 0


# ---------------------------------------------------------------------------
# Core registry behaviour
# ---------------------------------------------------------------------------

def test_fingerprint_dedup(isolated_registry):
    p = Prediction(
        statement="Test claim A",
        rationale="Because reasons apply therefore outcome follows.",
        confidence=0.6,
        horizon="2026-Q4",
        resolution_date=date.today() + timedelta(days=90),
        resolution_criteria="Official data source confirms threshold.",
    ).assign_id()
    added = isolated_registry.add_many([p])
    assert len(added) == 1

    dup = Prediction(
        statement="Test claim A",  # same statement + horizon → same fingerprint
        rationale="Different rationale should not create duplicate.",
        confidence=0.7,
        horizon="2026-Q4",
        resolution_date=p.resolution_date,
        resolution_criteria="Other criteria.",
    ).assign_id()
    assert isolated_registry.add_many([dup]) == []


def test_brier_on_resolve():
    """Pure math — no DB needed."""
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


def test_scoreboard_empty(isolated_registry):
    sb = isolated_registry.scoreboard()
    assert sb["total"] == 0
    assert sb["mean_brier"] is None
    assert sb["calibration"] == []


def test_due_detection(isolated_registry):
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
    isolated_registry.add_many([past, future])
    due_ids = {p.id for p in isolated_registry.due()}
    assert past.id in due_ids
    assert future.id not in due_ids


def test_registry_path_arg_uses_separate_db(tmp_path):
    """Registry(path=...) must use the given file, NOT the global engine."""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    reg_a = Registry(path=db_a)
    reg_b = Registry(path=db_b)

    p = Prediction(
        statement="Only in DB-A",
        rationale="isolation test",
        confidence=0.5,
        horizon="2027-Q1",
        resolution_date=date(2027, 3, 31),
        resolution_criteria="test",
    ).assign_id()
    reg_a.add_many([p])

    # reg_b must NOT see the prediction added to reg_a
    assert reg_b.scoreboard()["total"] == 0
    assert reg_a.scoreboard()["total"] == 1


def test_track_record_summary_contains_root_cause(isolated_registry):
    """track_record_summary must not truncate ROOT_CAUSE labels on WRONG entries."""
    p = Prediction(
        statement="Employment decline across all devs",
        rationale="aggregate claim",
        confidence=0.75,
        horizon="2026-Q2",
        resolution_date=date(2026, 6, 30),
        resolution_criteria="BLS total employment",
    ).assign_id()
    long_rationale = (
        "ROOT_CAUSE:wrong_granularity | The aggregate BLS series did not decline; "
        "only junior roles at large tech shrank. "
        "CONTRAST_PAIR_FOR:wrong_granularity_miss — a narrower claim would have resolved TRUE."
    )
    p.resolve(False, long_rationale)
    isolated_registry.add_many([p])

    summary = isolated_registry.track_record_summary()
    assert "ROOT_CAUSE:wrong_granularity" in summary
    assert "CONTRAST_PAIR_FOR:wrong_granularity_miss" in summary
