"""Offline tests for REST API (TestClient — no live server, no API key)."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure open auth for tests
os.environ.pop("FORECASTER_API_KEY", None)

from api_server import app

client = TestClient(app)


def test_health_open():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["auth"] == "open"


def test_scoreboard():
    r = client.get("/v1/scoreboard")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "disclaimer" in data


def test_ood_get_fast():
    r = client.get("/v1/ood", params={"n_bootstrap": 5})
    assert r.status_code == 200
    assert "is_ood" in r.json()


def test_ood_post_scenario():
    r = client.post(
        "/v1/ood",
        json={"scenario": {"augmentation_ratio": 0.9}, "n_bootstrap": 5},
    )
    assert r.status_code == 200
    assert "prompt_context" in r.json()


def test_jobs_search_get():
    r = client.get("/v1/jobs/search", params={"query": "analyst", "industry": "Finance", "limit": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["industry"] == "Finance"
    assert data["count"] <= 3


def test_jobs_search_post():
    r = client.post(
        "/v1/jobs/search",
        json={"query": "engineer", "industry": "Tech", "limit": 5},
    )
    assert r.status_code == 200
    assert "jobs" in r.json()


def test_jobs_search_bad_industry():
    r = client.get("/v1/jobs/search", params={"industry": "NotReal"})
    assert r.status_code == 400


def test_predictions_open():
    r = client.get("/v1/predictions/open", params={"limit": 5})
    assert r.status_code == 200
    assert "predictions" in r.json()


def test_openapi_schema():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "forecaster-agent API"
    assert "/v1/scoreboard" in schema["paths"]


def test_api_key_required(monkeypatch):
    monkeypatch.setenv("FORECASTER_API_KEY", "test-secret-key")
    # Re-import auth check uses env at call time — configured_api_key reads env each time
    r = client.get("/health")
    assert r.status_code == 401
    r2 = client.get("/health", headers={"X-API-Key": "test-secret-key"})
    assert r2.status_code == 200
    monkeypatch.delenv("FORECASTER_API_KEY", raising=False)


def test_contribution_flow_api():
    from datetime import date, timedelta
    from sqlmodel import Session, delete

    from registry import Registry
    from schemas import Contribution, CrowdSnapshot, Prediction, engine

    with Session(engine) as session:
        session.exec(delete(Contribution))
        session.exec(delete(CrowdSnapshot))
        session.exec(delete(Prediction))
        session.commit()

    p = Prediction(
        statement="API test prediction for crowd flow",
        rationale="hidden agent rationale",
        confidence=0.65,
        horizon="2027-Q1",
        resolution_date=date.today() + timedelta(days=90),
        resolution_criteria="Public filings.",
    ).assign_id()
    Registry().add_many([p])

    blind = client.get(f"/v1/predictions/{p.id}/contribute")
    assert blind.status_code == 200
    assert "confidence" not in blind.json()

    post = client.post(
        f"/v1/predictions/{p.id}/contributions",
        json={
            "contributor_id": "api_tester",
            "probability": 0.4,
            "argument": "Because constraints bind however demand grows therefore spending lags since queues persist.",
            "evidence_urls": ["https://example.com/report"],
        },
    )
    assert post.status_code == 200
    assert "aggregate_probability" not in post.json()

    crowd = client.get(
        f"/v1/predictions/{p.id}/crowd",
        params={"contributor_id": "api_tester"},
    )
    assert crowd.status_code == 200
    assert "aggregate_probability" in crowd.json()

    forbidden = client.get(
        f"/v1/predictions/{p.id}/crowd",
        params={"contributor_id": "not_submitted"},
    )
    assert forbidden.status_code == 403
