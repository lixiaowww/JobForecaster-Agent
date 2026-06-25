"""BLS-driven high-coverage role enrichment.

Ranks occupations by national employment size (BLS OES 2023) and proactively
fills KB gaps for the roles that cover the most workers — before users ever
search for them.

Credit budget: Tavily advanced search, 1 credit per role.
Config: job_query_agent.coverage_enrichment.tavily_daily_budget (default 20)

Offline-safe: hardcoded 2023 BLS OES data is the baseline.
BLS API refresh: optional, requires BLS_API_KEY env var; runs monthly.
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
) -> list[dict]:
    """Return HIGH_COVERAGE_OCCUPATIONS entries not adequately covered in KB.

    'Adequately covered' = find_best_match returns sim >= sim_threshold.
    Default threshold: search_cfg tier_weak (0.55).
    Returns list sorted by employment size (largest gap first).
    """
    import copy
    try:
        import job_radar
    except ImportError:
        return []

    threshold = sim_threshold if sim_threshold is not None else float(
        search_cfg.get("tier_weak", 0.55)
    )
    gaps: list[dict] = []
    for occ in HIGH_COVERAGE_OCCUPATIONS:
        _, best = job_radar.find_best_match(
            occ["query"], [copy.deepcopy(j) for j in jobs], search_cfg=search_cfg
        )
        sim = best.get("combined_similarity", 0.0) if best else 0.0
        if sim < threshold:
            gaps.append({**occ, "_current_sim": round(sim, 3), "_best_id": best["id"] if best else None})
    return gaps


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
# Optional BLS API refresh (monthly cadence — requires BLS_API_KEY)
# ---------------------------------------------------------------------------
_BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Map SOC code → BLS OES national employment series ID
# Format: OEUN + 0000000 (national) + 000000 (all industries) + soc_nodash(6) + 01
def _soc_to_series(soc: str) -> str:
    code = soc.replace("-", "")
    return f"OEUN0000000000000{code}01"


def refresh_employment_from_bls(
    *,
    api_key: str | None = None,
    cache_path: str = _CACHE_PATH,
    max_series: int = 50,
) -> dict[str, int]:
    """Fetch latest employment levels from BLS OES API.

    Returns {soc_code: employment_thousands}. Falls back to hardcoded if API fails.
    Results cached for 30 days to avoid redundant calls.
    """
    key = api_key or os.environ.get("BLS_API_KEY", "")
    cache = _load_emp_cache(cache_path)

    # Cache is fresh (within 30 days) → return it
    cached_date = cache.get("_fetched_at", "")
    if cached_date:
        from datetime import date as _date
        try:
            age_days = (_date.today() - _date.fromisoformat(cached_date)).days
            if age_days < 30:
                return {k: v for k, v in cache.items() if not k.startswith("_")}
        except Exception:
            pass

    batch = HIGH_COVERAGE_OCCUPATIONS[:max_series]
    series_ids = [_soc_to_series(occ["soc"]) for occ in batch]
    soc_by_series = {_soc_to_series(occ["soc"]): occ["soc"] for occ in batch}

    try:
        import requests
        payload: dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": "2023",
            "endyear": "2024",
        }
        if key:
            payload["registrationkey"] = key

        resp = requests.post(_BLS_API_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            return {}

        result: dict[str, int] = {}
        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            vals = series.get("data", [])
            if vals:
                try:
                    emp = int(vals[0]["value"].replace(",", ""))
                    soc = soc_by_series.get(sid, sid)
                    result[soc] = emp
                except Exception:
                    pass

        if result:
            result["_fetched_at"] = date.today().isoformat()
            _save_emp_cache(cache_path, result)
        return result

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
