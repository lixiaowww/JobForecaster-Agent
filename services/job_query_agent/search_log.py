"""Radar / HF search log — record queries and aggregate for weighted discovery."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def record_search_log(
    query: str,
    *,
    path: str | Path = "data/radar_search_log.jsonl",
    source: str = "radar",
    tier: str | None = None,
    best_id: str | None = None,
    sim: float | None = None,
    industry: str | None = None,
) -> None:
    """Append one search event (best-effort; never raises)."""
    q = (query or "").strip()
    if not q:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "query": q,
        "source": source,
        "tier": tier,
        "best_id": best_id,
        "sim": sim,
        "industry": industry,
    }
    try:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_search_log_rows(path: str | Path) -> list[dict[str, Any]]:
    """Load all JSONL rows; skip malformed lines."""
    p = Path(path)
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("query"):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def aggregate_search_queries(
    path: str | Path,
    *,
    min_occurrences: int = 1,
) -> dict[str, int]:
    """Return normalized query → count (case-insensitive key, canonical first-seen casing)."""
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for row in load_search_log_rows(path):
        q = str(row["query"]).strip()
        if not q:
            continue
        key = q.lower()
        counts[key] += 1
        display.setdefault(key, q)
    return {
        display[k]: v
        for k, v in counts.items()
        if v >= min_occurrences
    }


def merge_search_logs(
    src: str | Path,
    dest: str | Path = "data/radar_search_log.jsonl",
) -> int:
    """Merge *src* JSONL into *dest* (dedupe by ts+query). Returns rows appended."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_search_log_rows(dest_path)
    seen = {(r.get("ts"), str(r.get("query", "")).lower()) for r in existing}
    added = 0
    with dest_path.open("a", encoding="utf-8") as fh:
        for row in load_search_log_rows(src):
            key = (row.get("ts"), str(row.get("query", "")).lower())
            if key in seen:
                continue
            seen.add(key)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
    return added
