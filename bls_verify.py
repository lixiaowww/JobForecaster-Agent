"""P2.1 — BLS Public API Verification (dashboard badges).

Thin wrapper over `services.job_market` (HR-2: pure core lives there).
"""
from __future__ import annotations

from services import job_market as jm


def fetch_series(series_ids: list[str], start_year: str = "2022", end_year: str = "2024") -> dict:
    """Fetch BLS time series data. Falls back to data/bls_market_seed.json offline."""
    return jm.fetch_bls_series(
        series_ids,
        start_year=start_year,
        end_year=end_year,
        cache_path="data/bls_cache.json",
        seed_path="data/bls_market_seed.json",
    )


def compare_kb_to_bls(kb_jobs: list[dict]) -> dict[str, dict]:
    """Compare KB displacement risk against BLS employment trends."""
    mapped_ids = list(jm.BLS_SERIES_MAP.values())
    source = jm.BlsJobMarketSource(start_year="2022", end_year="2024")
    observations = source.fetch(mapped_ids)
    comparisons = jm.compare_observations_to_kb(kb_jobs, observations)
    return jm.comparisons_for_dashboard(kb_jobs, comparisons)
