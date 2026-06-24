"""LLM-as-judge evaluator for career transition feasibility.

For each (anchor, candidate) pair the LLM returns:
  - feasibility: 0.0–1.0  (0.8+ natural, 0.5–0.7 retraining, 0.2–0.4 reskill, <0.2 extreme leap)
  - reasoning:   one sentence explaining the rating
  - recommended: bool

Results are cached in data/transition_eval_cache.json so each pair is evaluated once.
The calibration loop calls run_evaluation_pass() nightly to fill gaps for new KB entries.
"""
from __future__ import annotations

import json
from typing import Any

from services.transition_evaluator import cache as tcache

_SYSTEM = """\
You are a career transition expert and labor economist.
Given two job roles, rate the feasibility of a person transitioning from the first to the second.

Scoring guide:
  0.85–1.0  Natural progression — same domain, most skills transfer, 0–6 months upskilling
  0.60–0.84 Adjacent move — related domain, key skills transfer, 6–18 months
  0.35–0.59 Deliberate pivot — adjacent industry or skills, 18–36 months
  0.10–0.34 Major reskill — different domain, substantial retraining
  0.00–0.09 Extreme leap — almost no skill overlap, very high effort

Return ONLY valid JSON, no markdown:
{"feasibility": float, "reasoning": "one sentence (max 20 words)", "recommended": bool}
"""


def _prompt(anchor: dict, candidate: dict) -> str:
    a_skills = ", ".join(anchor.get("required_skills") or [])
    c_skills = ", ".join(candidate.get("required_skills") or [])
    gap = [
        s for s in (candidate.get("required_skills") or [])
        if s.lower() not in {x.lower() for x in (anchor.get("required_skills") or [])}
    ][:4]
    return (
        f"FROM: {anchor.get('title')} ({anchor.get('industry')})\n"
        f"  Skills: {a_skills}\n\n"
        f"TO: {candidate.get('title')} ({candidate.get('industry')})\n"
        f"  Skills: {c_skills}\n"
        f"  New skills needed: {', '.join(gap) or 'none identified'}\n\n"
        "Rate this transition."
    )


def evaluate_pair(
    anchor: dict,
    candidate: dict,
    *,
    cache_path: str = "data/transition_eval_cache.json",
    force: bool = False,
) -> dict | None:
    """Evaluate one transition pair. Returns cached result if already evaluated."""
    aid, cid = anchor.get("id", ""), candidate.get("id", "")
    if not aid or not cid or aid == cid:
        return None

    if not force:
        cached = tcache.get(aid, cid, cache_path)
        if cached:
            return cached

    try:
        from forecast import call_llm
    except ImportError:
        return None

    try:
        raw = call_llm(_SYSTEM, _prompt(anchor, candidate), max_tokens=120)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        result = json.loads(text)
        feasibility = float(result.get("feasibility", 0.5))
        reasoning = str(result.get("reasoning", ""))
        tcache.put(aid, cid, feasibility, reasoning, cache_path)
        return {"feasibility": feasibility, "reasoning": reasoning,
                "recommended": bool(result.get("recommended", feasibility >= 0.5))}
    except Exception:
        return None


def run_evaluation_pass(
    jobs: list[dict],
    *,
    cache_path: str = "data/transition_eval_cache.json",
    max_pairs: int = 40,
    min_feasibility_to_promote: float = 0.55,
    kb_path: str = "data/jobs_kb.json",
) -> dict[str, Any]:
    """Evaluate uncached transition pairs and promote good ones into KB transition_targets.

    Called from the calibration loop after query calibration completes.
    Returns a summary dict for reporting.
    """
    import json as _json
    import os

    job_by_id = {j["id"]: j for j in jobs}
    pairs = tcache.missing_pairs(jobs, path=cache_path)[:max_pairs]

    evaluated = 0
    promoted = 0
    skipped = 0

    for anchor_id, cand_id in pairs:
        anchor = job_by_id.get(anchor_id)
        cand = job_by_id.get(cand_id)
        if not anchor or not cand:
            continue
        result = evaluate_pair(anchor, cand, cache_path=cache_path)
        if result is None:
            skipped += 1
            continue
        evaluated += 1

        if result["feasibility"] >= min_feasibility_to_promote:
            _promote_to_kb(anchor_id, cand_id, result, kb_path)
            promoted += 1

    return {"evaluated": evaluated, "promoted": promoted, "skipped": skipped,
            "cache_path": cache_path}


def _promote_to_kb(
    anchor_id: str,
    candidate_id: str,
    eval_result: dict,
    kb_path: str,
) -> None:
    """Append candidate to anchor's transition_targets if not already present."""
    import json as _json, os, math

    if not os.path.exists(kb_path):
        return
    with open(kb_path, "r", encoding="utf-8") as f:
        kb = _json.load(f)

    for job in kb:
        if job.get("id") != anchor_id:
            continue
        targets = job.get("transition_targets") or []
        existing_ids = {t.get("target_id") for t in targets}
        if candidate_id in existing_ids:
            return  # already there

        feasibility = eval_result["feasibility"]
        # Rough retrain estimate: 0.85 feasibility → ~4mo, 0.55 → ~18mo
        months = max(2, round(24 * (1.0 - feasibility)))
        targets.append({
            "target_id": candidate_id,
            "retrain_months": months,
            "skill_bridge": eval_result.get("reasoning", ""),
            "confidence": round(feasibility, 3),
            "_source": "llm_eval",
        })
        job["transition_targets"] = targets
        break

    with open(kb_path, "w", encoding="utf-8") as f:
        _json.dump(kb, f, indent=2, ensure_ascii=False)
