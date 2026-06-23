"""Job market calibration — BLS employment trends vs KB displacement risk (HR-1/2/3).

Not part of macro `ingest.py` signals. Calibrates Job Radar KB via explicit writeback.
Indeed/LinkedIn scraping is out of scope; only official APIs (BLS) are supported.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

from paths import PROJECT_ROOT

# BLS OES national employment level series → KB job IDs
BLS_SERIES_MAP: dict[str, str] = {
    "OEUS000015-2011100001": "fin_credit_analyst",
    "OEUS000023-2011200001": "fin_financial_advisor",
    "OEUS000015-1011200001": "tech_software_engineer",
    "OEUS000011-2911200001": "hlt_radiologist",
    "OEUS000023-2312300001": "leg_paralegal",
    "OEUS000027-4011100001": "ret_cashier",
    "OEUS000025-4131100001": "log_truck_driver",
}

_BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


@dataclass(frozen=True)
class MarketObservation:
    job_id: str
    source: str
    metric: str
    value: float
    as_of: str
    confidence: float = 1.0


@dataclass(frozen=True)
class KbComparison:
    job_id: str
    kb_displacement_risk: float
    market_trend: float | None
    agreement: str  # confirmed | divergent | unknown
    badge: str


@dataclass(frozen=True)
class CalibrationRecord:
    displacement_risk_base: float
    displacement_risk_calibrated: float
    delta: float
    sources: list[dict[str, Any]]
    calibrated_at: str
    agreement: str


class JobMarketSource(Protocol):
    name: str

    def fetch(
        self,
        job_ids: list[str],
        *,
        fixture: dict[str, Any] | None = None,
    ) -> list[MarketObservation]: ...


def default_calibration_config(cfg: dict | None = None) -> dict[str, Any]:
    """Merge user config with Harness defaults (HR-3)."""
    root = cfg or {}
    jm = root.get("job_market") or {}
    cal = jm.get("calibration") or {}
    bls = jm.get("sources", {}).get("bls") or {}
    return {
        "enabled": jm.get("enabled", True),
        "trend_threshold": cal.get("trend_threshold", 0.02),
        "high_risk_cutoff": cal.get("high_risk_cutoff", 0.6),
        "low_risk_cutoff": cal.get("low_risk_cutoff", 0.4),
        "max_delta": cal.get("max_delta", 0.10),
        "blend_weight": cal.get("blend_weight", 0.3),
        "writeback_mode": cal.get("writeback_mode", "overlay"),
        "kb_path": cal.get("kb_path", root.get("job_radar", {}).get("kb_path", "data/jobs_kb.json")),
        "overlay_path": cal.get("overlay_path", "data/kb_calibration.json"),
        "log_path": cal.get("log_path", "data/kb_calibration_log.jsonl"),
        "bls_start_year": bls.get("start_year", "2022"),
        "bls_end_year": bls.get("end_year", "2024"),
        "bls_cache_path": bls.get("cache_path", "data/bls_cache.json"),
        "bls_seed_path": bls.get("seed_path", "data/bls_market_seed.json"),
        "overlay_seed_path": cal.get("overlay_seed_path", "data/kb_calibration_seed.json"),
    }


class BlsJobMarketSource:
    """BLS OES employment level trends (public API, offline-safe)."""

    name = "bls"

    def __init__(
        self,
        start_year: str = "2022",
        end_year: str = "2024",
        cache_path: str = "data/bls_cache.json",
        seed_path: str = "data/bls_market_seed.json",
    ):
        self.start_year = start_year
        self.end_year = end_year
        self.cache_path = cache_path
        self.seed_path = seed_path

    def fetch(
        self,
        job_ids: list[str],
        *,
        fixture: dict[str, Any] | None = None,
    ) -> list[MarketObservation]:
        if fixture is not None:
            series_data = fixture
        else:
            wanted = [sid for sid, jid in BLS_SERIES_MAP.items() if jid in job_ids or not job_ids]
            series_data = fetch_bls_series(
                wanted or list(BLS_SERIES_MAP.keys()),
                start_year=self.start_year,
                end_year=self.end_year,
                cache_path=self.cache_path,
                seed_path=self.seed_path,
            )

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out: list[MarketObservation] = []
        for series_id, kb_id in BLS_SERIES_MAP.items():
            if job_ids and kb_id not in job_ids:
                continue
            entry = series_data.get(series_id)
            if not entry or entry.get("trend") is None:
                continue
            out.append(
                MarketObservation(
                    job_id=kb_id,
                    source="bls",
                    metric="employment_trend",
                    value=float(entry["trend"]),
                    as_of=as_of,
                    confidence=1.0,
                )
            )
        return out


def fetch_bls_series(
    series_ids: list[str],
    start_year: str = "2022",
    end_year: str = "2024",
    cache_path: str = "data/bls_cache.json",
    seed_path: str = "data/bls_market_seed.json",
) -> dict[str, dict[str, Any]]:
    """Resolve BLS series: fresh cache → live API → committed local seed (HR-1)."""
    cache = _load_bls_cache(cache_path)
    if cache:
        return _pick_series(cache, series_ids)

    live = _fetch_bls_live(series_ids, start_year, end_year)
    if live:
        _save_bls_cache(cache_path, live)
        return _pick_series(live, series_ids)

    seed = _load_bls_seed(seed_path)
    return _pick_series(seed, series_ids)


def _fetch_bls_live(series_ids: list[str], start_year: str, end_year: str) -> dict[str, dict[str, Any]]:
    try:
        import requests

        payload = {
            "seriesid": series_ids,
            "startyear": start_year,
            "endyear": end_year,
            "catalog": False,
        }
        resp = requests.post(_BLS_API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, dict[str, Any]] = {}
        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            values = series.get("data", [])
            if len(values) < 2:
                continue
            latest_val = _safe_int(values[0].get("value"))
            oldest_val = _safe_int(values[-1].get("value"))
            if latest_val is None or oldest_val is None or oldest_val == 0:
                continue
            trend = (latest_val - oldest_val) / oldest_val
            result[sid] = {"trend": round(trend, 4), "latest": latest_val}
        return result
    except Exception:
        return {}


def classify_agreement(
    kb_risk: float,
    market_trend: float | None,
    *,
    trend_threshold: float = 0.02,
    high_risk_cutoff: float = 0.6,
    low_risk_cutoff: float = 0.4,
) -> tuple[str, str]:
    """Pure comparison logic shared by dashboard badges and calibration."""
    if market_trend is None:
        return "unknown", "🔷 BLS Unavailable"

    if kb_risk >= high_risk_cutoff and market_trend < -trend_threshold:
        return "confirmed", "✅ BLS Confirmed"
    if kb_risk < low_risk_cutoff and market_trend > trend_threshold:
        return "confirmed", "✅ BLS Confirmed"
    if abs(market_trend) < trend_threshold:
        return "unknown", "🔷 BLS Stable"
    return "divergent", "⚠️ BLS Divergence"


def compare_observations_to_kb(
    kb_jobs: list[dict],
    observations: list[MarketObservation],
    *,
    trend_threshold: float = 0.02,
    high_risk_cutoff: float = 0.6,
    low_risk_cutoff: float = 0.4,
) -> dict[str, KbComparison]:
    """Compare KB displacement risk to market observations (HR-2 pure)."""
    kb_map = {j["id"]: j for j in kb_jobs if j.get("id")}
    by_job: dict[str, list[MarketObservation]] = {}
    for obs in observations:
        by_job.setdefault(obs.job_id, []).append(obs)

    result: dict[str, KbComparison] = {}
    for job_id, obs_list in by_job.items():
        job = kb_map.get(job_id)
        if not job:
            continue
        bls_obs = next((o for o in obs_list if o.source == "bls" and o.metric == "employment_trend"), None)
        kb_risk = float(job.get("displacement_risk", 0.5))
        trend = bls_obs.value if bls_obs else None
        agreement, badge = classify_agreement(
            kb_risk,
            trend,
            trend_threshold=trend_threshold,
            high_risk_cutoff=high_risk_cutoff,
            low_risk_cutoff=low_risk_cutoff,
        )
        result[job_id] = KbComparison(
            job_id=job_id,
            kb_displacement_risk=kb_risk,
            market_trend=trend,
            agreement=agreement,
            badge=badge,
        )
    return result


def compute_calibration_delta(
    kb_risk: float,
    market_trend: float | None,
    agreement: str,
    *,
    blend_weight: float = 0.3,
    max_delta: float = 0.10,
    trend_threshold: float = 0.02,
    high_risk_cutoff: float = 0.6,
    low_risk_cutoff: float = 0.4,
) -> float:
    """Compute bounded adjustment; only divergent agreements move the needle."""
    if agreement != "divergent" or market_trend is None:
        return 0.0

    delta = 0.0
    if kb_risk >= high_risk_cutoff and market_trend > trend_threshold:
        # KB high risk but employment growing → nudge risk down
        delta = -blend_weight * abs(market_trend)
    elif kb_risk < low_risk_cutoff and market_trend < -trend_threshold:
        # KB low risk but employment shrinking → nudge risk up
        delta = blend_weight * abs(market_trend)

    return max(-max_delta, min(max_delta, round(delta, 4)))


def build_calibration_record(
    job: dict,
    comparison: KbComparison,
    observations: list[MarketObservation],
    cal_cfg: dict[str, Any],
) -> CalibrationRecord | None:
    """Build a calibration record for one job; None if no change."""
    kb_risk = float(job.get("displacement_risk", 0.5))
    delta = compute_calibration_delta(
        kb_risk,
        comparison.market_trend,
        comparison.agreement,
        blend_weight=cal_cfg["blend_weight"],
        max_delta=cal_cfg["max_delta"],
        trend_threshold=cal_cfg["trend_threshold"],
        high_risk_cutoff=cal_cfg["high_risk_cutoff"],
        low_risk_cutoff=cal_cfg["low_risk_cutoff"],
    )

    job_obs = [o for o in observations if o.job_id == comparison.job_id]
    sources = [
        {
            "name": o.source,
            "metric": o.metric,
            "value": o.value,
            "as_of": o.as_of,
            "agreement": comparison.agreement,
        }
        for o in job_obs
    ]

    calibrated = round(max(0.0, min(1.0, kb_risk + delta)), 4)
    if delta == 0.0:
        return None

    return CalibrationRecord(
        displacement_risk_base=kb_risk,
        displacement_risk_calibrated=calibrated,
        delta=delta,
        sources=sources,
        calibrated_at=datetime.now(timezone.utc).isoformat(),
        agreement=comparison.agreement,
    )


def comparisons_for_dashboard(kb_jobs: list[dict], comparisons: dict[str, KbComparison]) -> dict[str, dict]:
    """Shape for `bls_verify.compare_kb_to_bls` backward compatibility."""
    out: dict[str, dict] = {}
    kb_ids = {j["id"] for j in kb_jobs if j.get("id")}
    for job_id in kb_ids:
        if job_id in comparisons:
            c = comparisons[job_id]
            out[job_id] = {
                "kb_displacement_risk": c.kb_displacement_risk,
                "bls_trend": c.market_trend,
                "agreement": c.agreement,
                "badge": c.badge,
            }
        elif job_id in set(BLS_SERIES_MAP.values()):
            job = next(j for j in kb_jobs if j.get("id") == job_id)
            agreement, badge = classify_agreement(
                float(job.get("displacement_risk", 0.5)),
                None,
            )
            out[job_id] = {
                "kb_displacement_risk": float(job.get("displacement_risk", 0.5)),
                "bls_trend": None,
                "agreement": agreement,
                "badge": badge,
            }
    return out


def load_calibration_overlay(
    overlay_path: str | Path | None = None,
    overlay_seed_path: str | Path | None = None,
) -> dict[str, dict]:
    """Runtime overlay first, then committed seed overlay (offline RAG layer)."""
    path = _resolve_path(overlay_path or "data/kb_calibration.json")
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data:
                return data
        except Exception:
            pass

    seed_overlay = _resolve_path(overlay_seed_path or "data/kb_calibration_seed.json")
    if seed_overlay.is_file():
        try:
            return json.loads(seed_overlay.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def merge_calibration_into_jobs(jobs: list[dict], overlay: dict[str, dict] | None = None) -> list[dict]:
    """Apply overlay so UI/scoring see calibrated displacement risk."""
    if overlay is None:
        overlay = load_calibration_overlay()
    if not overlay:
        return jobs

    merged: list[dict] = []
    for job in jobs:
        copy = dict(job)
        mc = overlay.get(copy.get("id", ""))
        if mc:
            copy["market_calibration"] = mc
            cal_risk = mc.get("displacement_risk_calibrated")
            if cal_risk is not None:
                copy["displacement_risk"] = cal_risk
        merged.append(copy)
    return merged


def write_calibration_overlay(
    records: dict[str, CalibrationRecord],
    overlay_path: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, dict]:
    """Persist calibration overlay JSON."""
    payload = {jid: asdict(rec) for jid, rec in records.items()}
    if dry_run:
        return payload

    path = _resolve_path(overlay_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def append_calibration_log(
    entries: list[dict[str, Any]],
    log_path: str | Path,
    *,
    dry_run: bool = False,
) -> None:
    if dry_run or not entries:
        return
    path = _resolve_path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_calibration(
    cfg: dict | None = None,
    *,
    dry_run: bool = False,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch BLS observations, compute deltas, write overlay (or dry-run)."""
    cal_cfg = default_calibration_config(cfg)
    if not cal_cfg["enabled"]:
        return {"status": "disabled", "updated": 0}

    kb_path = _resolve_path(cal_cfg["kb_path"])
    if not kb_path.is_file():
        return {"status": "error", "message": f"KB not found: {kb_path}", "updated": 0}

    jobs = json.loads(kb_path.read_text(encoding="utf-8"))
    mapped_ids = list(BLS_SERIES_MAP.values())

    source = BlsJobMarketSource(
        start_year=cal_cfg["bls_start_year"],
        end_year=cal_cfg["bls_end_year"],
        cache_path=cal_cfg["bls_cache_path"],
        seed_path=cal_cfg["bls_seed_path"],
    )
    observations = source.fetch(mapped_ids, fixture=fixture)
    comparisons = compare_observations_to_kb(
        jobs,
        observations,
        trend_threshold=cal_cfg["trend_threshold"],
        high_risk_cutoff=cal_cfg["high_risk_cutoff"],
        low_risk_cutoff=cal_cfg["low_risk_cutoff"],
    )

    kb_map = {j["id"]: j for j in jobs if j.get("id")}
    records: dict[str, CalibrationRecord] = {}
    log_entries: list[dict[str, Any]] = []

    for job_id, comparison in comparisons.items():
        job = kb_map.get(job_id)
        if not job:
            continue
        rec = build_calibration_record(job, comparison, observations, cal_cfg)
        if rec is None:
            continue
        records[job_id] = rec
        log_entries.append({"job_id": job_id, **asdict(rec)})

    mode = cal_cfg["writeback_mode"]
    if mode == "dry_run" or dry_run:
        payload = {jid: asdict(r) for jid, r in records.items()}
        return {
            "status": "dry_run",
            "updated": len(records),
            "overlay": payload,
            "comparisons": {k: asdict(v) for k, v in comparisons.items()},
        }

    if mode == "inline":
        _write_inline_calibration(jobs, records, kb_path, dry_run=False)
    else:
        write_calibration_overlay(records, cal_cfg["overlay_path"])

    append_calibration_log(log_entries, cal_cfg["log_path"])

    return {
        "status": "ok",
        "updated": len(records),
        "writeback_mode": mode,
        "overlay_path": cal_cfg["overlay_path"] if mode == "overlay" else str(kb_path),
    }


def _write_inline_calibration(
    jobs: list[dict],
    records: dict[str, CalibrationRecord],
    kb_path: Path,
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    for job in jobs:
        jid = job.get("id")
        if jid in records:
            job["market_calibration"] = asdict(records[jid])
            job["displacement_risk"] = records[jid].displacement_risk_calibrated
    kb_path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def _pick_series(data: dict[str, dict[str, Any]], series_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not data:
        return {}
    if not series_ids:
        return data
    return {sid: entry for sid, entry in data.items() if sid in series_ids}


def _load_bls_seed(seed_path: str) -> dict[str, dict[str, Any]]:
    path = _resolve_path(seed_path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "series" in raw:
            return raw["series"]
        return raw
    except Exception:
        return {}


def _load_bls_cache(cache_path: str) -> dict:
    path = _resolve_path(cache_path)
    if not path.is_file():
        return {}
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime >= 86400:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data:
            return {}
        return data
    except Exception:
        return {}


def _save_bls_cache(cache_path: str, data: dict) -> None:
    path = _resolve_path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None
