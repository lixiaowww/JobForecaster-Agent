"""Shared pytest fixtures for the forecaster-agent test suite.

Harness rule HR-1: offline-first, no API keys required.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path before any imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from schemas import make_engine
from registry import Registry


@pytest.fixture()
def isolated_db(tmp_path):
    """A temporary SQLite file that is deleted after the test.

    Use this when you need a fully clean Registry without any seed data or
    inter-test state from the shared production DB.

    Usage::

        def test_something(isolated_db):
            reg = Registry(engine=isolated_db)
            reg.add_many([...])
            ...
    """
    eng = make_engine(tmp_path / "test.db")
    yield eng
    # tmp_path is cleaned up by pytest automatically


@pytest.fixture()
def isolated_registry(isolated_db):
    """A Registry backed by a fresh, test-local SQLite engine.

    Equivalent to ``Registry(engine=isolated_db)`` but more ergonomic.

    Usage::

        def test_something(isolated_registry):
            isolated_registry.add_many([...])
            assert isolated_registry.scoreboard()["total"] == 1
    """
    return Registry(engine=isolated_db)


@pytest.fixture(autouse=True)
def _no_search_log_writes_to_production(tmp_path, monkeypatch):
    """Keep the test suite out of ``data/radar_search_log.jsonl`` (HR-1).

    ``ui/tabs/radar.py`` records every search to the production log, so any
    test that renders the radar tab with a query used to append real-looking
    rows to it. That was untidy before; it is a correctness problem now that
    ``services/job_query_agent/claims.py`` reads that log as *external
    evidence* when grading the agent's own patches — a test run could
    manufacture the corroboration a claim needs.

    Redirects only the default destination: calls that pass an explicit
    ``path`` (most of ``test_job_query_agent.py``) are untouched.
    """
    from services.job_query_agent import search_log as _sl

    real = _sl.record_search_log
    default_dest = tmp_path / "radar_search_log.jsonl"

    def _redirected(query, *, path=None, **kwargs):
        return real(query, path=path or default_dest, **kwargs)

    monkeypatch.setattr(_sl, "record_search_log", _redirected)
    yield
