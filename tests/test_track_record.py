"""Tests for services/track_record.py (HR-11)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete

from registry import Registry
from schemas import Prediction, Status, engine
from services.track_record import (
    partition_by_origin,
    prediction_origin,
    scoreboard_subset,
    seed_prediction_ids,
    upcoming_resolutions,
    verify_live_export_sync,
)


def _clean():
    with Session(engine) as session:
        session.exec(delete(Prediction))
        session.commit()


def test_seed_prediction_ids_loads_from_file():
    ids = seed_prediction_ids()
    assert len(ids) >= 8


def test_partition_by_origin(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([{
        "statement": "Seed only claim",
        "rationale": "r", "category": "macro", "confidence": 0.6,
        "horizon": "2026-Q4", "resolution_date": "2026-12-31",
        "resolution_criteria": "c", "status": "resolved_true",
        "outcome": True, "judged_rationale": "ok",
    }]), encoding="utf-8")
    seed_ids = seed_prediction_ids(seed)
    assert len(seed_ids) == 1

    seed_p = Prediction.model_validate(json.loads(seed.read_text())[0]).assign_id()
    live_p = Prediction(
        statement="Live cron claim",
        rationale="r", confidence=0.5, horizon="2027-Q1",
        resolution_date=date(2027, 3, 31), resolution_criteria="c",
    ).assign_id()

    s, l = partition_by_origin([seed_p, live_p], seed_ids)
    assert len(s) == 1 and len(l) == 1
    assert prediction_origin(seed_p, seed_ids) == "seed"
    assert prediction_origin(live_p, seed_ids) == "live"


def test_scoreboard_subset_mean_brier():
    p_hit = Prediction(
        statement="Hit", rationale="r", confidence=0.8, horizon="2026-Q1",
        resolution_date=date(2026, 3, 31), resolution_criteria="c",
    )
    p_hit.resolve(True, "yes")
    p_miss = Prediction(
        statement="Miss", rationale="r", confidence=0.8, horizon="2026-Q1",
        resolution_date=date(2026, 3, 31), resolution_criteria="c",
    )
    p_miss.resolve(False, "no")
    sb = scoreboard_subset([p_hit, p_miss])
    assert sb["resolved"] == 2
    assert sb["mean_brier"] == pytest.approx(0.34)


def test_upcoming_resolutions_sorted():
    p1 = Prediction(
        statement="Soon", rationale="r", confidence=0.5, horizon="2026-Q2",
        resolution_date=date(2026, 6, 30), resolution_criteria="c",
    ).assign_id()
    p2 = Prediction(
        statement="Later", rationale="r", confidence=0.5, horizon="2027-Q1",
        resolution_date=date(2027, 3, 31), resolution_criteria="c",
    ).assign_id()
    out = upcoming_resolutions([p2, p1], today=date(2026, 1, 1))
    assert out[0].statement == "Soon"


def test_verify_live_export_sync_ok():
    p = Prediction(
        statement="Sync test", rationale="r", confidence=0.5, horizon="2026-Q4",
        resolution_date=date(2026, 12, 31), resolution_criteria="c",
    ).assign_id()
    assert verify_live_export_sync([p], [p]) == []


def test_verify_live_export_detects_status_mismatch():
    p_db = Prediction(
        statement="Resolved live", rationale="r", confidence=0.7, horizon="2026-Q1",
        resolution_date=date(2026, 3, 31), resolution_criteria="c",
    ).assign_id()
    p_db.resolve(True, "facts")
    p_jsonl = Prediction(
        statement="Resolved live", rationale="r", confidence=0.7, horizon="2026-Q1",
        resolution_date=date(2026, 3, 31), resolution_criteria="c",
        status=Status.open,
    ).assign_id()
    p_jsonl.id = p_db.id
    errs = verify_live_export_sync([p_db], [p_jsonl])
    assert any("status mismatch" in e for e in errs)


def test_export_live_only_excludes_seed(tmp_path):
    import run

    _clean()
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([{
        "statement": "Curated seed row",
        "rationale": "r", "category": "macro", "confidence": 0.6,
        "horizon": "2026-Q4", "resolution_date": "2026-12-31",
        "resolution_criteria": "c", "status": "open",
    }]), encoding="utf-8")
    seed_p = Prediction.model_validate(json.loads(seed.read_text())[0]).assign_id()
    live_p = Prediction(
        statement="Daily LLM row",
        rationale="r", confidence=0.5, horizon="2027-Q2",
        resolution_date=date(2027, 6, 30), resolution_criteria="c",
    ).assign_id()
    Registry().add_many([seed_p, live_p])

    out = tmp_path / "live.jsonl"
    run.cmd_export(
        {"database_path": "data/forecaster.db"},
        str(out),
        seed_path=str(seed),
    )
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "Daily LLM row" in lines[0]
    assert "Curated seed row" not in lines[0]
    _clean()


def test_verify_export_cli(tmp_path):
    import run

    _clean()
    seed = tmp_path / "seed.json"
    seed.write_text("[]", encoding="utf-8")
    p = Prediction(
        statement="CLI verify", rationale="r", confidence=0.5, horizon="2026-Q4",
        resolution_date=date(2026, 12, 31), resolution_criteria="c",
    ).assign_id()
    Registry().add_many([p])
    out = tmp_path / "live.jsonl"
    run.cmd_export(
        {"database_path": "data/forecaster.db"},
        str(out),
        seed_path=str(seed),
    )
    run.cmd_verify_export(
        {"database_path": "data/forecaster.db"},
        str(out),
        seed_path=str(seed),
    )
    _clean()
