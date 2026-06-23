"""Dashboard seed data for empty registry (HF Spaces)."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete

from paths import PROJECT_ROOT
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


def test_seed_is_an_honest_sourced_track_record():
    """Guard the credibility of the public demo's track record:
    enough resolved bets, a non-trivial number of MISSES (no fake perfection),
    real source URLs, and a mean Brier that beats the 0.25 random baseline."""
    raw = json.loads((PROJECT_ROOT / "data" / "predictions_seed.json").read_text())
    resolved = [r for r in raw if r.get("status", "").startswith("resolved_")]
    misses = [r for r in resolved if r.get("outcome") is False]
    sourced = [r for r in raw if r.get("sources")]

    assert len(resolved) >= 8, "track record too thin to be credible"
    assert len(misses) >= 2, "a track record with zero misses is not believable"
    assert len(sourced) >= 6, "resolved bets should cite verifiable sources"

    briers = [
        (r["confidence"] - (1.0 if r["outcome"] else 0.0)) ** 2 for r in resolved
    ]
    mean_brier = sum(briers) / len(briers)
    assert mean_brier < 0.25, "must beat the random-coin-flip baseline"
    # but not suspiciously perfect (would imply cherry-picking)
    assert mean_brier > 0.05, "implausibly perfect — likely cherry-picked"

    # every resolved bet must explain *why* it resolved that way
    for r in resolved:
        assert r.get("judged_rationale"), f"missing rationale: {r['statement'][:40]}"
