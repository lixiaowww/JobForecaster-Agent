"""Persistent cache for LLM-evaluated transition feasibility scores.

File: data/transition_eval_cache.json
Key:  "{anchor_id}→{candidate_id}"
Value: {"feasibility": float, "reasoning": str, "evaluated_at": ISO-date}
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

_DEFAULT_PATH = "data/transition_eval_cache.json"


def _load(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cache: dict[str, dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _key(anchor_id: str, candidate_id: str) -> str:
    return f"{anchor_id}→{candidate_id}"


def get(anchor_id: str, candidate_id: str, path: str = _DEFAULT_PATH) -> dict | None:
    return _load(path).get(_key(anchor_id, candidate_id))


def put(
    anchor_id: str,
    candidate_id: str,
    feasibility: float,
    reasoning: str,
    path: str = _DEFAULT_PATH,
) -> None:
    cache = _load(path)
    cache[_key(anchor_id, candidate_id)] = {
        "feasibility": round(float(feasibility), 3),
        "reasoning": reasoning,
        "evaluated_at": date.today().isoformat(),
    }
    _save(cache, path)


def get_all(path: str = _DEFAULT_PATH) -> dict[str, dict]:
    return _load(path)


def missing_pairs(
    jobs: list[dict],
    top_k: int = 5,
    path: str = _DEFAULT_PATH,
) -> list[tuple[str, str]]:
    """Return (anchor_id, candidate_id) pairs not yet in cache.

    Only considers pairs where anchor has empty transition_targets (needs evaluation).
    """
    cache = _load(path)
    ids = [j["id"] for j in jobs]
    pairs: list[tuple[str, str]] = []
    for job in jobs:
        aid = job.get("id", "")
        if job.get("transition_targets"):
            continue  # already has curated targets
        for cid in ids:
            if cid != aid and _key(aid, cid) not in cache:
                pairs.append((aid, cid))
        if len(pairs) >= top_k * 10:
            break
    return pairs
