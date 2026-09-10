"""Occupation-level entry competition — bringing industry tightness down to the job.

``services/labor_tightness.py`` answers "how tight is this *industry*". It
cannot go finer, because there is no occupational vacancy series. This module
supplies the missing dimension from the other side of the market: not how many
openings there are, but **how many people could plausibly take them**.

Red ocean is not "many applicants" in the abstract. It is *many adjacent
workers per opening* — people already holding an occupation similar enough that
moving in is realistic. Two occupations in the same industry, facing the same
vacancy rate, are very different propositions if one has ten adjacent
occupations feeding into it and the other has none.

Why not the KB's own ``transition_targets``
-------------------------------------------
The obvious move is to use the transition graph already in the KB. Measured on
it, that would have been a mistake:

* 21% of all 238 edges point at just three targets, and 37 of 92 rows have no
  in-edges at all;
* the graph was curated to answer "where should a displaced worker *go*", so it
  points toward a handful of designated safe havens. Read as competition it
  measures which destinations the KB recommends most, not which jobs are hard
  to get;
* 16 of its edges were written by this system's own ``transition_evaluator``
  (``_source: "llm_eval"``), so it is not fully external to begin with.

A prototype built on it ranked Public Policy Analyst as the single most
competitive occupation in the KB — an artefact of four in-edges landing on a
5,580-person occupation — while reporting zero competition for Accountant
(1.4M) and Administrative Assistant (1.8M), which simply are not anyone's
curated destination.

The KB's other adjacency candidates fail too, and it is worth recording why so
nobody retries them: ``required_skills`` holds 365 distinct free-text strings
across 382 slots, so only 0.6% of job pairs share even one skill; the 8-dim
``skill_vector`` is all-positive and narrow, giving pairwise cosine a median of
0.88 — everything is adjacent to everything.

What is used instead
--------------------
O*NET's published **Related Occupations**: 18,460 edges over 923 occupations,
tiered (Primary-Short / Primary-Long / Supplemental), derived from measured
occupational characteristics rather than from anyone's advice about careers.
It joins to the KB on the SOC codes stamped by ``services/bls_coverage.py`` —
which is what made this possible; before those, there was nothing to join on.

Employment weights come from the 831-occupation BLS catalog, so the adjacent
pool counts *all* related occupations, not only the 65 that happen to be in
this KB.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ONET_URL = "https://www.onetcenter.org/dl_files/database/db_30_0_text.zip"
_ONET_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
_RELATED_MEMBER = "Related Occupations.txt"
_CACHE_PATH = "data/onet_related.json"

# O*NET's own tiering, read as "how plausible is a move along this edge".
# Weights are a prior — the tiers are measured, the numbers attached to them
# are not. Same discipline as the claim stakes and the leverage composite.
TIER_WEIGHT: dict[str, float] = {
    "Primary-Short": 1.0,    # closest match, shortest retraining
    "Primary-Long": 0.6,     # still a primary relation, longer path
    "Supplemental": 0.3,     # plausible but distant
}


@dataclass(frozen=True)
class EntryCompetition:
    """How contested one occupation's openings are, from the supply side."""
    job_id: str
    title: str
    soc_code: str | None
    employment: int | None
    industry: str = ""
    adjacent_pool: float | None = None       # weighted headcount of feeder occupations
    feeder_count: int = 0                    # distinct related occupations
    est_openings: float | None = None        # employment x industry vacancy rate
    competition_ratio: float | None = None   # adjacent workers per opening
    percentile: float | None = None          # rank within the modelled cohort
    verdict: str = "not_modelled"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# O*NET relatedness graph
# ---------------------------------------------------------------------------
def _soc7(onet_soc: str) -> str:
    """O*NET-SOC ``13-2011.00`` → SOC ``13-2011``. Detail suffixes collapse."""
    return (onet_soc or "").strip()[:7]


def refresh_onet_related(*, path: str = _CACHE_PATH) -> dict[str, list[list]]:
    """Download O*NET and cache in-edges: ``{soc: [[feeder_soc, tier], ...]}``.

    Stored as *in*-edges because that is the direction competition flows: an
    edge ``Y → X`` in O*NET means a worker exploring occupation Y is shown X,
    so Y is a feeder into X. Only 56% of O*NET's edges are symmetric, so the
    direction is real information and is not flattened.
    """
    try:
        import requests

        resp = requests.get(_ONET_URL, headers=_ONET_HEADERS, timeout=180)
        resp.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        member = next(n for n in archive.namelist() if n.endswith(_RELATED_MEMBER))
        rows = archive.read(member).decode("utf-8", "replace").splitlines()
    except Exception:
        return onet_related(path=path)

    header = rows[0].split("\t")
    try:
        i_src = header.index("O*NET-SOC Code")
        i_dst = header.index("Related O*NET-SOC Code")
        i_tier = header.index("Relatedness Tier")
    except ValueError:
        return onet_related(path=path)

    seen: set[tuple[str, str]] = set()
    in_edges: dict[str, list[list]] = {}
    for line in rows[1:]:
        parts = line.split("\t")
        if len(parts) <= i_tier:
            continue
        src, dst = _soc7(parts[i_src]), _soc7(parts[i_dst])
        if not src or not dst or src == dst or (src, dst) in seen:
            continue
        seen.add((src, dst))
        in_edges.setdefault(dst, []).append([src, parts[i_tier].strip()])

    payload = {**in_edges, "_fetched_at": datetime.now(timezone.utc).isoformat()}
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return in_edges


def onet_related(*, path: str = _CACHE_PATH) -> dict[str, list[list]]:
    """Cached in-edge graph. ``{}`` when never built — never a fabricated one."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# entry competition
# ---------------------------------------------------------------------------
def adjacent_pool(
    soc: str,
    *,
    graph: dict[str, list[list]],
    employment: dict[str, dict],
) -> tuple[float | None, int]:
    """Weighted headcount of occupations that feed into *soc*.

    Counts *every* related occupation in the national catalog, not only the
    ones this KB happens to contain — competition does not stop at the edge of
    a knowledge base. Feeders with no employment figure are skipped rather than
    imputed, and the feeder count reports how many actually contributed.
    """
    feeders = graph.get(soc) or []
    if not feeders:
        return None, 0

    total = 0.0
    counted = 0
    for feeder_soc, tier in feeders:
        entry = employment.get(feeder_soc) or {}
        headcount = entry.get("employment")
        if not headcount:
            continue
        total += headcount * TIER_WEIGHT.get(tier, 0.3)
        counted += 1
    return (round(total, 1), counted) if counted else (None, 0)


def estimate_openings(employment: int | None, openings_rate: float | None) -> float | None:
    """Occupation openings implied by its own headcount and its industry's rate.

    JOLTS defines the openings rate as ``V / (E + V)``, so inverting it gives
    ``V = E * rate / (100 - rate)``. The rate is the industry's — that
    limitation is inherited and cannot be removed without an occupational
    vacancy series that does not exist. What this does add is *scale*: two
    occupations in one industry no longer look identical, because a 1.4M-person
    occupation and a 5,000-person one imply very different numbers of openings.
    """
    if not employment or not openings_rate or openings_rate >= 100:
        return None
    return round(employment * openings_rate / (100.0 - openings_rate), 1)


def classify_by_rank(
    ratios: list[float],
    *,
    red_quantile: float = 0.67,
    blue_quantile: float = 0.33,
) -> dict[float, str]:
    """Verdicts assigned by rank within the cohort, not by an absolute cutoff.

    The raw ratio is "weighted adjacent headcount per estimated opening", and
    that number has no natural scale: it inherits the tier weights, and it
    scales with how small the occupation is, so a fixed threshold mostly
    measures occupation size. Ranking does not — a cohort ordering is nearly
    invariant to the tier weights, which is exactly what you want from a
    quantity whose weights are admittedly a prior.

    It also matches what the question actually means. "Red ocean" is not an
    absolute property of a job; it is a comparison with the other jobs someone
    could be aiming at.
    """
    if not ratios:
        return {}
    ordered = sorted(ratios)
    n = len(ordered)

    def cut(q: float) -> float:
        return ordered[min(n - 1, max(0, int(round(q * (n - 1)))))]

    red_at, blue_at = cut(red_quantile), cut(blue_quantile)
    out: dict[float, str] = {}
    for r in ratios:
        if r >= red_at:
            out[r] = "red_ocean"
        elif r <= blue_at:
            out[r] = "blue_ocean"
        else:
            out[r] = "balanced"
    return out


def entry_competition(
    jobs: list[dict],
    *,
    tightness: dict[str, Any] | None = None,
    graph: dict[str, list[list]] | None = None,
    employment: dict[str, dict] | None = None,
    red_quantile: float = 0.67,
    blue_quantile: float = 0.33,
) -> list[EntryCompetition]:
    """Per-occupation competition ratio: adjacent workers per estimated opening.

    A row that cannot be modelled says so. ``not_modelled`` is never collapsed
    into ``blue_ocean``: an occupation with no SOC code, no employment figure or
    no known feeders is one this method is silent about, and silence must not
    read as good news. That is the same rule the patch claims follow when
    evidence is missing.
    """
    from services.bls_coverage import soc_catalog
    from services.labor_tightness import industry_tightness

    graph = graph if graph is not None else onet_related()
    employment = employment if employment is not None else soc_catalog()
    by_industry = tightness if tightness is not None else industry_tightness()

    out: list[EntryCompetition] = []
    for job in jobs:
        soc = job.get("soc_code")
        base = {
            "job_id": job["id"],
            "title": job.get("title", ""),
            "soc_code": soc,
            "employment": job.get("bls_employment"),
            "industry": job.get("industry", ""),
        }
        if not soc:
            out.append(EntryCompetition(
                **base, reason="no SOC anchor — cannot join to the O*NET graph"))
            continue

        pool, feeders = adjacent_pool(soc, graph=graph, employment=employment)
        if pool is None:
            out.append(EntryCompetition(
                **base, feeder_count=feeders,
                reason=f"no related occupations for SOC {soc} in O*NET"))
            continue

        industry = by_industry.get(job.get("industry", ""))
        rate = industry.openings_rate if industry and industry.covered else None
        openings = estimate_openings(job.get("bls_employment"), rate)
        if openings is None:
            out.append(EntryCompetition(
                **base, adjacent_pool=pool, feeder_count=feeders,
                reason=("industry not covered by JOLTS" if rate is None
                        else "no employment figure for this occupation")))
            continue

        out.append(EntryCompetition(
            **base,
            adjacent_pool=pool,
            feeder_count=feeders,
            est_openings=openings,
            competition_ratio=round(pool / openings, 2),
            verdict="",              # assigned by rank once the cohort is known
            reason="",
        ))

    # Second pass: the verdict is a statement about this occupation relative to
    # the others, so it cannot be decided one row at a time.
    ratios = [r.competition_ratio for r in out if r.competition_ratio is not None]
    verdicts = classify_by_rank(
        ratios, red_quantile=red_quantile, blue_quantile=blue_quantile)
    percentile = {
        r: (i + 0.5) / len(ratios)
        for i, r in enumerate(sorted(ratios))
    } if ratios else {}
    return [
        r if r.competition_ratio is None else EntryCompetition(
            **{**r.to_dict(),
               "verdict": verdicts[r.competition_ratio],
               "percentile": round(percentile[r.competition_ratio], 3)}
        )
        for r in out
    ]


def competition_report(jobs: list[dict], **kwargs) -> dict[str, Any]:
    """Ranked competition plus an explicit account of what could not be modelled."""
    rows = entry_competition(jobs, **kwargs)
    modelled = [r for r in rows if r.competition_ratio is not None]
    modelled.sort(key=lambda r: r.competition_ratio, reverse=True)
    unmodelled = [r for r in rows if r.competition_ratio is None]

    reasons: dict[str, int] = {}
    for r in unmodelled:
        reasons[r.reason] = reasons.get(r.reason, 0) + 1

    return {
        "granularity": "occupation",
        "source": "O*NET Related Occupations x BLS employment x JOLTS industry vacancy rate",
        "tier_weights_are_a_prior": True,
        "inflow_channel": "occupational_switchers_only",
        "caveats": [
            "The vacancy *rate* is still the industry's — no occupational "
            "vacancy series exists. What is occupation-level here is the "
            "adjacent labour pool and the scale of the occupation itself.",
            "Only occupation-to-occupation inflow is counted. New entrants "
            "from education are invisible, so credentialed professions fed "
            "mainly by graduates — law, medicine, teaching — will read as "
            "less contested than they are. Lawyer lands in the bottom "
            "tercile here for exactly that reason.",
            "Verdicts are ranks within this cohort, not absolute properties. "
            "A different set of occupations produces different verdicts for "
            "the same jobs.",
        ],
        "modelled": len(modelled),
        "not_modelled": len(unmodelled),
        "not_modelled_reasons": reasons,
        "occupations": [r.to_dict() for r in modelled],
        "skipped": [
            {"job_id": r.job_id, "title": r.title, "reason": r.reason}
            for r in unmodelled
        ],
    }
