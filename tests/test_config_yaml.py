"""Ensure config.yaml is valid YAML (prevents dashboard boot failures)."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import PROJECT_ROOT


def test_config_yaml_parses():
    cfg_path = PROJECT_ROOT / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["job_market"]["enabled"] is True
    assert data["job_market"]["sources"]["bls"]["seed_path"] == "data/bls_market_seed.json"
    assert data["job_market"]["calibration"]["overlay_seed_path"] == "data/kb_calibration_seed.json"


def test_config_ci_yaml_parses():
    data = yaml.safe_load((PROJECT_ROOT / "config.ci.yaml").read_text(encoding="utf-8"))
    assert data["require_review"] is False
    assert data["publish"]["file"]["out_dir"] == "site"
