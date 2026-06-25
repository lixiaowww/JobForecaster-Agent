import hashlib
import json
import math
import os
import re
from typing import Any
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

# Canonical hot roles that must hit the KB strongly (HR-7 coverage guardrail).
CORE_HOT_ROLE_QUERIES: tuple[tuple[str, str], ...] = (
    ("software product manager", "tech_product_manager"),
    ("product manager", "tech_product_manager"),
    ("产品经理", "tech_product_manager"),
    ("software developer", "tech_software_eng"),
    ("software engineer", "tech_software_eng"),
    ("程序员", "tech_software_eng"),
    ("data scientist", "tech_data_scientist"),
    ("project manager", "tech_project_manager"),
)


def assert_core_hot_role_coverage(
    jobs: list[dict] | None = None,
    search_cfg: dict | None = None,
) -> None:
    """Raise AssertionError if a core role query misses its expected KB id."""
    pool = jobs if jobs is not None else load_knowledge_base()
    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    weak = float(cfg["tier_weak"])
    for query, expected_id in CORE_HOT_ROLE_QUERIES:
        sim, best = find_best_match(query, pool, search_cfg=cfg)
        assert best is not None, f"no match for {query!r}"
        assert best["id"] == expected_id, (
            f"{query!r} → {best.get('id')} (expected {expected_id}, sim={sim})"
        )
        assert sim >= weak, f"{query!r} sim {sim} < tier_weak {weak}"


# Larger hashing dim than the crowd default (256) to avoid bucket collisions that
# made unrelated jobs spuriously match short queries like "finance".
_SEARCH_EMBED_DIM = 8192


def _default_embedder():
    return RadarHashingEmbedder(dim=_SEARCH_EMBED_DIM)


_SEARCH_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}")


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class RadarHashingEmbedder(HashingEmbedder):
    """Hashing embedder with CJK token support for bilingual job search."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in _SEARCH_TOKEN.findall(text.lower()):
                if tok in _QUERY_STOPWORDS and tok.isascii():
                    continue
                bucket = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "big")
                v[bucket % self.dim] += 1.0
            out.append(_l2(v))
        return out


_ST_MODEL: Any = None  # module-level singleton, loaded once
_ST_CACHE: dict[str, list[float]] = {}  # md5(text) → normalised vector


class SentenceEmbedder:
    """Semantic embedder backed by sentence-transformers (multilingual MiniLM).

    Falls back to RadarHashingEmbedder if the package is not installed so that
    the codebase stays importable in minimal environments (e.g. CI without the
    extra dependency).
    """

    MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

    def _model(self) -> Any:
        global _ST_MODEL
        if _ST_MODEL is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _ST_MODEL = SentenceTransformer(self.MODEL_NAME)
        return _ST_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float] | None] = [None] * len(texts)
        miss_idx: list[int] = []
        miss_txt: list[str] = []
        for i, t in enumerate(texts):
            key = hashlib.md5(t.encode()).hexdigest()
            if key in _ST_CACHE:
                result[i] = _ST_CACHE[key]
            else:
                miss_idx.append(i)
                miss_txt.append(t)
        if miss_txt:
            model = self._model()
            vecs = model.encode(miss_txt, normalize_embeddings=True).tolist()
            for i, (idx, text) in enumerate(zip(miss_idx, miss_txt)):
                key = hashlib.md5(text.encode()).hexdigest()
                _ST_CACHE[key] = vecs[i]
                result[idx] = vecs[i]
        return result  # type: ignore[return-value]


_SENTENCE_EMBEDDER: SentenceEmbedder | None = None
_EMBEDDER_FALLBACK_REASON: str | None = None


def embedder_fallback_reason() -> str | None:
    """Set when ``sentence_transformers`` was requested but hashing is used."""
    return _EMBEDDER_FALLBACK_REASON


def resolve_embedder(search_cfg: dict | None = None) -> Any:
    """Return the configured embedder: ``sentence_transformers`` or ``hashing``."""
    global _SENTENCE_EMBEDDER, _EMBEDDER_FALLBACK_REASON
    name = (search_cfg or {}).get("embedder", "hashing")
    if name != "sentence_transformers":
        _EMBEDDER_FALLBACK_REASON = None
        return _default_embedder()
    try:
        if _SENTENCE_EMBEDDER is None:
            _SENTENCE_EMBEDDER = SentenceEmbedder()
        _EMBEDDER_FALLBACK_REASON = None
        return _SENTENCE_EMBEDDER
    except Exception as exc:
        _EMBEDDER_FALLBACK_REASON = str(exc)
        return _default_embedder()


def _job_embed_text(job: dict) -> str:
    """Full lexical document for a job (used for token-overlap scoring)."""
    skills_str = ", ".join(job.get("required_skills", []))
    aliases_str = " ".join(job.get("search_aliases", []))
    parts = [
        job.get("title", ""),
        job.get("title_zh", ""),
        aliases_str,
        job.get("industry", ""),
        job.get("category", ""),
        job.get("description", ""),
        job.get("description_zh", ""),
        skills_str,
    ]
    return " ".join(p for p in parts if p)


def _job_embed_title(job: dict) -> str:
    """Short title document for semantic embedding.

    Using only title + aliases keeps the semantic vector focused on the role
    name rather than letting description vocabulary dilute the match.
    """
    aliases_str = " ".join(job.get("search_aliases", []))
    parts = [job.get("title", ""), job.get("title_zh", ""), aliases_str]
    return " ".join(p for p in parts if p)


_KNOWN_INDUSTRIES = (
    "Agriculture", "Construction", "Education", "Finance", "Government",
    "Healthcare", "Hospitality", "Legal", "Logistics", "Manufacturing",
    "Media", "Retail", "Tech",
)
_QUERY_STOPWORDS = frozenset({"and", "the", "for", "with", "from", "role", "jobs"})

# Normalize common alternate job titles before retrieval (HR-7 hot-role coverage).
_QUERY_TITLE_ALIASES: dict[str, str] = {
    "software developer": "software engineer",
    "software development": "software engineer",
    "programmer": "software engineer",
    "coder": "software engineer",
    "full stack developer": "software engineer",
    "backend developer": "software engineer",
    "frontend developer": "software engineer",
    "dev": "software engineer",
    "product owner": "product manager",
    "technical product manager": "product manager",
    "tpm": "project manager",
    "program manager": "project manager",
}


def normalize_search_query(query: str, search_cfg: dict | None = None) -> str:
    """Map high-traffic alternate titles to canonical KB search phrases."""
    q = (query or "").strip()
    if not q:
        return q
    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    aliases = cfg.get("title_aliases") or _QUERY_TITLE_ALIASES
    key = q.lower()
    if key in aliases:
        return aliases[key]
    return q


def _query_tokens(query: str) -> list[str]:
    # Keep all tokens ≥ 2 chars; only drop pure-ASCII single characters.
    # This preserves domain abbreviations like "ml", "hr", "qa", "gp".
    tokens = [t for t in _SEARCH_TOKEN.findall(query.lower()) if len(t) >= 2]
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


# --------------------------------------------------------------------------- #
# Search config (HR-3) — defaults mirror pre-Phase-8 code constants
# --------------------------------------------------------------------------- #

_DEFAULT_SEARCH_CONFIG: dict = {
    "embed_weight": 0.45,
    "lex_weight": 0.55,
    "multi_word_penalty": 0.45,
    "industry_only_boost": 0.08,
    "tier_no_match": 0.42,
    "tier_weak": 0.55,
    "tier_strong": 0.65,
    "title_aliases": {},
}

_DEFAULT_TRANSITION_CONFIG: dict = {
    "skill": 0.40,
    "overlap": 0.15,
    "risk": 0.25,
    "demand": 0.20,
}

_DEFAULT_PERSONALIZATION_CONFIG: dict = {
    "junior_retrain_cap_months": 6,
    "mid_retrain_cap_months": 12,
    "senior_retrain_cap_months": 24,
    "min_stratified_responses": 5,
}

EXPERIENCE_LEVELS: tuple[str, ...] = ("junior", "mid", "senior")

# Backward-compat module aliases (tests / legacy imports)
_SIMILARITY_THRESHOLD = _DEFAULT_SEARCH_CONFIG["tier_no_match"]
_STRONG_MATCH_THRESHOLD = _DEFAULT_SEARCH_CONFIG["tier_weak"]


def resolve_search_config(job_radar_cfg: dict | None = None) -> dict:
    """Merge ``config.yaml`` → ``job_radar.search`` with offline-safe defaults."""
    cfg = job_radar_cfg or {}
    merged = {**_DEFAULT_SEARCH_CONFIG, **cfg.get("search", {})}
    file_aliases = dict(merged.get("title_aliases") or {})
    merged["title_aliases"] = {**_QUERY_TITLE_ALIASES, **file_aliases}
    return merged


def resolve_transition_config(job_radar_cfg: dict | None = None) -> dict:
    cfg = job_radar_cfg or {}
    return {**_DEFAULT_TRANSITION_CONFIG, **cfg.get("transition", {})}


def resolve_personalization_config(job_radar_cfg: dict | None = None) -> dict:
    cfg = job_radar_cfg or {}
    return {**_DEFAULT_PERSONALIZATION_CONFIG, **cfg.get("personalization", {})}


def search_match_tier(sim: float, search_cfg: dict | None = None) -> str:
    """User-facing retrieval tier: ``none`` | ``weak`` | ``strong`` (HR-12)."""
    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    if sim < float(cfg["tier_no_match"]):
        return "none"
    if sim < float(cfg["tier_strong"]):
        return "weak"
    return "strong"


def _score_job_match(
    query: str,
    job: dict,
    q_emb: list[float],
    j_emb: list[float],
    search_cfg: dict | None = None,
) -> dict:
    """Blend embedding + lexical overlap; penalise multi-word queries that only hit one token."""
    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    w_emb = float(cfg["embed_weight"])
    w_lex = float(cfg["lex_weight"])
    emb_sim = sum(a * b for a, b in zip(q_emb, j_emb))
    text = _job_embed_text(job)
    lex = _lexical_overlap(query, text)
    combined = w_emb * emb_sim + w_lex * lex

    tokens = _query_tokens(query)
    if len(tokens) >= 2:
        hits = sum(1 for t in tokens if t in text.lower())
        min_hits = max(2, (len(tokens) + 1) // 2)
        if hits < min_hits:
            combined *= float(cfg["multi_word_penalty"])

    if _industry_only_query(query) and not is_ai_role(job):
        combined = min(1.0, combined + float(cfg["industry_only_boost"]))

    return {
        "semantic_similarity": round(emb_sim, 3),
        "lexical_overlap": round(lex, 3),
        "combined_similarity": round(combined, 3),
    }


def _apply_search_scores(
    jobs: list[dict],
    query: str,
    embedder=None,
    search_cfg: dict | None = None,
) -> list[dict]:
    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    query = normalize_search_query(query, cfg)
    if embedder is None:
        embedder = resolve_embedder(cfg)
    # Semantic embeddings use only title+aliases (focused; avoids description dilution).
    # Lexical scoring still uses the full document text inside _score_job_match.
    is_semantic = isinstance(embedder, SentenceEmbedder)
    embed_fn = _job_embed_title if is_semantic else _job_embed_text
    q_emb = embedder.embed([query])[0]
    texts = [embed_fn(j) for j in jobs]
    j_embs = embedder.embed(texts)
    for idx, j in enumerate(jobs):
        scores = _score_job_match(query, j, q_emb, j_embs[idx], search_cfg)
        j.update(scores)
    return jobs


def get_hybrid_scores(
    jobs: list[dict],
    query: str,
    alpha: float,
    beta: float,
    embedder=None,
    search_cfg: dict | None = None,
) -> list[dict]:
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

    _apply_search_scores(jobs, query, embedder, search_cfg)
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
_TRANSITION_WEIGHTS = dict(_DEFAULT_TRANSITION_CONFIG)

# Skill vectors live in [0, 1]^8, so the max Euclidean distance is sqrt(8).
_MAX_SKILL_DIST = math.sqrt(8.0)

# Cache skill semantic similarity by sorted id pair (symmetric).
_SKILL_SEM_CACHE: dict[tuple[str, str], float] = {}


def _skill_semantic_sim(a: dict, b: dict) -> float:
    """Cosine similarity between the required_skills text of two roles.

    Uses the module-level SentenceEmbedder when available; falls back to 0.0
    (which is then overridden by domain_proximity in the caller).  Results are
    cached by sorted (id_a, id_b) pair so each pair is embedded once per process.
    """
    id_a, id_b = a.get("id", ""), b.get("id", "")
    key: tuple[str, str] = (min(id_a, id_b), max(id_a, id_b))
    if key in _SKILL_SEM_CACHE:
        return _SKILL_SEM_CACHE[key]

    skills_a = ", ".join(a.get("required_skills") or [])
    skills_b = ", ".join(b.get("required_skills") or [])
    if not skills_a or not skills_b or _SENTENCE_EMBEDDER is None:
        result = 0.0
    else:
        try:
            embs = _SENTENCE_EMBEDDER.embed([skills_a, skills_b])
            result = float(sum(x * y for x, y in zip(embs[0], embs[1])))
            result = max(0.0, min(1.0, result))
        except Exception:
            result = 0.0

    _SKILL_SEM_CACHE[key] = result
    return result


def _skill_distance(a: dict, b: dict) -> float:
    """Normalised Euclidean distance between two 8-dim economic sensitivity vectors → [0, 1]."""
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


# Industries that share enough domain knowledge for a realistic lateral move.
_ADJACENT_INDUSTRIES: dict[str, frozenset[str]] = {
    "Finance":        frozenset({"Finance", "Legal", "Government"}),
    "Legal":          frozenset({"Legal", "Finance", "Government"}),
    "Tech":           frozenset({"Tech", "Media"}),
    "Healthcare":     frozenset({"Healthcare", "Education"}),
    "Education":      frozenset({"Education", "Healthcare", "Government"}),
    "Manufacturing":  frozenset({"Manufacturing", "Construction", "Logistics"}),
    "Construction":   frozenset({"Construction", "Manufacturing"}),
    "Logistics":      frozenset({"Logistics", "Manufacturing", "Retail"}),
    "Retail":         frozenset({"Retail", "Logistics", "Hospitality"}),
    "Agriculture":    frozenset({"Agriculture", "Manufacturing"}),
    "Hospitality":    frozenset({"Hospitality", "Retail"}),
    "Government":     frozenset({"Government", "Legal", "Education"}),
    "Media":          frozenset({"Media", "Tech"}),
}


def _domain_proximity(a: dict, b: dict) -> float:
    """Return 1.0 for same industry, 0.5 for adjacent, 0.0 for unrelated.

    Replaces _skill_jaccard in transition scoring — jaccard is always 0 because
    KB required_skills use unique multi-word phrases that never overlap.
    """
    ind_a = (a.get("industry") or "").strip()
    ind_b = (b.get("industry") or "").strip()
    if not ind_a or not ind_b:
        return 0.5  # unknown → neutral
    if ind_a == ind_b:
        return 1.0
    if ind_b in _ADJACENT_INDUSTRIES.get(ind_a, frozenset()):
        return 0.5
    return 0.0


def _skill_gap(current: dict, target: dict, limit: int = 3) -> list[str]:
    """Target skills the current role lacks — the concrete bridge to close."""
    have = {s.strip().lower() for s in current.get("required_skills", [])}
    gap = [s for s in target.get("required_skills", []) if s.strip().lower() not in have]
    return gap[:limit]


def personalization_weights(
    base: dict | None = None,
    *,
    experience_level: str = "mid",
    personalization_cfg: dict | None = None,
) -> dict:
    """Adjust transition score weights for user seniority (HR-2 pure, testable)."""
    w = {**_TRANSITION_WEIGHTS, **(base or {})}
    pcfg = personalization_cfg or _DEFAULT_PERSONALIZATION_CONFIG
    level = experience_level if experience_level in EXPERIENCE_LEVELS else "mid"
    if level == "junior":
        w["overlap"] = w.get("overlap", 0.15) + 0.05
        w["skill"] = w.get("skill", 0.40) + 0.05
        w["demand"] = max(0.0, w.get("demand", 0.20) - 0.05)
    elif level == "senior":
        w["demand"] = w.get("demand", 0.20) + 0.05
        w["risk"] = w.get("risk", 0.25) + 0.05
        w["overlap"] = max(0.0, w.get("overlap", 0.15) - 0.05)
    total = sum(w.values()) or 1.0
    return {k: round(v / total, 4) for k, v in w.items()}


def retrain_cap_for_level(
    experience_level: str,
    personalization_cfg: dict | None = None,
    override_months: int | None = None,
) -> int:
    """Max acceptable retrain months for the user's experience band."""
    if override_months is not None:
        return int(override_months)
    pcfg = personalization_cfg or _DEFAULT_PERSONALIZATION_CONFIG
    key = f"{experience_level}_retrain_cap_months"
    if experience_level in EXPERIENCE_LEVELS and key in pcfg:
        return int(pcfg[key])
    return int(pcfg.get("mid_retrain_cap_months", 12))


def compute_transition_paths(
    current_job: dict,
    all_jobs: list[dict],
    scenario: dict,
    *,
    top_k: int = 3,
    weights: dict | None = None,
    experience_level: str | None = None,
    max_retrain_months: int | None = None,
    job_radar_cfg: dict | None = None,
) -> list[dict]:
    """Derive transition targets from KB-curated hints (when available) or dynamic
    skill-vector distance, risk reduction and scenario-driven demand.

    When ``current_job`` has ``transition_targets`` entries covering at least
    ``top_k`` slots, those IDs form the candidate pool so that human-validated
    paths are surface first.  Dynamic scoring still runs on the pool so results
    remain scenario-responsive.  For jobs without curated targets the algorithm
    falls back to the full job list (excluding ``at_risk`` roles).

    Returns detail dicts compatible with the radar transition cards, with extra
    transparency fields (skill_distance, transition_score, demand_outlook).
    """
    tcfg = resolve_transition_config(job_radar_cfg)
    pcfg = resolve_personalization_config(job_radar_cfg)
    if weights is None and experience_level:
        w = personalization_weights(
            tcfg,
            experience_level=experience_level,
            personalization_cfg=pcfg,
        )
    else:
        w = {**tcfg, **(weights or {})}
    retrain_cap = retrain_cap_for_level(
        experience_level or "mid",
        pcfg,
        max_retrain_months,
    )
    cur_risk = float(current_job.get("displacement_risk") or 0.0)

    # Score every other job under the active scenario in one pass.
    scored = compute_impact_scores(all_jobs, scenario)
    impact_by_id = {j["id"]: j["impact_score"] for j in scored}

    demands = [impact_by_id.get(j["id"], 0.0) for j in all_jobs if j["id"] != current_job.get("id")]
    d_min, d_max = (min(demands), max(demands)) if demands else (0.0, 1.0)
    d_span = (d_max - d_min) or 1.0

    # Build candidate pool: KB-curated targets take priority when there are enough
    # to fill top_k; otherwise fall through to the full dynamic pool.
    curated_entries = current_job.get("transition_targets") or []
    curated_by_id: dict[str, dict] = {
        ce["target_id"]: ce for ce in curated_entries if ce.get("target_id")
    }
    job_by_id = {j["id"]: j for j in all_jobs}

    if len(curated_by_id) >= top_k:
        # Curated pool first; pad with dynamic candidates if more are needed
        curated_jobs = [job_by_id[tid] for tid in curated_by_id if tid in job_by_id]
        dynamic_jobs = [
            j for j in all_jobs
            if j.get("id") not in curated_by_id
            and j.get("id") != current_job.get("id")
            and j.get("category") != "at_risk"
        ]
        pool = curated_jobs + dynamic_jobs
    else:
        curated_by_id = {}  # not enough curated → full dynamic
        pool = [j for j in all_jobs if j.get("id") != current_job.get("id")]

    candidates = []
    for tgt in pool:
        if tgt.get("id") == current_job.get("id"):
            continue
        # Don't recommend jumping into another high-displacement (dying) role.
        if tgt.get("category") == "at_risk":
            continue

        tid = tgt.get("id", "")
        is_curated = tid in curated_by_id
        dist = _skill_distance(current_job, tgt)
        proximity = 1.0 - dist
        domain_prox = _domain_proximity(current_job, tgt)
        # Real skill transferability: semantic cosine of required_skills text.
        # Weighted with domain_proximity so industry adjacency acts as a floor.
        skill_sem = _skill_semantic_sim(current_job, tgt)
        overlap_signal = 0.65 * skill_sem + 0.35 * domain_prox

        tgt_risk = float(tgt.get("displacement_risk") or 0.0)
        risk_reduction = max(0.0, cur_risk - tgt_risk)
        demand_raw = impact_by_id.get(tid, 0.0)
        demand_norm = (demand_raw - d_min) / d_span

        # LLM-evaluated transition confidence boosts score when cached.
        llm_conf = tgt.get("_transition_confidence", {}).get(current_job.get("id", ""), None)

        score = (
            w["skill"] * proximity
            + w["overlap"] * overlap_signal
            + w["risk"] * risk_reduction
            + w["demand"] * demand_norm
        )
        if llm_conf is not None:
            # Confidence acts as a multiplicative gate: 0.5 = neutral, <0.5 = penalise
            score *= (0.5 + llm_conf * 0.5)
        # KB-curated targets bypass the retrain cap and use the KB's time estimate.
        curated_hint = curated_by_id.get(tid, {})
        if is_curated:
            retrain_months = int(curated_hint.get("retrain_months") or round(3 + 21 * dist))
        else:
            retrain_months = int(round(3 + 21 * dist))
            if retrain_months > retrain_cap:
                continue

        # Prefer KB skill bridge text over computed gap when available.
        kb_bridge = curated_hint.get("skill_bridge", "")
        bridge_skills = (
            [kb_bridge] if kb_bridge else _skill_gap(current_job, tgt)
        )

        candidates.append({
            "id": tid,
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
            "retrain_months": retrain_months,
            "skill_bridge_skills": bridge_skills,
            "required_skills_preview": tgt.get("required_skills", [])[:2],
        })

    candidates.sort(key=lambda c: c["transition_score"], reverse=True)
    # Surface curated candidates first (stable-sort tie-breaking).
    candidates.sort(key=lambda c: c["id"] not in curated_by_id)
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


def _aggregate_feedback_metrics(f_list: list) -> dict:
    total = len(f_list)
    unemployed = sum(1 for f in f_list if f.status == "unemployed")
    transitioning = sum(1 for f in f_list if f.status == "transitioning")
    emp_displacement_rate = (unemployed + transitioning) / total if total else 0.0
    avg_confidence = sum(f.confidence for f in f_list) / total if total else 1.0
    targets: dict[str, int] = {}
    for f in f_list:
        if f.transition_target:
            t_title = f.transition_target.strip()
            targets[t_title] = targets.get(t_title, 0) + 1
    sorted_targets = sorted(targets.items(), key=lambda x: x[1], reverse=True)
    return {
        "total_responses": total,
        "unemployed_count": unemployed,
        "transitioning_count": transitioning,
        "empirical_displacement_rate": round(emp_displacement_rate, 3),
        "average_confidence": round(avg_confidence, 3),
        "top_empirical_targets": [t[0] for t in sorted_targets[:3]],
    }


def get_empirical_metrics(
    experience_level: str | None = None,
    *,
    job_radar_cfg: dict | None = None,
) -> dict:
    """
    Aggregates JobFeedback records to compute empirical displacement rates,
    average worker confidence, and top transition targets by job title.

    When *experience_level* is set and a (title, level) cell has ≥
  min_stratified_responses, that cell is used; otherwise falls back to title-only.
    """
    from schemas import engine, JobFeedback
    from sqlmodel import Session, select

    pcfg = resolve_personalization_config(job_radar_cfg)
    min_cell = int(pcfg.get("min_stratified_responses", 5))

    with Session(engine) as session:
        feedbacks = session.exec(select(JobFeedback)).all()

    by_title: dict[str, list] = {}
    by_title_level: dict[tuple[str, str], list] = {}
    for f in feedbacks:
        title = f.job_title.strip()
        level = getattr(f, "experience_level", None) or "mid"
        by_title.setdefault(title, []).append(f)
        by_title_level.setdefault((title, level), []).append(f)

    metrics: dict[str, dict] = {}
    for title, all_for_title in by_title.items():
        pool = all_for_title
        stratified = False
        if experience_level:
            cell = by_title_level.get((title, experience_level), [])
            if len(cell) >= min_cell:
                pool = cell
                stratified = True
        entry = _aggregate_feedback_metrics(pool)
        entry["stratified"] = stratified
        if stratified:
            entry["experience_level"] = experience_level
        metrics[title] = entry
    return metrics


# ---------------------------------------------------------------------------
# Dynamic KB expansion via LLM (when search query has no close match)
# ---------------------------------------------------------------------------


def find_best_match(
    query: str,
    jobs: list[dict],
    embedder=None,
    search_cfg: dict | None = None,
) -> tuple[float, dict | None]:
    """Return (combined_similarity, best_job) for the query against the KB."""
    if not jobs or not query:
        return 0.0, None

    cfg = search_cfg or _DEFAULT_SEARCH_CONFIG
    query = normalize_search_query(query, cfg)
    if embedder is None:
        embedder = resolve_embedder(cfg)

    pool = jobs
    ind = _industry_only_query(query)
    if ind:
        subset = [j for j in jobs if j.get("industry") == ind]
        if subset:
            pool = subset

    _apply_search_scores(pool, query, embedder, cfg)
    best = max(pool, key=lambda j: j.get("combined_similarity", 0.0))
    return best.get("combined_similarity", 0.0), best


def rank_jobs_by_transition_score(
    anchor: dict,
    jobs: list[dict],
    scenario: dict,
    *,
    experience_level: str | None = None,
    max_retrain_months: int | None = None,
    job_radar_cfg: dict | None = None,
) -> list[dict]:
    """HR-12: rank occupations by transition fit from *anchor*, not text search."""
    paths = compute_transition_paths(
        anchor,
        jobs,
        scenario,
        top_k=len(jobs),
        experience_level=experience_level,
        max_retrain_months=max_retrain_months,
        job_radar_cfg=job_radar_cfg,
    )
    score_by_id = {p["id"]: p["transition_score"] for p in paths}
    ranked = []
    for j in jobs:
        copy = j.copy()
        copy["transition_score"] = score_by_id.get(j["id"], 0.0)
        ranked.append(copy)
    ranked.sort(key=lambda x: x.get("transition_score", 0.0), reverse=True)
    return ranked


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


def generate_job_profile_via_llm(query: str, *, kb_path: str = "data/jobs_kb.json") -> dict | None:
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
        _append_to_kb(cached, kb_path)  # ensure KB has it (idempotent by id)
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

    # Enrich with real job description data when Tavily is available.
    try:
        from services.search_enrichment import search_job_context
        web_context = search_job_context(query)
    except Exception:
        web_context = ""

    if web_context:
        user_prompt = (
            f"Generate a job profile for: {query}\n\n"
            f"Use this real-world context to calibrate skills, industry, and risk:\n\n"
            f"{web_context}"
        )
    else:
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
        _append_to_kb(profile, kb_path)

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
        # Strip transition_targets that reference IDs not yet in KB, or that are at_risk
        # (recommending a dying role as a transition destination is misleading).
        kb_by_id = {j["id"]: j for j in kb}
        valid_targets = [
            t for t in profile.get("transition_targets", [])
            if t.get("target_id") in existing_ids
            and kb_by_id[t["target_id"]].get("category") != "at_risk"
        ]
        profile = {**profile, "transition_targets": valid_targets}
        kb.append(profile)
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # fail silently — KB is still usable from memory
