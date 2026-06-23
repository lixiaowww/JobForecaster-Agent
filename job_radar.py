import json
import math
import os
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


def get_hybrid_scores(jobs: list[dict], query: str, alpha: float, beta: float, embedder=None) -> list[dict]:
    """
    Calculates hybrid score: alpha * impact_score + beta * semantic_similarity.
    If query is empty, semantic similarity is set to 0.0 and hybrid score is alpha * impact_score.
    """
    if not query:
        for j in jobs:
            j["semantic_similarity"] = 0.0
            j["hybrid_score"] = round(alpha * j.get("impact_score", 0.0), 3)
        return jobs
        
    if embedder is None:
        embedder = _default_embedder()

    # Embed the query
    q_emb = embedder.embed([query])[0]
    
    # Pre-embed jobs
    texts = [_job_embed_text(j) for j in jobs]
    j_embs = embedder.embed(texts)
    
    # Calculate cosine similarity
    for idx, j in enumerate(jobs):
        emb = j_embs[idx]
        # Dot product since HashingEmbedder outputs L2 normalised vectors
        similarity = sum(q * val for q, val in zip(q_emb, emb))
        j["semantic_similarity"] = round(similarity, 3)
        j["hybrid_score"] = round(alpha * j.get("impact_score", 0.0) + beta * similarity, 3)
        
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
                "retrain_months": target.get("retrain_months"),
                "salary_delta": target.get("salary_delta"),
                "description": target_job.get("description"),
                "description_zh": target_job.get("description_zh"),
                # First 2 required skills for Skill Bridge summary line
                "required_skills_preview": target_job.get("required_skills", [])[:2],
            }
            transitions.append(detail)
            
    return transitions

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

_SIMILARITY_THRESHOLD = 0.15  # below this, we consider "not in KB"


def find_best_match(query: str, jobs: list[dict], embedder=None) -> tuple[float, dict | None]:
    """Return (max_similarity, best_job) for the query against the KB.
    If KB is empty, returns (0.0, None).
    """
    if not jobs or not query:
        return 0.0, None

    if embedder is None:
        embedder = _default_embedder()

    q_emb = embedder.embed([query])[0]
    texts = [_job_embed_text(j) for j in jobs]
    j_embs = embedder.embed(texts)
    best_sim = 0.0
    best_job = None
    for idx, j in enumerate(jobs):
        sim = sum(q * val for q, val in zip(q_emb, j_embs[idx]))
        if sim > best_sim:
            best_sim = sim
            best_job = j

    return best_sim, best_job


def generate_job_profile_via_llm(query: str) -> dict | None:
    """Use the LLM to generate a full KB-compatible job profile for an unknown role.

    Returns a dict matching the KB schema, or None on failure.
    The generated profile is also appended to data/jobs_kb.json on disk.
    """
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

        # Append to on-disk KB
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
