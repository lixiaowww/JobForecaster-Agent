"""Offline tests for services/read_model.py (HR-1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crowd import HashingEmbedder
from services.read_model import get_ood_assessment, get_scoreboard, search_jobs


def test_read_model_ood_offline():
    result = get_ood_assessment(n_bootstrap=5)
    assert "is_ood" in result
    assert "prompt_context" in result
    assert "OUTSIDE HISTORY" in result["prompt_context"] or "within historical" in result["prompt_context"]


def test_read_model_search_jobs_offline():
    jobs = search_jobs(query="analyst", industry="finance", embedder=HashingEmbedder())
    assert isinstance(jobs, list)
    if jobs:
        assert "hybrid_score" in jobs[0]


def test_read_model_scoreboard():
    sb = get_scoreboard()
    assert "total" in sb
    assert "mean_brier" in sb
