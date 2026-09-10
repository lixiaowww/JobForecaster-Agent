"""External evidence for grading the query agent's own patches.

Every gatherer here answers one question: *after* a patch landed, did the
outside world corroborate it?

The hard rule this module exists to enforce: **only events with a timestamp
strictly after the patch was applied count.** Evidence that already existed
when the agent decided to patch is what motivated the patch in the first
place — reusing it as proof is the circularity ``claims.py`` exists to break.

Signal strength is not uniform, and the callers are told which is which:

``feedback_corroboration``  — strongest. A human independently typed this job
    title into the feedback form after the patch existed. For ``kb_profile_new``
    (where the agent invented the profile) this is the only evidence that the
    role is a thing real people hold, not an LLM confabulation.
``bls_presence``            — strong but coarse and often unavailable: the KB
    carries SOC codes only for BLS-enriched rows. Absent → skipped, never faked.
``satisfied_searches`` /    — weakest, and an approximation. The search log has
``reformulations``            no session id, so "the same person searched again"
    is inferred from time adjacency in a single global stream. Treated as
    supporting evidence only, never sufficient alone for a positive verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from services.job_query_agent.search_log import load_search_log_rows

# Log sources that represent real end-user traffic. The agent never writes to
# the search log (only ``ui/tabs/radar.py`` does), but pinning the set means a
# future agent-side writer cannot silently start grading itself.
ORGANIC_SOURCES = ("radar", "hf", "ui", None, "")


@dataclass(frozen=True)
class Signal:
    """One external observation about a patch."""
    name: str
    direction: str           # "positive" | "negative" | "neutral"
    found: bool
    count: int = 0
    detail: str = ""
    strength: str = "weak"   # "strong" | "weak"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "found": self.found,
            "count": self.count,
            "strength": self.strength,
            "detail": self.detail,
            **({"extra": self.extra} if self.extra else {}),
        }


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _organic_rows_after(
    log_path: str | Path,
    since: datetime,
) -> list[tuple[datetime, dict[str, Any]]]:
    """Timestamped organic log rows strictly after *since*, oldest first."""
    out: list[tuple[datetime, dict[str, Any]]] = []
    for row in load_search_log_rows(log_path):
        if row.get("source") not in ORGANIC_SOURCES:
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts <= since:
            continue
        out.append((ts, row))
    out.sort(key=lambda pair: pair[0])
    return out


def search_behaviour(
    query: str,
    *,
    since: datetime,
    log_path: str | Path = "data/radar_search_log.jsonl",
    window_minutes: int = 10,
) -> tuple[Signal, Signal]:
    """Post-patch user search behaviour for *query*: (satisfied, reformulated).

    A search for *query* is counted as **satisfied** when no *different* query
    follows it within ``window_minutes``, and as a **reformulation** when one
    does. Query reformulation as a dissatisfaction signal is standard IR
    practice; what is approximate here is the session boundary, which is
    inferred from time adjacency because the log carries no session id. Two
    users searching seconds apart will therefore look like one reformulating
    user. That is why this signal is marked ``weak`` and can never carry a
    positive verdict by itself — see ``claims.judge_claim``.
    """
    rows = _organic_rows_after(log_path, since)
    target = _norm(query)
    window = timedelta(minutes=window_minutes)

    satisfied = 0
    reformulated = 0
    examples: list[str] = []
    for idx, (ts, row) in enumerate(rows):
        if _norm(str(row.get("query", ""))) != target:
            continue
        follower = None
        for next_ts, next_row in rows[idx + 1:]:
            if next_ts - ts > window:
                break
            if _norm(str(next_row.get("query", ""))) != target:
                follower = str(next_row.get("query", ""))
                break
        if follower is None:
            satisfied += 1
        else:
            reformulated += 1
            if len(examples) < 3:
                examples.append(follower)

    return (
        Signal(
            name="satisfied_searches",
            direction="positive",
            found=satisfied > 0,
            count=satisfied,
            strength="weak",
            detail=f"{satisfied} post-patch search(es) for {query!r} with no follow-up reformulation",
        ),
        Signal(
            name="reformulations",
            direction="negative",
            found=reformulated > 0,
            count=reformulated,
            strength="weak",
            detail=(
                f"{reformulated} post-patch search(es) for {query!r} followed by a "
                f"different query within {window_minutes}min"
                + (f" (e.g. {', '.join(examples)})" if examples else "")
            ),
        ),
    )


def feedback_corroboration(
    titles: Iterable[str],
    *,
    since: datetime,
    engine=None,
) -> Signal:
    """Did a real person name this role in the feedback form after the patch?

    Matches ``JobFeedback.job_title`` (and ``transition_target``) against the
    patched profile's title and search aliases. This is the strongest signal
    available offline: the feedback form is filled in by humans who have never
    seen the KB, so a match is genuinely independent of anything the agent
    wrote.
    """
    wanted = {_norm(t) for t in titles if _norm(t)}
    if not wanted:
        return Signal("feedback_corroboration", "positive", False, 0,
                      "no titles to match", "strong")

    try:
        from sqlmodel import Session, select

        import schemas
        from schemas import JobFeedback

        eng = engine if engine is not None else schemas.engine
        with Session(eng) as session:
            rows = list(session.exec(select(JobFeedback)).all())
    except Exception as exc:               # DB absent in some CI profiles
        return Signal("feedback_corroboration", "positive", False, 0,
                      f"feedback unavailable: {exc}", "strong")

    hits: list[str] = []
    for fb in rows:
        created = fb.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is None or created <= since:
            continue
        for candidate in (fb.job_title, fb.transition_target):
            norm = _norm(candidate or "")
            if not norm:
                continue
            if any(norm == w or w in norm or norm in w for w in wanted):
                hits.append(candidate or "")
                break

    return Signal(
        name="feedback_corroboration",
        direction="positive",
        found=bool(hits),
        count=len(hits),
        strength="strong",
        detail=(
            f"{len(hits)} post-patch human feedback row(s) naming this role"
            + (f" (e.g. {hits[0]!r})" if hits else "")
        ),
    )


def bls_presence(job: dict[str, Any] | None) -> Signal:
    """Does the patched profile correspond to a real BLS occupation?

    Only meaningful for KB rows that BLS enrichment has touched
    (``services/bls_coverage.py``). Un-enriched rows return ``found=False``
    with ``strength="skipped"`` so ``judge_claim`` can tell "no evidence" apart
    from "evidence says no" — an unavailable source must never read as a
    refutation, and must never be quietly counted as a confirmation either.
    """
    if not job:
        return Signal("bls_presence", "positive", False, 0,
                      "target profile not in KB", "skipped")
    soc = job.get("soc_code") or job.get("soc")
    employment = job.get("bls_employment") or job.get("employment")
    if not soc:
        return Signal("bls_presence", "positive", False, 0,
                      "no SOC code on profile (BLS enrichment has not run)", "skipped")
    if not employment:
        return Signal("bls_presence", "positive", False, 0,
                      f"SOC {soc} present but no employment figure", "skipped")
    return Signal(
        name="bls_presence",
        direction="positive",
        found=True,
        count=1,
        strength="strong",
        detail=f"SOC {soc} with employment {employment}",
        extra={"soc_code": soc, "employment": employment},
    )
