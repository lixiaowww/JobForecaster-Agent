"""Offline tests for mock LLM and bot command parsing."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["FORECASTER_MOCK_LLM"] = "1"

import forecast as fc
from schemas import Prediction
from bots.base import dispatch_command, parse_submit_line
from services.mock_llm import mock_llm_response


def test_mock_forecast_json():
    fc.set_mock_mode(True)
    preds = fc.generate_predictions([], "track", max_predictions=2)
    assert len(preds) >= 1
    assert preds[0].statement
    assert preds[0].confidence > 0


def test_mock_judge_ambiguous():
    fc.set_mock_mode(True)
    out, why = fc.judge_prediction(
        Prediction(
            statement="Test",
            rationale="r",
            confidence=0.5,
            horizon="2026",
            resolution_date=date.today(),
            resolution_criteria="c",
        ),
        [],
    )
    assert out is None
    assert "Mock" in why or why


def test_parse_submit_line():
    tid, prob, arg, urls = parse_submit_line(
        "abc123 0.4 | Because demand slows however grids bind therefore capex lags. | https://a.com,https://b.com"
    )
    assert tid == "abc123"
    assert prob == 0.4
    assert len(urls) == 2


def test_dispatch_help():
    msg = dispatch_command("user1", "/help", "")
    assert "contribute" in msg.lower()
