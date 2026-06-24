"""Load config.yaml from project root (HR-3: thresholds live in config)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from paths import PROJECT_ROOT


def _apply_runtime_embedder_default(data: dict[str, Any]) -> None:
    """HF Space / explicit env must use semantic search; CI profile stays hashing."""
    jr = data.setdefault("job_radar", {})
    search = jr.setdefault("search", {})
    if os.getenv("JOB_RADAR_EMBEDDER"):
        search["embedder"] = os.environ["JOB_RADAR_EMBEDDER"]
    elif os.getenv("SPACE_ID"):
        search.setdefault("embedder", "sentence_transformers")
    cfg_path = os.getenv("FORECASTER_CONFIG", "")
    if cfg_path.endswith("config.ci.yaml"):
        search["embedder"] = "hashing"


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    data.setdefault("evolution", {"n_bootstrap": 50})
    data.setdefault("job_radar", {
        "alpha": 0.6,
        "beta": 0.4,
        "impact_threshold": 0.15,
        "kb_path": "data/jobs_kb.json",
    })
    _apply_runtime_embedder_default(data)
    data.setdefault("job_market", {
        "enabled": True,
        "sources": {"bls": {"enabled": True}},
        "calibration": {
            "writeback_mode": "overlay",
            "overlay_path": "data/kb_calibration.json",
        },
    })
    return data
