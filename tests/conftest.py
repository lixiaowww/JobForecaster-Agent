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
