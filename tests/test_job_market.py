"""Offline tests for services/job_market.py (HR-1/HR-2)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import job_market as jm


BLS_FIXTURE = {
    "OEUS000015-2011100001": {"trend": 0.05, "latest": 100000},   # credit analyst — divergent (high risk KB)
    "OEUS000015-1011200001": {"trend": -0.06, "latest": 200000},  # software engineer — confirmed shrink
    "OEUS000027-4011100001": {"trend": -0.01, "latest": 50000},   # cashier — stable
}


def _sample_jobs():
    return [
        {"id": "fin_credit_analyst", "displacement_risk": 0.85},
        {"id": "tech_software_engineer", "displacement_risk": 0.75},
        {"id": "ret_cashier", "displacement_risk": 0.9},
        {"id": "fin_wealth_manager", "displacement_risk": 0.4},
    ]


def test_classify_agreement_confirmed_and_divergent():
    agree, badge = jm.classify_agreement(0.85, -0.05)
    assert agree == "confirmed"
    assert "Confirmed" in badge

    agree, badge = jm.classify_agreement(0.85, 0.05)
    assert agree == "divergent"
    assert "Divergence" in badge


def test_compute_calibration_delta_only_on_divergent():
    assert jm.compute_calibration_delta(0.85, 0.05, "divergent", blend_weight=0.3, max_delta=0.10) < 0
    assert jm.compute_calibration_delta(0.85, -0.05, "confirmed") == 0.0
    assert jm.compute_calibration_delta(0.85, 0.05, "divergent", max_delta=0.05) >= -0.05


def test_bls_source_fixture_offline():
    source = jm.BlsJobMarketSource()
    obs = source.fetch(["fin_credit_analyst"], fixture=BLS_FIXTURE)
    assert len(obs) == 1
    assert obs[0].source == "bls"
    assert obs[0].value == 0.05


def test_compare_observations_to_kb():
    jobs = _sample_jobs()
    source = jm.BlsJobMarketSource()
    obs = source.fetch([j["id"] for j in jobs], fixture=BLS_FIXTURE)
    comparisons = jm.compare_observations_to_kb(jobs, obs)
    assert comparisons["fin_credit_analyst"].agreement == "divergent"
    assert comparisons["tech_software_engineer"].agreement == "confirmed"


def test_merge_calibration_into_jobs():
    jobs = [{"id": "fin_credit_analyst", "displacement_risk": 0.85}]
    overlay = {
        "fin_credit_analyst": {
            "displacement_risk_base": 0.85,
            "displacement_risk_calibrated": 0.80,
            "delta": -0.05,
            "sources": [],
            "calibrated_at": "2026-06-23T00:00:00+00:00",
            "agreement": "divergent",
        }
    }
    merged = jm.merge_calibration_into_jobs(jobs, overlay)
    assert merged[0]["displacement_risk"] == 0.80
    assert merged[0]["market_calibration"]["delta"] == -0.05


def test_run_calibration_dry_run(tmp_path):
    kb = tmp_path / "jobs_kb.json"
    kb.write_text(
        json.dumps([{"id": "fin_credit_analyst", "displacement_risk": 0.85}]),
        encoding="utf-8",
    )
    cfg = {
        "job_market": {
            "enabled": True,
            "calibration": {
                "kb_path": str(kb),
                "writeback_mode": "overlay",
                "overlay_path": str(tmp_path / "overlay.json"),
                "blend_weight": 0.3,
                "max_delta": 0.10,
            },
        }
    }
    result = jm.run_calibration(cfg, dry_run=True, fixture=BLS_FIXTURE)
    assert result["status"] == "dry_run"
    assert result["updated"] >= 1
    overlay = result["overlay"]["fin_credit_analyst"]
    assert overlay["displacement_risk_calibrated"] < 0.85


def test_fetch_bls_series_offline_seed():
    series = jm.fetch_bls_series(
        list(jm.BLS_SERIES_MAP.keys()),
        cache_path="/nonexistent/bls_cache.json",
        seed_path="data/bls_market_seed.json",
    )
    assert len(series) == len(jm.BLS_SERIES_MAP)
    assert "OEUS000015-2011100001" in series


def test_load_calibration_overlay_falls_back_to_seed():
    overlay = jm.load_calibration_overlay(
        overlay_path="/nonexistent/kb_calibration.json",
        overlay_seed_path="data/kb_calibration_seed.json",
    )
    assert isinstance(overlay, dict)


def test_bls_verify_wrapper_compat():
    import bls_verify

    jobs = _sample_jobs()
    dashboard = bls_verify.compare_kb_to_bls(jobs)
    assert "fin_credit_analyst" in dashboard or isinstance(dashboard, dict)


# --- field-feedback calibration (P2) -----------------------------------------

def _field_jobs():
    return [
        {"id": "ret_cashier", "title": "Cashier", "displacement_risk": 0.40},
        {"id": "tech_dev", "title": "Software Developer", "displacement_risk": 0.30},
    ]


def test_field_calibration_no_data_is_noop():
    assert jm.compute_field_calibration(_field_jobs(), {}) == {}
    assert jm.compute_field_calibration(_field_jobs(), None) == {}


def test_field_calibration_min_responses_gate():
    metrics = {"Cashier": {"total_responses": 2, "empirical_displacement_rate": 0.9,
                           "average_confidence": 0.5}}
    # below the default min_responses=5 threshold → ignored
    assert jm.compute_field_calibration(_field_jobs(), metrics) == {}


def test_field_calibration_moves_toward_empirical_but_bounded():
    metrics = {"Cashier": {"total_responses": 50, "empirical_displacement_rate": 0.95,
                           "average_confidence": 0.4}}
    recs = jm.compute_field_calibration(_field_jobs(), metrics, max_delta=0.15)
    rec = recs["ret_cashier"]
    # empirical (0.95) > kb (0.40) → risk nudged UP, but capped by max_delta
    assert rec.delta > 0
    assert rec.delta <= 0.15
    assert rec.displacement_risk_calibrated > 0.40
    assert rec.displacement_risk_calibrated <= 0.40 + 0.15 + 1e-9


def test_field_calibration_shrinkage_small_sample_moves_less():
    big = {"Cashier": {"total_responses": 200, "empirical_displacement_rate": 0.9,
                       "average_confidence": 0.5}}
    small = {"Cashier": {"total_responses": 6, "empirical_displacement_rate": 0.9,
                         "average_confidence": 0.5}}
    d_big = jm.compute_field_calibration(_field_jobs(), big)["ret_cashier"].delta
    d_small = jm.compute_field_calibration(_field_jobs(), small)["ret_cashier"].delta
    assert abs(d_small) < abs(d_big)


def test_merge_field_calibration_into_jobs():
    metrics = {"Cashier": {"total_responses": 50, "empirical_displacement_rate": 0.95,
                           "average_confidence": 0.4}}
    recs = jm.compute_field_calibration(_field_jobs(), metrics)
    merged = jm.merge_field_calibration_into_jobs(_field_jobs(), recs)
    cashier = next(j for j in merged if j["id"] == "ret_cashier")
    assert cashier["displacement_risk"] == recs["ret_cashier"].displacement_risk_calibrated
    assert cashier["field_calibration"]["n_responses"] == 50
    # untouched job keeps its original risk and gains no calibration block
    dev = next(j for j in merged if j["id"] == "tech_dev")
    assert dev["displacement_risk"] == 0.30
    assert "field_calibration" not in dev
