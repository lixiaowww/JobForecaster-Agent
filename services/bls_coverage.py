"""BLS-driven high-coverage role enrichment.

Ranks occupations by national employment size (BLS OES 2023) and proactively
fills KB gaps for the roles that cover the most workers — before users ever
search for them.

Credit budget: Tavily advanced search, 1 credit per role.
Config: job_query_agent.coverage_enrichment.tavily_daily_budget (default 20)

Offline-safe: hardcoded 2023 BLS OES data is the baseline.
Employment refresh: annual OES flat file download from BLS (no API key needed).
  URL: https://www.bls.gov/oes/special.requests/oesm{YY}nat.zip
  BLS_API_KEY env var: used for CES monthly data in job_market.py (higher rate limits).
  Note: BLS time series API (v2) does NOT support OES — OES is distributed
        as annual Excel flat files only.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# BLS OES 2023 — top occupations by national employment (thousands)
# Source: BLS Occupational Employment and Wage Statistics, May 2023
# Fields: soc_code, title, employment_k (thousands), search_query, industry
# ---------------------------------------------------------------------------
HIGH_COVERAGE_OCCUPATIONS: list[dict[str, Any]] = [
    # Retail & Sales
    {"soc": "41-2031", "title": "Retail Salesperson",          "emp_k": 4436, "query": "retail salesperson",          "industry": "Retail"},
    {"soc": "41-2011", "title": "Cashier",                     "emp_k": 3327, "query": "cashier",                     "industry": "Retail"},
    {"soc": "41-4011", "title": "Sales Representative (B2B)",  "emp_k": 1521, "query": "sales representative",        "industry": "Retail"},
    {"soc": "41-3021", "title": "Insurance Sales Agent",       "emp_k":  492, "query": "insurance agent",             "industry": "Finance"},
    {"soc": "41-3011", "title": "Advertising Sales Agent",     "emp_k":  150, "query": "advertising sales agent",     "industry": "Media"},
    # Office & Admin
    {"soc": "43-9061", "title": "Office Clerk",                "emp_k": 3074, "query": "office clerk",                "industry": "Government"},
    {"soc": "43-4051", "title": "Customer Service Representative","emp_k": 2884, "query": "customer service representative","industry": "Retail"},
    {"soc": "43-6014", "title": "Administrative Assistant",    "emp_k": 2018, "query": "administrative assistant",    "industry": "Government"},
    {"soc": "43-3031", "title": "Bookkeeping Clerk",           "emp_k": 1481, "query": "bookkeeper",                  "industry": "Finance"},
    {"soc": "43-4171", "title": "Receptionist",                "emp_k":  942, "query": "receptionist",               "industry": "Government"},
    {"soc": "43-1011", "title": "Office Supervisor",           "emp_k":  785, "query": "office supervisor",           "industry": "Government"},
    # Healthcare
    {"soc": "29-1141", "title": "Registered Nurse",            "emp_k": 3171, "query": "registered nurse",           "industry": "Healthcare"},
    {"soc": "31-1121", "title": "Home Health Aide",            "emp_k": 2395, "query": "home health aide",            "industry": "Healthcare"},
    {"soc": "31-1131", "title": "Nursing Assistant",           "emp_k": 1396, "query": "nursing assistant",           "industry": "Healthcare"},
    {"soc": "31-9092", "title": "Medical Assistant",           "emp_k":  782, "query": "medical assistant",           "industry": "Healthcare"},
    {"soc": "29-2061", "title": "Licensed Practical Nurse",    "emp_k":  635, "query": "licensed practical nurse",    "industry": "Healthcare"},
    {"soc": "29-2034", "title": "Radiologic Technologist",     "emp_k":  226, "query": "radiologic technologist",     "industry": "Healthcare"},
    {"soc": "29-1051", "title": "Pharmacist",                  "emp_k":  322, "query": "pharmacist",                  "industry": "Healthcare"},
    {"soc": "11-9111", "title": "Healthcare Manager",          "emp_k":  588, "query": "healthcare manager",          "industry": "Healthcare"},
    # Food & Hospitality
    {"soc": "35-3023", "title": "Fast Food Worker",            "emp_k": 3784, "query": "fast food worker",            "industry": "Hospitality"},
    {"soc": "35-3031", "title": "Waiter / Waitress",           "emp_k": 2218, "query": "waiter",                      "industry": "Hospitality"},
    {"soc": "35-2014", "title": "Restaurant Cook",             "emp_k": 1512, "query": "restaurant cook",             "industry": "Hospitality"},
    {"soc": "35-1011", "title": "Food Service Supervisor",     "emp_k":  994, "query": "food service supervisor",     "industry": "Hospitality"},
    # Logistics & Transport
    {"soc": "53-7062", "title": "Warehouse Worker",            "emp_k": 2596, "query": "warehouse worker",            "industry": "Logistics"},
    {"soc": "53-3032", "title": "Heavy Truck Driver",          "emp_k": 2004, "query": "truck driver",                "industry": "Logistics"},
    {"soc": "53-3033", "title": "Delivery Driver",             "emp_k":  916, "query": "delivery driver",             "industry": "Logistics"},
    # Construction & Maintenance
    {"soc": "47-2061", "title": "Construction Laborer",        "emp_k": 1582, "query": "construction laborer",        "industry": "Construction"},
    {"soc": "37-2011", "title": "Janitor / Cleaner",           "emp_k": 2318, "query": "janitor",                     "industry": "Construction"},
    {"soc": "49-9071", "title": "Maintenance & Repair Worker", "emp_k": 1521, "query": "maintenance technician",      "industry": "Construction"},
    {"soc": "47-1011", "title": "Construction Supervisor",     "emp_k":  720, "query": "construction supervisor",     "industry": "Construction"},
    # Education
    {"soc": "25-2021", "title": "Elementary School Teacher",   "emp_k": 1534, "query": "elementary school teacher",   "industry": "Education"},
    {"soc": "25-2031", "title": "Secondary School Teacher",    "emp_k": 1078, "query": "high school teacher",         "industry": "Education"},
    {"soc": "25-1099", "title": "University Lecturer",         "emp_k":  643, "query": "university lecturer",         "industry": "Education"},
    {"soc": "25-9031", "title": "Instructional Coordinator",   "emp_k":  181, "query": "instructional designer",      "industry": "Education"},
    # Tech
    {"soc": "15-1252", "title": "Software Developer",          "emp_k": 1892, "query": "software developer",         "industry": "Tech"},
    {"soc": "15-1211", "title": "Systems Analyst",             "emp_k":  586, "query": "systems analyst",             "industry": "Tech"},
    {"soc": "15-1232", "title": "IT Support Specialist",       "emp_k":  835, "query": "it support specialist",       "industry": "Tech"},
    {"soc": "15-1244", "title": "Network Administrator",       "emp_k":  344, "query": "network administrator",       "industry": "Tech"},
    {"soc": "15-1254", "title": "Web Developer",               "emp_k":  208, "query": "web developer",               "industry": "Tech"},
    {"soc": "15-2051", "title": "Data Scientist",              "emp_k":  168, "query": "data scientist",              "industry": "Tech"},
    {"soc": "11-3021", "title": "IT Manager",                  "emp_k":  490, "query": "it manager",                  "industry": "Tech"},
    # Finance & Business
    {"soc": "13-2011", "title": "Accountant",                  "emp_k": 1441, "query": "accountant",                  "industry": "Finance"},
    {"soc": "13-1161", "title": "Market Research Analyst",     "emp_k":  792, "query": "market research analyst",     "industry": "Finance"},
    {"soc": "13-2051", "title": "Financial Analyst",           "emp_k":  327, "query": "financial analyst",           "industry": "Finance"},
    {"soc": "13-2082", "title": "Tax Preparer",                "emp_k":   80, "query": "tax preparer",                "industry": "Finance"},
    {"soc": "11-1021", "title": "Operations Manager",          "emp_k": 3057, "query": "operations manager",          "industry": "Government"},
    {"soc": "11-2021", "title": "Marketing Manager",           "emp_k":  386, "query": "marketing manager",           "industry": "Media"},
    {"soc": "13-1071", "title": "HR Specialist",               "emp_k":  861, "query": "hr specialist",               "industry": "Government"},
    # Engineering
    {"soc": "17-2051", "title": "Civil Engineer",              "emp_k":  329, "query": "civil engineer",              "industry": "Construction"},
    {"soc": "17-2141", "title": "Mechanical Engineer",         "emp_k":  303, "query": "mechanical engineer",         "industry": "Manufacturing"},
    {"soc": "17-2071", "title": "Electrical Engineer",         "emp_k":  195, "query": "electrical engineer",         "industry": "Manufacturing"},
    {"soc": "17-2112", "title": "Industrial Engineer",         "emp_k":  299, "query": "industrial engineer",         "industry": "Manufacturing"},
    # Legal & Social
    {"soc": "23-1011", "title": "Lawyer",                      "emp_k":  813, "query": "lawyer",                      "industry": "Legal"},
    {"soc": "23-2011", "title": "Paralegal",                   "emp_k":  372, "query": "paralegal",                   "industry": "Legal"},
    {"soc": "21-1021", "title": "Child / Family Social Worker","emp_k":  342, "query": "social worker",               "industry": "Government"},
    # Security & Protection
    {"soc": "33-9032", "title": "Security Guard",              "emp_k": 1073, "query": "security guard",              "industry": "Government"},
    # Agriculture
    {"soc": "45-2092", "title": "Agricultural Worker",         "emp_k":  870, "query": "farm worker",                 "industry": "Agriculture"},
]

# Sort by employment size (highest first) — this is the enrichment priority order
HIGH_COVERAGE_OCCUPATIONS.sort(key=lambda x: x["emp_k"], reverse=True)

_CACHE_PATH = "data/bls_coverage_cache.json"


def coverage_gaps(
    jobs: list[dict],
    search_cfg: dict,
    *,
    sim_threshold: float | None = None,
    use_live_employment: bool = False,
) -> list[dict]:
    """Return HIGH_COVERAGE_OCCUPATIONS entries not adequately covered in KB.

    'Adequately covered' = find_best_match returns sim >= sim_threshold.
    Default threshold: search_cfg tier_weak (0.55).
    Returns list sorted by employment size (largest gap first).

    use_live_employment=True: pull cached OES data to override hardcoded emp_k.
    """
    import copy
    try:
        import job_radar
    except ImportError:
        return []

    threshold = sim_threshold if sim_threshold is not None else float(
        search_cfg.get("tier_weak", 0.55)
    )

    # Optionally override with live OES employment numbers (from cache)
    live_emp: dict[str, int] = {}
    if use_live_employment:
        cached = _load_emp_cache(_CACHE_PATH)
        live_emp = {k: v for k, v in cached.items() if not k.startswith("_")}

    occupations = HIGH_COVERAGE_OCCUPATIONS
    if live_emp:
        occupations = sorted(
            [{**o, "emp_k": live_emp.get(o["soc"], o["emp_k"] * 1000) // 1000} for o in occupations],
            key=lambda x: x["emp_k"], reverse=True,
        )

    gaps: list[dict] = []
    for occ in occupations:
        _, best = job_radar.find_best_match(
            occ["query"], [copy.deepcopy(j) for j in jobs], search_cfg=search_cfg
        )
        sim = best.get("combined_similarity", 0.0) if best else 0.0
        if sim < threshold:
            gaps.append({**occ, "_current_sim": round(sim, 3), "_best_id": best["id"] if best else None})
    return gaps


def _stamp_soc(jobs: list[dict], job_id: str, occ: dict, kb_path: str) -> None:
    """Write the known SOC code + employment onto a freshly generated KB row."""
    emp_cache = _load_emp_cache(_CACHE_PATH)
    for job in jobs:
        if job.get("id") != job_id:
            continue
        job["soc_code"] = occ["soc"]
        job["bls_title"] = occ["title"]
        emp = emp_cache.get(occ["soc"])
        if emp is None and occ.get("emp_k"):
            emp = int(occ["emp_k"]) * 1000
        if emp is not None:
            job["bls_employment"] = emp
        Path(kb_path).write_text(
            json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        return


def run_coverage_enrichment(
    cfg: dict,
    *,
    daily_budget: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Enrich KB with top-employment occupations missing from KB.

    Called from query-agent calibration loop before query rounds.
    Respects daily_budget (Tavily credits). Returns summary dict.
    """
    import copy
    try:
        import job_radar
    except ImportError:
        return {"skipped": True, "reason": "job_radar not available"}

    if not os.environ.get("TAVILY_API_KEY") and not os.environ.get("GROQ_API_KEY"):
        return {"skipped": True, "reason": "no API keys"}

    jr_cfg = cfg.get("job_radar", {})
    kb_path = jr_cfg.get("kb_path", "data/jobs_kb.json")
    search_cfg = job_radar.resolve_search_config(jr_cfg)

    jobs = job_radar.load_knowledge_base(kb_path)
    gaps = coverage_gaps(jobs, search_cfg)

    generated = 0
    failed = 0
    skipped_budget = 0
    results: list[dict] = []

    for occ in gaps:
        if generated >= daily_budget:
            skipped_budget += len(gaps) - generated - failed
            break

        if dry_run:
            results.append({"query": occ["query"], "emp_k": occ["emp_k"], "dry_run": True})
            generated += 1
            continue

        profile = job_radar.generate_job_profile_via_llm(occ["query"], kb_path=kb_path)
        if profile:
            # Reload jobs so next coverage_gaps call sees the new entry
            jobs = job_radar.load_knowledge_base(kb_path)
            # Stamp the SOC code we already know. This row is generated *for* a
            # specific BLS occupation, so the mapping is certain here in a way
            # no later matching pass can recover — and it is the only external
            # anchor an LLM-generated profile will ever have. It was previously
            # discarded, which left every generated row permanently unverifiable
            # by ``evidence.bls_presence``.
            _stamp_soc(jobs, profile["id"], occ, kb_path)
            results.append({
                "query": occ["query"],
                "emp_k": occ["emp_k"],
                "profile_id": profile["id"],
                "sim_before": occ["_current_sim"],
                "workers_covered_k": occ["emp_k"],
            })
            generated += 1
        else:
            failed += 1

    total_workers_k = sum(r.get("workers_covered_k", 0) for r in results)
    return {
        "gaps_found": len(gaps),
        "generated": generated,
        "failed": failed,
        "skipped_budget": skipped_budget,
        "tavily_credits_used": generated,  # 1 credit per generate_job_profile_via_llm call
        "workers_newly_covered_k": total_workers_k,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Annual OES flat file refresh (no API key needed — BLS publishes publicly)
# URL pattern: https://www.bls.gov/oes/special.requests/oesm{YY}nat.zip
# Released each May; contains national_M{YEAR}_dl.xlsx with TOT_EMP by SOC.
# ---------------------------------------------------------------------------

def refresh_employment_from_bls(
    *,
    year: int | None = None,
    cache_path: str = _CACHE_PATH,
) -> dict[str, int]:
    """Download BLS OES national flat file and extract employment by SOC code.

    Returns {soc_code: employment} (actual count, not thousands).
    Results cached for ~365 days. Falls back to {} on any failure.

    Note: BLS time series API v2 does NOT support OES occupational series.
    OES is annual and distributed as Excel flat files only.
    BLS_API_KEY is used for CES monthly data (job_market.py), not here.
    """
    cache = _load_emp_cache(cache_path)
    cached_date = cache.get("_fetched_at", "")
    if cached_date:
        try:
            age_days = (date.today() - date.fromisoformat(cached_date)).days
            if age_days < 340:  # refresh annually
                return {k: v for k, v in cache.items() if not k.startswith("_")}
        except Exception:
            pass

    if year is None:
        # Use previous year (OES released in May; current year not yet available before May)
        y = date.today().year
        year = y - 1 if date.today().month < 6 else y

    yy = str(year)[2:]  # "2023" → "23"
    url = f"https://www.bls.gov/oes/special.requests/oesm{yy}nat.zip"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Referer": "https://www.bls.gov/oes/",
    }

    try:
        import io
        import requests
        import zipfile

        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        if resp.content[:2] != b"PK":
            return {}  # not a ZIP (got HTML redirect)

        z = zipfile.ZipFile(io.BytesIO(resp.content))
        xlsx_name = next((n for n in z.namelist() if n.endswith(".xlsx")), None)
        if not xlsx_name:
            return {}

        try:
            import openpyxl
        except ImportError:
            return {}  # openpyxl optional

        wb = openpyxl.load_workbook(z.open(xlsx_name), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        col_headers = [str(c).strip() if c else "" for c in next(rows)]

        occ_idx = col_headers.index("OCC_CODE")
        emp_idx = col_headers.index("TOT_EMP")
        naics_idx = col_headers.index("NAICS") if "NAICS" in col_headers else None

        # Filter: national cross-industry rows (NAICS = "000000" or "Cross-industry")
        soc_set = {occ["soc"] for occ in HIGH_COVERAGE_OCCUPATIONS}
        result: dict[str, int] = {}
        for row in rows:
            soc = str(row[occ_idx]).strip() if row[occ_idx] else ""
            if soc not in soc_set:
                continue
            # Use cross-industry row (NAICS = 000000)
            naics = str(row[naics_idx]).strip() if naics_idx is not None else "000000"
            if naics not in ("000000", "Cross-industry"):
                continue
            raw = row[emp_idx]
            try:
                emp = int(str(raw).replace(",", ""))
                if soc not in result:  # take first (cross-industry) match
                    result[soc] = emp
            except (TypeError, ValueError):
                pass

        if result:
            result["_fetched_at"] = date.today().isoformat()
            result["_oes_year"] = year
            _save_emp_cache(cache_path, result)
        return {k: v for k, v in result.items() if not k.startswith("_")}

    except Exception:
        return {}


def _load_emp_cache(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_emp_cache(path: str, data: dict) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SOC backfill — stamping external occupational ground truth onto KB rows
# ---------------------------------------------------------------------------
def _norm_title(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def soc_backfill_matches(jobs: list[dict]) -> list[dict]:
    """KB rows that can be stamped with a BLS SOC code, high-precision only.

    Two restrictions, both deliberate, both costing recall on purpose:

    **Titles only — never ``search_aliases``.** Aliases are the field the query
    agent mutates. Matching through them would let the agent add an alias, have
    that alias earn the profile a SOC code, and then have that SOC code count as
    *external evidence* when grading its own patches — precisely the circularity
    ``services/job_query_agent/claims.py`` exists to break. Measured on the
    current KB, the alias path produced 8 wrong stamps out of 28, including
    ``13-2051 Financial Analyst → fin_credit_analyst`` (Credit Analyst is
    13-2041) via an alias.

    **Injective only.** A KB row claimed by two SOC codes, or a SOC code
    claiming two rows, is dropped rather than guessed at (e.g. 15-1252 Software
    Developer and 15-1254 Web Developer both reaching one "Software Engineer"
    row). An anchor that is sometimes wrong is worse than no anchor: a bad
    ground truth does not merely fail to catch drift, it certifies it.

    Fuzzy similarity was evaluated for this and rejected outright — at a 0.70
    cutoff it mapped IT Manager and Operations Manager onto the HR Manager row
    and Systems Analyst onto Credit Analyst, while scoring an exact Receptionist
    match at 0.064.
    """
    import collections

    by_title: dict[str, list[str]] = collections.defaultdict(list)
    for job in jobs:
        by_title[_norm_title(job.get("title", ""))].append(job["id"])

    pairs: set[tuple[str, str, str]] = set()
    for occ in HIGH_COVERAGE_OCCUPATIONS:
        for key in {_norm_title(occ["title"]), _norm_title(occ["query"])}:
            if not key:
                continue
            for job_id in by_title.get(key, []):
                pairs.add((occ["soc"], occ["title"], job_id))

    soc_per_job: dict[str, set[str]] = collections.defaultdict(set)
    job_per_soc: dict[str, set[str]] = collections.defaultdict(set)
    for soc, _title, job_id in pairs:
        soc_per_job[job_id].add(soc)
        job_per_soc[soc].add(job_id)

    emp_cache = _load_emp_cache(_CACHE_PATH)
    out: list[dict] = []
    for soc, title, job_id in sorted(pairs):
        if len(soc_per_job[job_id]) != 1 or len(job_per_soc[soc]) != 1:
            continue
        out.append({
            "job_id": job_id,
            "soc_code": soc,
            "bls_title": title,
            "bls_employment": emp_cache.get(soc),
        })
    return out


def run_soc_backfill(
    cfg: dict,
    *,
    dry_run: bool = False,
    refresh_employment: bool = False,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Stamp ``soc_code`` / ``bls_employment`` onto KB rows that match a SOC code.

    This is what turns ``evidence.bls_presence`` from a permanently-skipped
    signal into a working one: without a SOC code on the row there is nothing
    for a patch claim to be corroborated against.

    Idempotent — rows that already carry a ``soc_code`` are left alone, so this
    can run on a schedule. Recorded in the provenance ledger like every other
    automatic write to the KB.
    """
    try:
        import job_radar
    except ImportError:
        return {"skipped": True, "reason": "job_radar not available"}

    from services import provenance

    kb_path = cfg.get("job_radar", {}).get("kb_path", "data/jobs_kb.json")
    ledger_path = ledger_path or cfg.get("job_query_agent", {}).get(
        "provenance_path", provenance.DEFAULT_LEDGER_PATH)

    if refresh_employment:
        refresh_employment_from_bls()   # network; falls back to cache on failure

    jobs = job_radar.load_knowledge_base(kb_path)
    by_id = {j["id"]: j for j in jobs}
    matches = soc_backfill_matches(jobs)

    stamped: list[dict] = []
    already: list[str] = []
    for m in matches:
        job = by_id.get(m["job_id"])
        if job is None:
            continue
        if job.get("soc_code"):
            already.append(m["job_id"])
            continue
        stamped.append(m)
        if not dry_run:
            job["soc_code"] = m["soc_code"]
            job["bls_title"] = m["bls_title"]
            if m["bls_employment"] is not None:
                job["bls_employment"] = m["bls_employment"]

    if stamped and not dry_run:
        Path(kb_path).write_text(
            json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        provenance.record_patch(
            subsystem="bls_coverage",
            patch_type="soc_backfill",
            reason=f"stamped {len(stamped)} KB row(s) with BLS SOC ground truth",
            before=[{"id": m["job_id"]} for m in stamped],
            after=stamped,
            path=ledger_path,
        )

    return {
        "matches": len(matches),
        "stamped": len(stamped),
        "already_stamped": len(already),
        "with_employment": sum(1 for m in stamped if m["bls_employment"] is not None),
        "dry_run": dry_run,
        "results": stamped,
    }
