import json
import math
import os
import re
from crowd import HashingEmbedder

def load_knowledge_base(
    kb_path: str = "data/jobs_kb.json",
    overlay_path: str | None = None,
    apply_calibration: bool = True,
) -> list[dict]:
    """Loads job profiles and optionally merges BLS calibration overlay."""
    if not os.path.exists(kb_path):
        return []
    with open(kb_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    if not apply_calibration:
        return jobs
    try:
        from services.job_market import load_calibration_overlay, merge_calibration_into_jobs

        overlay = load_calibration_overlay(overlay_path)
        return merge_calibration_into_jobs(jobs, overlay)
    except Exception:
        return jobs

def compute_impact_scores(jobs: list[dict], scenario_params: dict) -> list[dict]:
    """
    Computes the impact score for each job based on sensitivity weights and scenario parameters.
    Formula: impact_j = base_demand_trend_j + sum(s_i * w_j_i)
    Where s_i is normalized.
    """
    scored_jobs = []
    var_names = [
        "augmentation_ratio", "demand_elasticity", "oring_leverage",
        "skill_distance", "diffusion_years", "absorbing_sector",
        "productivity_capture", "task_frontier_open"
    ]
    
    for job in jobs:
        score = job.get("base_demand_trend", 0.0)
        sensitivity = job.get("sensitivity", {})
        
        for var in var_names:
            val = scenario_params.get(var, 0.5)
            # Normalize diffusion_years (which has slider range 1.0 - 50.0)
            if var == "diffusion_years":
                val = math.log1p(val) / math.log1p(50)
            
            weight = sensitivity.get(var, 0.0)
            score += val * weight
            
        job_copy = job.copy()
        job_copy["impact_score"] = round(score, 3)
        scored_jobs.append(job_copy)
        
    return scored_jobs

def filter_by_industry(jobs: list[dict], industry: str) -> list[dict]:
    """Filters the list of jobs by industry."""
    if not industry or industry == "All":
        return jobs
    return [j for j in jobs if j.get("industry") == industry]

# Larger hashing dim than the crowd default (256) to avoid bucket collisions that
# made unrelated jobs spuriously match short queries like "finance".
_SEARCH_EMBED_DIM = 8192


def _default_embedder():
    return HashingEmbedder(dim=_SEARCH_EMBED_DIM)


def _job_embed_text(job: dict) -> str:
    """Build the lexical search document for a job.

    Includes industry + category so queries like "finance" match Finance-industry
    roles whose titles don't literally contain the word (e.g. "Credit Analyst").
    """
    skills_str = ", ".join(job.get("required_skills", []))
    parts = [
        job.get("title", ""),
        job.get("title_zh", ""),
        job.get("industry", ""),
        job.get("category", ""),
        job.get("description", ""),
        job.get("description_zh", ""),
        skills_str,
    ]
    return " ".join(p for p in parts if p)


_KNOWN_INDUSTRIES = (
    "Agriculture", "Construction", "Education", "Finance", "Government",
    "Healthcare", "Hospitality", "Legal", "Logistics", "Manufacturing",
    "Media", "Retail", "Tech",
)
_QUERY_STOPWORDS = frozenset({"and", "the", "for", "with", "from", "role", "jobs"})


def _query_tokens(query: str) -> list[str]:
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 3]
    return [t for t in tokens if t not in _QUERY_STOPWORDS]


def _lexical_overlap(query: str, text: str) -> float:
    tokens = _query_tokens(query)
    if not tokens:
        return 0.0
    text_l = text.lower()
    return sum(1 for t in tokens if t in text_l) / len(tokens)


def _industry_only_query(query: str) -> str | None:
    q = query.strip().lower()
    for ind in _KNOWN_INDUSTRIES:
        if q == ind.lower():
            return ind
    return None


def _score_job_match(query: str, job: dict, q_emb: list[float], j_emb: list[float]) -> dict:
    """Blend embedding + lexical overlap; penalise multi-word queries that only hit one token."""
    emb_sim = sum(a * b for a, b in zip(q_emb, j_emb))
    text = _job_embed_text(job)
    lex = _lexical_overlap(query, text)
    combined = 0.45 * emb_sim + 0.55 * lex

    tokens = _query_tokens(query)
    if len(tokens) >= 2:
        hits = sum(1 for t in tokens if t in text.lower())
        min_hits = max(2, (len(tokens) + 1) // 2)
        if hits < min_hits:
            combined *= 0.45

    if _industry_only_query(query) and not is_ai_role(job):
        combined = min(1.0, combined + 0.08)

    return {
        "semantic_similarity": round(emb_sim, 3),
        "lexical_overlap": round(lex, 3),
        "combined_similarity": round(combined, 3),
    }


def _apply_search_scores(jobs: list[dict], query: str, embedder=None) -> list[dict]:
    if embedder is None:
        embedder = _default_embedder()
    q_emb = embedder.embed([query])[0]
    texts = [_job_embed_text(j) for j in jobs]
    j_embs = embedder.embed(texts)
    for idx, j in enumerate(jobs):
        scores = _score_job_match(query, j, q_emb, j_embs[idx])
        j.update(scores)
    return jobs


def get_hybrid_scores(jobs: list[dict], query: str, alpha: float, beta: float, embedder=None) -> list[dict]:
    """
    Calculates hybrid score: alpha * impact_score + beta * search relevance.
    When a query is present, relevance uses combined embedding + lexical overlap
    (not embedding alone), and results should be sorted by hybrid_score with
    search-weighted coefficients so impact_score does not dominate.
    """
    if not query:
        for j in jobs:
            j["semantic_similarity"] = 0.0
            j["lexical_overlap"] = 0.0
            j["combined_similarity"] = 0.0
            j["hybrid_score"] = round(alpha * j.get("impact_score", 0.0), 3)
        return jobs

    _apply_search_scores(jobs, query, embedder)
    # When searching, weight relevance heavily so impact_score does not dominate ordering.
    search_alpha, search_beta = 0.05, 0.95
    for j in jobs:
        rel = j.get("combined_similarity", j.get("semantic_similarity", 0.0))
        j["hybrid_score"] = round(
            search_alpha * j.get("impact_score", 0.0) + search_beta * rel,
            3,
        )

    return jobs

def _normalize_transition_target(target) -> dict | None:
    """Accept KB dict entries or bare target_id strings (common LLM output)."""
    if isinstance(target, str):
        return {
            "target_id": target,
            "skill_bridge": None,
            "retrain_months": None,
            "salary_delta": None,
        }
    if isinstance(target, dict):
        tid = target.get("target_id")
        if isinstance(tid, str):
            return target
    return None


def _normalize_transition_targets(targets) -> list[dict]:
    if not targets:
        return []
    out: list[dict] = []
    for raw in targets:
        norm = _normalize_transition_target(raw)
        if norm:
            out.append(norm)
    return out


_AI_TITLE_PAT = re.compile(
    r"\b(AI|LLM|Prompt|Robot|Roboticist|Algorithmic|Autonomous|Digital Twin|Agent|Machine Learning)\b",
    re.IGNORECASE,
)


def is_ai_role(job: dict) -> bool:
    """Heuristic: does the role's title denote an AI-native occupation?"""
    return bool(_AI_TITLE_PAT.search(job.get("title", "")))


def _skill_overlap(a: dict, b: dict) -> int:
    """Count shared required skills (case-insensitive) between two jobs."""
    sa = {s.strip().lower() for s in a.get("required_skills", [])}
    sb = {s.strip().lower() for s in b.get("required_skills", [])}
    return len(sa & sb)


def get_transition_details(current_job_id: str, all_jobs: list[dict]) -> list[dict]:
    """
    Finds transition paths for a current job ID and returns detailed profiles of target jobs.
    """
    # Create lookup map
    jobs_map = {j["id"]: j for j in all_jobs}
    current_job = jobs_map.get(current_job_id)
    if not current_job:
        return []
        
    transitions = []
    for raw in current_job.get("transition_targets", []):
        target = _normalize_transition_target(raw)
        if not target:
            continue
        target_id = target["target_id"]
        target_job = jobs_map.get(target_id)
        if target_job:
            detail = {
                "id": target_id,
                "title": target_job.get("title"),
                "title_zh": target_job.get("title_zh"),
                "industry": target_job.get("industry"),
                "category": target_job.get("category"),
                "skill_bridge": target.get("skill_bridge"),
                # Coerce None (e.g. from bare-string LLM targets) to safe numerics
                # so the UI can compare/format without TypeError.
                "retrain_months": target.get("retrain_months") if target.get("retrain_months") is not None else 0,
                "salary_delta": target.get("salary_delta") if target.get("salary_delta") is not None else 0.0,
                "description": target_job.get("description"),
                "description_zh": target_job.get("description_zh"),
                # First 2 required skills for Skill Bridge summary line
                "required_skills_preview": target_job.get("required_skills", [])[:2],
                # Reasoning signals (transparency: why this path is suggested)
                "is_ai": is_ai_role(target_job),
                "skill_overlap": _skill_overlap(current_job, target_job),
                "current_displacement_risk": current_job.get("displacement_risk"),
                "target_displacement_risk": target_job.get("displacement_risk"),
            }
            transitions.append(detail)
            
    return transitions

# --------------------------------------------------------------------------- #
# Real-time transition derivation (model-based, not static KB lists)
# --------------------------------------------------------------------------- #

# Default weights for the composite transition score. Override via
# config.yaml -> job_radar.transition.{skill,overlap,risk,demand}.
_TRANSITION_WEIGHTS = {
    "skill": 0.40,    # skill-vector proximity (ease of transition)
    "overlap": 0.15,  # shared concrete skills (Jaccard)
    "risk": 0.25,     # reduction in automation/displacement risk
    "demand": 0.20,   # target's forward demand under the active scenario
}

# Skill vectors live in [0, 1]^8, so the max Euclidean distance is sqrt(8).
_MAX_SKILL_DIST = math.sqrt(8.0)


def _skill_distance(a: dict, b: dict) -> float:
    """Normalised Euclidean distance between two 8-dim skill vectors → [0, 1]."""
    va = a.get("skill_vector") or []
    vb = b.get("skill_vector") or []
    n = min(len(va), len(vb))
    if n == 0:
        return 1.0
    dist = math.sqrt(sum((va[i] - vb[i]) ** 2 for i in range(n)))
    return min(1.0, dist / _MAX_SKILL_DIST)


def _skill_jaccard(a: dict, b: dict) -> float:
    sa = {s.strip().lower() for s in a.get("required_skills", [])}
    sb = {s.strip().lower() for s in b.get("required_skills", [])}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _skill_gap(current: dict, target: dict, limit: int = 3) -> list[str]:
    """Target skills the current role lacks — the concrete bridge to close."""
    have = {s.strip().lower() for s in current.get("required_skills", [])}
    gap = [s for s in target.get("required_skills", []) if s.strip().lower() not in have]
    return gap[:limit]


def compute_transition_paths(
    current_job: dict,
    all_jobs: list[dict],
    scenario: dict,
    *,
    top_k: int = 3,
    weights: dict | None = None,
) -> list[dict]:
    """Derive transition targets live from skill-vector distance, risk reduction
    and scenario-driven demand — instead of reading static ``transition_targets``.

    Returns detail dicts compatible with the radar transition cards, with extra
    transparency fields (skill_distance, transition_score, demand_outlook).
    """
    w = {**_TRANSITION_WEIGHTS, **(weights or {})}
    cur_risk = float(current_job.get("displacement_risk") or 0.0)

    # Score every other job under the active scenario in one pass.
    scored = compute_impact_scores(all_jobs, scenario)
    impact_by_id = {j["id"]: j["impact_score"] for j in scored}

    demands = [impact_by_id.get(j["id"], 0.0) for j in all_jobs if j["id"] != current_job.get("id")]
    d_min, d_max = (min(demands), max(demands)) if demands else (0.0, 1.0)
    d_span = (d_max - d_min) or 1.0

    candidates = []
    for tgt in all_jobs:
        if tgt.get("id") == current_job.get("id"):
            continue
        # Don't recommend jumping into another high-displacement (dying) role.
        if tgt.get("category") == "at_risk":
            continue

        dist = _skill_distance(current_job, tgt)
        proximity = 1.0 - dist
        jacc = _skill_jaccard(current_job, tgt)
        tgt_risk = float(tgt.get("displacement_risk") or 0.0)
        risk_reduction = max(0.0, cur_risk - tgt_risk)
        demand_raw = impact_by_id.get(tgt["id"], 0.0)
        demand_norm = (demand_raw - d_min) / d_span

        score = (
            w["skill"] * proximity
            + w["overlap"] * jacc
            + w["risk"] * risk_reduction
            + w["demand"] * demand_norm
        )

        candidates.append({
            "id": tgt["id"],
            "title": tgt.get("title"),
            "title_zh": tgt.get("title_zh"),
            "industry": tgt.get("industry"),
            "category": tgt.get("category"),
            "description": tgt.get("description"),
            "description_zh": tgt.get("description_zh"),
            "is_ai": is_ai_role(tgt),
            "skill_overlap": _skill_overlap(current_job, tgt),
            "skill_distance": round(dist, 3),
            "skill_proximity": round(proximity, 3),
            "transition_score": round(score, 3),
            "current_displacement_risk": cur_risk,
            "target_displacement_risk": tgt_risk,
            "demand_outlook": round(demand_raw, 3),
            # Retraining time scales with skill distance: 3..24 months.
            "retrain_months": int(round(3 + 21 * dist)),
            "skill_bridge_skills": _skill_gap(current_job, tgt),
            "required_skills_preview": tgt.get("required_skills", [])[:2],
        })

    candidates.sort(key=lambda c: c["transition_score"], reverse=True)
    return candidates[:top_k]


def compute_timeline(jobs: list[dict], diffusion_years: float) -> list[dict]:
    """
    Calculates projected emergence years for emerging jobs.
    Formula: Projected = 2026 + (emergence_year - 2026) * (diffusion_years / 10.0)
    We anchor baseline_diffusion at 10.0.
    """
    timeline_jobs = []
    current_year = 2026
    baseline_diffusion = 10.0
    
    for j in jobs:
        if j.get("category") == "emerging" and j.get("emergence_year"):
            base_year = j["emergence_year"]
            years_to_emergence = base_year - current_year
            
            # Scale based on the diffusion rate (speed of AI adoption)
            # Faster diffusion (lower diffusion_years) shifts emergence earlier
            # Slower diffusion (higher diffusion_years) shifts emergence later
            scaling_factor = diffusion_years / baseline_diffusion
            projected_year = max(current_year, current_year + years_to_emergence * scaling_factor)
            
            # Round to 1 decimal place or year
            projected_year_rounded = round(projected_year, 1)
            
            job_copy = j.copy()
            job_copy["projected_emergence_year"] = projected_year_rounded
            timeline_jobs.append(job_copy)
            
    # Sort timeline by projected year
    timeline_jobs.sort(key=lambda x: x["projected_emergence_year"])
    return timeline_jobs


def save_job_feedback(feedback_obj) -> None:
    """Saves a crowd-sourced job transition feedback record to the database."""
    from schemas import engine
    from sqlmodel import Session
    with Session(engine) as session:
        session.add(feedback_obj)
        session.commit()


def get_empirical_metrics() -> dict:
    """
    Aggregates JobFeedback records to compute empirical displacement rates,
    average worker confidence, and top transition targets by job title.
    """
    from schemas import engine, JobFeedback
    from sqlmodel import Session, select
    
    metrics = {}
    with Session(engine) as session:
        statement = select(JobFeedback)
        feedbacks = session.exec(statement).all()
        
    # Group feedbacks by job title
    by_job = {}
    for f in feedbacks:
        # Canonicalize job title key
        title = f.job_title.strip()
        by_job.setdefault(title, []).append(f)
        
    for title, f_list in by_job.items():
        total = len(f_list)
        unemployed = sum(1 for f in f_list if f.status == "unemployed")
        transitioning = sum(1 for f in f_list if f.status == "transitioning")
        
        emp_displacement_rate = (unemployed + transitioning) / total if total else 0.0
        avg_confidence = sum(f.confidence for f in f_list) / total if total else 1.0
        
        # Find most common transition targets
        targets = {}
        for f in f_list:
            if f.transition_target:
                t_title = f.transition_target.strip()
                targets[t_title] = targets.get(t_title, 0) + 1
                
        sorted_targets = sorted(targets.items(), key=lambda x: x[1], reverse=True)
        top_targets = [t[0] for t in sorted_targets[:3]]
        
        metrics[title] = {
            "total_responses": total,
            "unemployed_count": unemployed,
            "transitioning_count": transitioning,
            "empirical_displacement_rate": round(emp_displacement_rate, 3),
            "average_confidence": round(avg_confidence, 3),
            "top_empirical_targets": top_targets
        }
    return metrics


# ---------------------------------------------------------------------------
# Dynamic KB expansion via LLM (when search query has no close match)
# ---------------------------------------------------------------------------

_SIMILARITY_THRESHOLD = 0.42   # below → no confident KB match (LLM expansion)
_STRONG_MATCH_THRESHOLD = 0.55  # above → green "search hit" banner


def find_best_match(query: str, jobs: list[dict], embedder=None) -> tuple[float, dict | None]:
    """Return (combined_similarity, best_job) for the query against the KB."""
    if not jobs or not query:
        return 0.0, None

    if embedder is None:
        embedder = _default_embedder()

    pool = jobs
    ind = _industry_only_query(query)
    if ind:
        subset = [j for j in jobs if j.get("industry") == ind]
        if subset:
            pool = subset

    _apply_search_scores(pool, query, embedder)
    best = max(pool, key=lambda j: j.get("combined_similarity", 0.0))
    return best.get("combined_similarity", 0.0), best


# --------------------------------------------------------------------------- #
# LLM profile cache — the only token-spending path. Cache by an order-independent
# query signature so synonyms/word-order variants reuse a generation instead of
# re-prompting the model. (Persists within the container; cleared on rebuild.)
# --------------------------------------------------------------------------- #

_LLM_CACHE_PATH = "data/llm_job_cache.json"


def _query_signature(query: str) -> str:
    """Order-independent normalized key: lowercased, de-punctuated, sorted tokens."""
    toks = re.findall(r"[a-z0-9]+", (query or "").lower())
    return " ".join(sorted(toks))


def _load_llm_cache(path: str | None = None) -> dict[str, dict]:
    path = path or _LLM_CACHE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_llm_cache(cache: dict[str, dict], path: str | None = None) -> None:
    path = path or _LLM_CACHE_PATH
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # cache is best-effort; never break the request path


def get_cached_job_profile(query: str, path: str | None = None) -> dict | None:
    """Return a previously generated profile for an equivalent query, else None."""
    sig = _query_signature(query)
    if not sig:
        return None
    return _load_llm_cache(path).get(sig)


def generate_job_profile_via_llm(query: str) -> dict | None:
    """Use the LLM to generate a full KB-compatible job profile for an unknown role.

    Returns a dict matching the KB schema, or None on failure. Results are cached
    by query signature (token-sorted) so equivalent queries skip the LLM call,
    and appended to data/jobs_kb.json on disk.
    """
    # Cache hit → zero tokens.
    cached = get_cached_job_profile(query)
    if cached is not None:
        cached = dict(cached)
        cached["_from_cache"] = True
        _append_to_kb(cached)  # ensure KB has it (idempotent by id)
        return cached

    try:
        from forecast import call_llm
    except ImportError:
        return None

    system_prompt = """You are an expert labor economist. Given a job title or role description,
generate a complete JSON job profile for an AI displacement forecasting knowledge base.

You MUST return ONLY valid JSON (no markdown, no explanation) with exactly these fields:
{
  "id": "short_snake_case_id",
  "title": "English Job Title",
  "title_zh": "中文职位名称",
  "industry": "one of: Finance, Tech, Manufacturing, Healthcare, Education, Legal, Logistics, Retail, Agriculture, Construction, Hospitality, Government, Media",
  "category": "one of: at_risk, transforming, emerging",
  "description": "2-3 sentence English description of the role and how AI impacts it",
  "description_zh": "2-3句中文描述",
  "sensitivity": {
    "augmentation_ratio": float between -1 and 1,
    "demand_elasticity": float between -1 and 1,
    "oring_leverage": float between -1 and 1,
    "skill_distance": float between -1 and 1,
    "diffusion_years": float between -1 and 1,
    "absorbing_sector": float between -1 and 1,
    "productivity_capture": float between -1 and 1,
    "task_frontier_open": float between -1 and 1
  },
  "base_demand_trend": float between -0.5 and 0.5,
  "displacement_risk": float between 0 and 1,
  "required_skills": ["skill1", "skill2", "skill3", "skill4"],
  "skill_vector": [8 floats between 0 and 1],
  "emergence_year": null or integer year (2026-2040) if category is "emerging",
  "sources": ["source1", "source2"],
  "transition_targets": []
}

Base your economic sensitivity values on labor economics theory (Autor, Jevons, Kremer, Baumol).
Be realistic and well-calibrated with displacement_risk."""

    user_prompt = f"Generate a job profile for: {query}"

    try:
        raw = call_llm(system_prompt, user_prompt, max_tokens=2000)
        # Extract JSON from response (handle possible markdown wrapping)
        text = raw.strip()
        if text.startswith("```"):
            # Strip markdown code fences
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines)

        profile = json.loads(text)

        # Validate minimum required fields
        required = ["id", "title", "industry", "category", "description",
                     "sensitivity", "displacement_risk", "required_skills"]
        if not all(k in profile for k in required):
            return None

        profile["transition_targets"] = _normalize_transition_targets(
            profile.get("transition_targets", [])
        )

        # Persist: query-signature cache (skip future LLM calls) + KB append.
        cache = _load_llm_cache()
        cache[_query_signature(query)] = profile
        _save_llm_cache(cache)
        _append_to_kb(profile)

        return profile

    except Exception:
        return None


def _append_to_kb(profile: dict, kb_path: str = "data/jobs_kb.json") -> None:
    """Append a new job profile to the KB JSON file (idempotent by id)."""
    if not os.path.exists(kb_path):
        return
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        # Don't add duplicates
        existing_ids = {j["id"] for j in kb}
        if profile["id"] in existing_ids:
            return
        kb.append(profile)
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # fail silently — KB is still usable from memory
