"""Offline tests for MCP tool handlers (no MCP runtime, no API key)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.mcp_handlers import (
    handle_get_calibration_scoreboard,
    handle_get_ood_assessment,
    handle_list_open_predictions,
    handle_search_jobs,
    parse_scenario_json,
)


def test_parse_scenario_json_merge():
    base = parse_scenario_json(None)
    assert base is None
    merged = parse_scenario_json('{"augmentation_ratio": 0.9}')
    assert merged["augmentation_ratio"] == 0.9


def test_parse_scenario_json_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown scenario keys"):
        parse_scenario_json('{"not_a_variable": 1}')


def test_handler_scoreboard_has_disclaimer():
    sb = handle_get_calibration_scoreboard()
    assert "total" in sb
    assert "disclaimer" in sb


def test_handler_ood_fast_bootstrap():
    result = handle_get_ood_assessment(n_bootstrap=5)
    assert "is_ood" in result
    assert "prompt_context" in result
    assert "disclaimer" in result


def test_handler_search_jobs_finance():
    result = handle_search_jobs(query="risk analyst", industry="Finance", limit=5)
    assert result["industry"] == "Finance"
    assert result["count"] <= 5
    assert "jobs" in result
    if result["jobs"]:
        assert "hybrid_score" in result["jobs"][0]


def test_handler_search_jobs_invalid_industry():
    with pytest.raises(ValueError, match="industry must be"):
        handle_search_jobs(industry="Invalid")


def test_handler_list_open_predictions():
    result = handle_list_open_predictions(limit=5)
    assert "predictions" in result
    assert result["count"] <= 5
    for p in result["predictions"]:
        assert "statement" in p
        assert "confidence" in p
