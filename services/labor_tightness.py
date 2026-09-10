"""Labour market tightness from JOLTS — how hard a job is to *get*, not just whether it survives.

Everything else this project measures is a stock: how many people hold an
occupation, and whether that number is falling. That answers "is this job
dying". It cannot answer "is this job hard to get", which is a property of the
*matching market* — the ratio of openings to the people chasing them — and is
what "red ocean vs blue ocean" actually means.

That ratio has a name and a theory. Market tightness θ = V/U is the central
object of Diamond–Mortensen–Pissarides search-and-matching (2010 Nobel), and
unlike employment it is a **leading** indicator: firms post before they hire,
so vacancies move ahead of headcount. The premise that every available signal
is lagging is true of the sources this project had, not of labour data in
general — JOLTS publishes openings, hires, quits and layoffs monthly, and none
of it was wired in.

**The honest limitation, stated up front:** JOLTS is published by *industry*,
never by occupation. There is no occupational vacancy series in the United
States. So everything here is the tide, not the boat — two occupations in the
same industry get the same tightness reading. Occupation-level differentiation
has to come from somewhere else (entry competition across skill-adjacent
occupations, computable from the KB's own transition graph). Callers get
``granularity: "industry"`` on every record so this cannot be forgotten.

JOLTS is also nonfarm by construction, so Agriculture has no series at all —
recorded as uncovered rather than approximated with a neighbour.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_CACHE_PATH = "data/jolts_cache.json"
_SEED_PATH = "data/jolts_seed.json"
_CACHE_MAX_AGE_DAYS = 25          # JOLTS is monthly; refresh a little under a month

# Unemployment level (CPS, seasonally adjusted, thousands) — the U in V/U.
UNEMPLOYMENT_SERIES = "LNS13000000"

# JOLTS data elements: (suffix, field name). Rates are comparable across
# industries; levels are needed for openings-per-hire and for θ.
ELEMENTS: dict[str, str] = {
    "JOR": "openings_rate",
    "QUR": "quits_rate",
    "HIR": "hires_rate",
    "LDR": "layoffs_rate",
    "JOL": "openings_level",
    "HIL": "hires_level",
}

TOTAL_NONFARM = "000000"

# KB ``industry`` → JOLTS industry code. JOLTS supersectors are NAICS-based
# while KB industries are colloquial, so a few of these are judgement calls and
# are commented as such. Every mapping is recorded on the output record, so a
# reader can always see which industry a number actually came from.
JOLTS_INDUSTRY: dict[str, tuple[str | None, str]] = {
    "Finance": ("510099", "Financial activities"),
    # Software and data roles live in NAICS 5415 (computer systems design),
    # which is inside Professional and business services — not Information.
    "Tech": ("540099", "Professional and business services"),
    # Legal services is NAICS 5411, also Professional and business services.
    "Legal": ("540099", "Professional and business services"),
    "Manufacturing": ("300000", "Manufacturing"),
    "Healthcare": ("620000", "Health care and social assistance"),
    "Education": ("610000", "Educational services"),
    "Retail": ("440000", "Retail trade"),
    # JOLTS publishes no standalone transportation/warehousing supersector;
    # 400000 (trade, transportation and utilities) is the narrowest that exists.
    "Logistics": ("400000", "Trade, transportation, and utilities"),
    "Construction": ("230000", "Construction"),
    "Hospitality": ("700000", "Leisure and hospitality"),
    "Government": ("900000", "Government"),
    "Media": ("510000", "Information"),
    # JOLTS is nonfarm. Agriculture is not under-sampled here, it is absent.
    "Agriculture": (None, "not covered — JOLTS is nonfarm by construction"),
}


def series_id(industry_code: str, element: str) -> str:
    """JTS + industry(6) + state(2) + area(5) + sizeclass(2) + element(3)."""
    return f"JTS{industry_code}000000000{element}"


@dataclass(frozen=True)
class IndustryTightness:
    """One industry's matching-market reading. All rates are percent."""
    kb_industry: str
    jolts_code: str | None
    jolts_label: str
    covered: bool
    openings_rate: float | None = None
    quits_rate: float | None = None
    hires_rate: float | None = None
    layoffs_rate: float | None = None
    openings_per_hire: float | None = None
    openings_momentum_6m: float | None = None
    worker_leverage: float | None = None
    verdict: str = "unknown"
    as_of: str = ""
    granularity: str = "industry"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# fetching (cache → live → committed seed, per HR-1)
# ---------------------------------------------------------------------------
def _read_json(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_is_fresh(cache: dict) -> bool:
    stamp = cache.get("_fetched_at", "")
    if not stamp:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return age.days < _CACHE_MAX_AGE_DAYS


def required_series() -> list[str]:
    """Every series this module needs: JOLTS elements per industry, plus U."""
    codes = {TOTAL_NONFARM}
    codes.update(c for c, _label in JOLTS_INDUSTRY.values() if c)
    out = [series_id(code, el) for code in sorted(codes) for el in ELEMENTS]
    out.append(UNEMPLOYMENT_SERIES)
    return out


def fetch_jolts(
    *,
    cache_path: str = _CACHE_PATH,
    seed_path: str = _SEED_PATH,
    allow_live: bool = True,
    start_year: str | None = None,
    end_year: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Resolve JOLTS + unemployment series: fresh cache → live API → seed.

    Returns ``{series_id: [{"year", "period", "value"}, ...]}`` newest first.
    Never raises and never leaves the caller without an answer: an offline run
    with no cache falls back to the committed seed, which is what keeps the
    test suite at zero network (HR-1).
    """
    cache = _read_json(cache_path)
    if _cache_is_fresh(cache):
        return {k: v for k, v in cache.items() if not k.startswith("_")}

    if allow_live:
        live = _fetch_live(required_series(), start_year, end_year)
        if live:
            payload = {**live, "_fetched_at": datetime.now(timezone.utc).isoformat()}
            try:
                Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                Path(cache_path).write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return live

    stale = {k: v for k, v in cache.items() if not k.startswith("_")}
    if stale:
        return stale
    return {k: v for k, v in _read_json(seed_path).items() if not k.startswith("_")}


# BLS v2 caps a single request at 50 series when registered and 25 when not.
# Over the cap it does not error — it answers 200 and silently returns only the
# first N, which reads as "those industries have no data". Chunking is what
# keeps a partial answer from being mistaken for a complete one.
_MAX_SERIES_REGISTERED = 50
_MAX_SERIES_ANONYMOUS = 25


def _fetch_live(
    series_ids: list[str],
    start_year: str | None,
    end_year: str | None,
) -> dict[str, list[dict[str, Any]]]:
    try:
        import requests
    except ImportError:
        return {}

    this_year = datetime.now(timezone.utc).year
    key = os.environ.get("BLS_API_KEY", "")
    chunk_size = _MAX_SERIES_REGISTERED if key else _MAX_SERIES_ANONYMOUS

    out: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(series_ids), chunk_size):
        chunk = series_ids[start:start + chunk_size]
        payload: dict[str, Any] = {
            "seriesid": chunk,
            "startyear": start_year or str(this_year - 2),
            "endyear": end_year or str(this_year),
            "catalog": False,
        }
        if key:
            payload["registrationkey"] = key
        try:
            resp = requests.post(_BLS_API_URL, json=payload, timeout=45)
            resp.raise_for_status()
            body = resp.json()
        except Exception:
            continue        # a bad chunk costs those series, not the whole run
        for series in body.get("Results", {}).get("series", []):
            rows = [
                {"year": d.get("year"), "period": d.get("period"),
                 "value": d.get("value")}
                for d in series.get("data", [])
            ]
            if rows:
                out[series["seriesID"]] = rows
    return out


def _latest(series: list[dict[str, Any]] | None) -> float | None:
    if not series:
        return None
    try:
        return float(str(series[0].get("value", "")).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _value_at(series: list[dict[str, Any]] | None, months_ago: int) -> float | None:
    if not series or len(series) <= months_ago:
        return None
    try:
        return float(str(series[months_ago].get("value", "")).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_of(series: list[dict[str, Any]] | None) -> str:
    if not series:
        return ""
    row = series[0]
    return f"{row.get('year', '')}-{row.get('period', '')}"


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def market_tightness(data: dict[str, list[dict]] | None = None) -> dict[str, Any]:
    """Economy-wide θ = V/U, the standard measure of how tight hiring is.

    θ > 1 means there are more openings than unemployed people looking — a
    worker's market in aggregate. This is the single number the rest of the
    module is relative to, and the only one here with a settled theoretical
    interpretation (Diamond–Mortensen–Pissarides).
    """
    data = data if data is not None else fetch_jolts()
    openings = data.get(series_id(TOTAL_NONFARM, "JOL"))
    unemployed = data.get(UNEMPLOYMENT_SERIES)
    v = _latest(openings)
    u = _latest(unemployed)
    theta = round(v / u, 4) if v and u else None
    return {
        "theta": theta,
        "openings_thousands": v,
        "unemployed_thousands": u,
        "openings_as_of": _as_of(openings),
        "unemployment_as_of": _as_of(unemployed),
        "interpretation": (
            None if theta is None
            else "more openings than job seekers (worker's market)" if theta > 1
            else "more job seekers than openings (employer's market)"
        ),
    }


def _industry_metrics(code: str, data: dict[str, list[dict]]) -> dict[str, Any]:
    got = {field: _latest(data.get(series_id(code, el)))
           for el, field in ELEMENTS.items()}

    openings_level = got.get("openings_level")
    hires_level = got.get("hires_level")
    got["openings_per_hire"] = (
        round(openings_level / hires_level, 3)
        if openings_level and hires_level else None
    )

    # Momentum on the openings *level*: vacancies lead employment, so their
    # direction is the closest thing here to a forward signal.
    six_ago = _value_at(data.get(series_id(code, "JOL")), 6)
    got["openings_momentum_6m"] = (
        round((openings_level - six_ago) / six_ago, 4)
        if openings_level and six_ago else None
    )
    got["as_of"] = _as_of(data.get(series_id(code, "JOR")))
    return got


def worker_leverage(metrics: dict[str, Any], baseline: dict[str, Any]) -> float | None:
    """How much leverage a worker has in this industry, 1.0 = the whole economy.

    Three ratios that all favour the worker when high, averaged, then penalised
    for excess layoff risk:

    * **openings rate** — how much unmet demand there is;
    * **quits rate** — the cleanest worker-side read on tightness. People quit
      when they believe they can replace the job, so this is revealed
      confidence rather than stated intent;
    * **openings per hire** — postings burned per actual hire. High means
      employers cannot fill roles, which is precisely a blue ocean for whoever
      is applying.

    The weights are a prior, not a result — exactly like the stakes in
    ``services/job_query_agent/claims.py``, and for the same reason. They are
    written down so that a track record can eventually say they were wrong;
    an index nobody can grade is decoration.
    """
    parts: list[float] = []
    for field in ("openings_rate", "quits_rate", "openings_per_hire"):
        mine, base = metrics.get(field), baseline.get(field)
        if mine and base:
            parts.append(mine / base)
    if not parts:
        return None

    score = sum(parts) / len(parts)
    mine, base = metrics.get("layoffs_rate"), baseline.get("layoffs_rate")
    if mine and base:
        score -= max(0.0, mine / base - 1.0) * 0.5
    return round(score, 3)


def classify_ocean(leverage: float | None) -> str:
    """Blue ocean = easier to get hired than the economy at large."""
    if leverage is None:
        return "unknown"
    if leverage >= 1.10:
        return "blue_ocean"
    if leverage <= 0.90:
        return "red_ocean"
    return "balanced"


def industry_tightness(
    data: dict[str, list[dict]] | None = None,
) -> dict[str, IndustryTightness]:
    """Tightness for every KB industry, keyed by the KB's own ``industry`` value."""
    data = data if data is not None else fetch_jolts()
    baseline = _industry_metrics(TOTAL_NONFARM, data)

    out: dict[str, IndustryTightness] = {}
    for kb_industry, (code, label) in JOLTS_INDUSTRY.items():
        if code is None:
            out[kb_industry] = IndustryTightness(
                kb_industry=kb_industry, jolts_code=None, jolts_label=label,
                covered=False, verdict="not_covered",
            )
            continue
        m = _industry_metrics(code, data)
        leverage = worker_leverage(m, baseline)
        out[kb_industry] = IndustryTightness(
            kb_industry=kb_industry,
            jolts_code=code,
            jolts_label=label,
            covered=True,
            openings_rate=m.get("openings_rate"),
            quits_rate=m.get("quits_rate"),
            hires_rate=m.get("hires_rate"),
            layoffs_rate=m.get("layoffs_rate"),
            openings_per_hire=m.get("openings_per_hire"),
            openings_momentum_6m=m.get("openings_momentum_6m"),
            worker_leverage=leverage,
            verdict=classify_ocean(leverage),
            as_of=m.get("as_of", ""),
        )
    return out


def tightness_for_jobs(
    jobs: list[dict],
    data: dict[str, list[dict]] | None = None,
) -> dict[str, IndustryTightness]:
    """Map each KB row id to its industry's tightness reading.

    Every row in an industry gets the same numbers — see the module docstring.
    This is deliberately not hidden behind a per-job score, because a per-job
    number would imply an occupational resolution that JOLTS does not have.
    """
    by_industry = industry_tightness(data)
    unknown = IndustryTightness(
        kb_industry="", jolts_code=None,
        jolts_label="no JOLTS mapping for this KB industry",
        covered=False, verdict="not_covered",
    )
    return {
        job["id"]: by_industry.get(job.get("industry", ""), unknown)
        for job in jobs
    }


def tightness_report(
    jobs: list[dict] | None = None,
    data: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """Everything the CLI, the dashboard and the forecast prompt need."""
    data = data if data is not None else fetch_jolts()
    by_industry = industry_tightness(data)
    ranked = sorted(
        (t for t in by_industry.values() if t.worker_leverage is not None),
        key=lambda t: t.worker_leverage,
        reverse=True,
    )
    return {
        "market": market_tightness(data),
        "granularity": "industry",
        # The measured components are the trustworthy part. ``worker_leverage``
        # combines them with weights that were chosen, not derived — most
        # visibly the layoff penalty, which is what puts Tech in the red ocean
        # despite it having the highest openings rate of any industry here.
        # Flagged in the payload so no consumer treats the composite as data.
        "worker_leverage_weights_are_a_prior": True,
        "caveat": (
            "JOLTS publishes vacancies by industry only; there is no "
            "occupational vacancy series. Occupations within an industry share "
            "these numbers."
        ),
        "industries": [t.to_dict() for t in ranked],
        "uncovered": [
            t.kb_industry for t in by_industry.values() if not t.covered
        ],
        "jobs": (
            {jid: t.verdict for jid, t in tightness_for_jobs(jobs, data).items()}
            if jobs else {}
        ),
    }
