"""Brier-scored claims over the query agent's own self-mutations.

Why this exists
---------------
The forecaster loop's scarcest asset is not its LLM — it is the discipline of
making a claim that is *dated*, *falsifiable*, and later *graded against
reality* (see ``schemas.Prediction`` / ``registry.Registry``). The query agent
had no such anchor. Its gate, ``apply.can_auto_apply``, scores a patch by
similarity against the same KB the patch is about to edit, so for a patch that
adds the matching alias — or invents the matching profile outright — passing
the gate is very nearly tautological. Run long enough, that loop grows more
self-consistent without growing more correct.

This module connects the two. Every auto-applied patch is restated as a
:class:`schemas.PatchClaim`: a sentence that could turn out false, a
``resolution_date``, an explicit ``confidence`` the agent must stake, and a
``resolution_criteria`` naming external evidence only. Later,
``resolve_due_claims`` judges it against things the KB cannot influence
(``evidence.py``), scores it with the same ``brier_score`` the AI-economy
forecasts use, and ``gate_verdict`` feeds the realised record back into the
gate: a patch type that keeps being wrong loses the right to auto-apply.

Three properties worth preserving if this is ever changed:

1. **No evidence resolves ambiguous, never true.** Otherwise the agent earns a
   spotless record by emitting unfalsifiable patches.
2. **Ambiguous claims still count as outstanding.** Otherwise unfalsifiable
   patches are not merely unpunished, they are free. The outstanding cap is
   what makes silence expensive.
3. **The gate fails open.** A bug in this module must never wedge the
   calibration cycle; it may only ever make the agent *more* conservative.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlmodel import Session, SQLModel, select

import schemas
from schemas import PatchClaim, Status, make_engine
from services import provenance
from services.job_query_agent import evidence as ev

CLAIMABLE_TYPES = ("alias_patch", "title_alias", "kb_profile_new")

_DEFAULT_STAKE_BASE = {
    "alias_patch": 0.75,     # narrowest edit, usually anchored by an expected_id
    "title_alias": 0.70,     # config-level, same anchor but wider blast radius
    "kb_profile_new": 0.55,  # LLM invents a whole profile — barely better than a guess
}
_OPEN = (Status.open, Status.due)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def claims_cfg(agent_cfg: dict[str, Any]) -> dict[str, Any]:
    return (agent_cfg or {}).get("claims", {}) or {}


def is_enabled(agent_cfg: dict[str, Any]) -> bool:
    """Off unless explicitly enabled, so existing callers are unaffected."""
    return bool(claims_cfg(agent_cfg).get("enabled", False))


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
class ClaimStore:
    """Persistence for :class:`PatchClaim`, mirroring ``registry.Registry``."""

    def __init__(self, path: str | Path | None = None, *, engine=None):
        if engine is not None:
            self._engine = engine
        elif path is not None:
            self._engine = make_engine(path)
        else:
            self._engine = schemas.engine
        SQLModel.metadata.create_all(self._engine)

    @property
    def engine(self):
        return self._engine

    def add(self, claim: PatchClaim) -> PatchClaim | None:
        """Insert; returns None if a claim with this patch_id already exists."""
        with Session(self._engine) as session:
            if session.get(PatchClaim, claim.id) is not None:
                return None
            session.add(claim)
            session.commit()
            session.refresh(claim)
            return claim

    def update(self, claim: PatchClaim) -> None:
        with Session(self._engine) as session:
            row = session.get(PatchClaim, claim.id)
            if row is None:
                return
            for k, v in claim.model_dump().items():
                setattr(row, k, v)
            session.add(row)
            session.commit()

    def load(self, patch_type: str | None = None) -> list[PatchClaim]:
        with Session(self._engine) as session:
            stmt = select(PatchClaim)
            if patch_type:
                stmt = stmt.where(PatchClaim.patch_type == patch_type)
            return list(session.exec(stmt).all())

    def get(self, claim_id: str) -> PatchClaim | None:
        with Session(self._engine) as session:
            return session.get(PatchClaim, claim_id)

    def due(self, today: date | None = None) -> list[PatchClaim]:
        today = today or date.today()
        with Session(self._engine) as session:
            stmt = select(PatchClaim).where(
                PatchClaim.status.in_(_OPEN),
                PatchClaim.resolution_date <= today,
            )
            return list(session.exec(stmt).all())

    def outstanding(self, patch_type: str | None = None) -> list[PatchClaim]:
        """Open/due claims, plus ambiguous ones — everything not yet graded.

        Ambiguous belongs here deliberately: a claim nobody could settle has
        not earned the agent any credit, and letting it drop out of the count
        would make unfalsifiable patches free.
        """
        return [
            c for c in self.load(patch_type)
            if c.status in _OPEN or c.status == Status.ambiguous
        ]

    def resolved(self, patch_type: str | None = None) -> list[PatchClaim]:
        """Claims that actually carry a Brier score."""
        return [c for c in self.load(patch_type) if c.brier is not None]


def store_for(cfg: dict[str, Any], *, engine=None) -> ClaimStore:
    if engine is not None:
        return ClaimStore(engine=engine)
    return ClaimStore(cfg.get("database_path"))


# ---------------------------------------------------------------------------
# staking
# ---------------------------------------------------------------------------
def stake_confidence(
    patch_type: str,
    *,
    sim_after: float,
    min_sim: float,
    expected_id: str | None = None,
    occurrences: int | None = None,
    min_occurrences: int = 3,
    agent_cfg: dict[str, Any] | None = None,
) -> float:
    """How sure the agent claims to be that this patch is externally correct.

    The weights below are a starting prior, not a result — which is the point.
    A stake that is never graded is decoration; these numbers exist so Brier
    can eventually say they were too high. Expect to tune them from the
    realised calibration curve, not from taste.
    """
    scfg = (claims_cfg(agent_cfg or {})).get("stake", {}) or {}
    base_map = {**_DEFAULT_STAKE_BASE, **(scfg.get("base") or {})}
    conf = float(base_map.get(patch_type, 0.5))

    # A human-labelled expected_id is the one non-circular anchor available at
    # apply time, so it is the only large bonus here.
    if expected_id:
        conf += float(scfg.get("expected_id_bonus", 0.10))

    # Headroom above the gate threshold, not raw similarity: clearing the bar
    # by a hair should not read as confidence.
    span = max(1e-6, 1.0 - min_sim)
    headroom = max(0.0, min(1.0, (float(sim_after) - min_sim) / span))
    conf += headroom * float(scfg.get("sim_weight", 0.15))

    # Repeat organic demand for the query — weak, hence a small bonus.
    if occurrences is not None and occurrences >= 2 * max(1, min_occurrences):
        conf += float(scfg.get("occurrence_bonus", 0.05))

    return max(0.05, min(0.95, round(conf, 4)))


def _statement_for(patch_type: str, query: str, target_id: str, title: str) -> str:
    role = f"{title!r} ({target_id})" if title else target_id
    if patch_type == "kb_profile_new":
        return (
            f"The KB profile {role}, generated by this agent for the unmatched "
            f"query {query!r}, describes a real occupation that people actually "
            f"hold — not an artefact of the generating model."
        )
    if patch_type == "title_alias":
        return (
            f"The config title-alias mapping {query!r} → {role} reflects how "
            f"real users use that term, and serves them the role they meant."
        )
    return (
        f"The search alias added so that {query!r} resolves to {role} is "
        f"externally correct: real users searching {query!r} mean that occupation."
    )


def _criteria_for(min_satisfied: int) -> str:
    return (
        "TRUE if, strictly after this patch was applied, (a) a human feedback "
        "row names this role, or (b) BLS occupation data covers it, or (c) at "
        f"least {min_satisfied} organic searches for the query show no "
        "reformulation. FALSE if the regression monitor rolls the patch back, "
        "or post-patch reformulations outnumber satisfied searches. AMBIGUOUS "
        "otherwise — absence of evidence never resolves TRUE."
    )


def build_claim(
    action: dict[str, Any],
    *,
    agent_cfg: dict[str, Any],
    query: str,
    expected_id: str | None = None,
    occurrences: int | None = None,
    jobs_by_id: dict[str, dict] | None = None,
    today: date | None = None,
    min_sim: float = 0.55,
) -> PatchClaim | None:
    """Turn a successful auto-apply action into a stakeable claim, or None."""
    if not action.get("auto_applied"):
        return None
    patch_id = action.get("patch_id")
    patch_type = action.get("type")
    if not patch_id or patch_type not in CLAIMABLE_TYPES:
        return None

    ccfg = claims_cfg(agent_cfg)
    horizon = int(ccfg.get("horizon_days", 30))
    min_satisfied = int(ccfg.get("min_satisfied_searches", 3))
    target_id = str(
        action.get("best_id_after") or action.get("profile_id")
        or action.get("target_id") or "",
    )
    title = ((jobs_by_id or {}).get(target_id) or {}).get("title", "")

    return PatchClaim(
        id=str(patch_id),
        patch_type=patch_type,
        query=query,
        target_id=target_id,
        source=str(action.get("_source") or action.get("source") or ""),
        statement=_statement_for(patch_type, query, target_id, title),
        resolution_criteria=_criteria_for(min_satisfied),
        confidence=stake_confidence(
            patch_type,
            sim_after=float(action.get("sim_after") or 0.0),
            min_sim=min_sim,
            expected_id=expected_id,
            occurrences=occurrences,
            agent_cfg=agent_cfg,
        ),
        created_at=datetime.now(timezone.utc),
        resolution_date=(today or date.today()) + timedelta(days=horizon),
    )


def open_claims_for_actions(
    actions: Iterable[dict[str, Any]],
    *,
    cfg: dict[str, Any],
    agent_cfg: dict[str, Any],
    jobs_by_id: dict[str, dict] | None = None,
    engine=None,
    today: date | None = None,
) -> list[PatchClaim]:
    """Stake a claim on every auto-applied patch in *actions*. Never raises."""
    if not is_enabled(agent_cfg):
        return []
    try:
        store = store_for(cfg, engine=engine)
        min_sim = float(agent_cfg.get("auto_apply", {}).get("min_sim_after", 0.55))
        out: list[PatchClaim] = []
        for action in actions:
            claim = build_claim(
                action,
                agent_cfg=agent_cfg,
                query=str(action.get("query") or action.get("_query") or ""),
                expected_id=action.get("_expected_id"),
                occurrences=action.get("_occurrences"),
                jobs_by_id=jobs_by_id,
                today=today,
                min_sim=min_sim,
            )
            if claim is None:
                continue
            stored = store.add(claim)
            if stored is not None:
                out.append(stored)
        return out
    except Exception:
        return []   # staking is bookkeeping; it must never break the cycle


# ---------------------------------------------------------------------------
# judging
# ---------------------------------------------------------------------------
def judge_claim(
    claim: PatchClaim,
    *,
    agent_cfg: dict[str, Any],
    jobs_by_id: dict[str, dict] | None = None,
    log_path: str | Path = "data/radar_search_log.jsonl",
    ledger_path: str | Path = provenance.DEFAULT_LEDGER_PATH,
    engine=None,
) -> tuple[bool | None, str, dict[str, Any]]:
    """Settle one claim against external evidence. Returns (outcome, why, evidence)."""
    ccfg = claims_cfg(agent_cfg)
    min_satisfied = int(ccfg.get("min_satisfied_searches", 3))
    window = int(ccfg.get("reformulation_window_minutes", 10))

    since = claim.created_at
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    # A patch the regression monitor already pulled is settled, and settled
    # against the agent: it staked confidence on something that did not hold.
    if provenance.is_reverted(claim.id, path=ledger_path):
        return False, "patch was rolled back by the regression monitor", {
            "signals": [], "verdict_basis": "rollback",
        }

    job = (jobs_by_id or {}).get(claim.target_id)
    aliases = list((job or {}).get("search_aliases") or [])
    titles = [t for t in [(job or {}).get("title", ""), *aliases] if t]

    satisfied, reformulated = ev.search_behaviour(
        claim.query, since=since, log_path=log_path, window_minutes=window,
    )
    feedback = ev.feedback_corroboration(titles, since=since, engine=engine)
    bls = ev.bls_presence(job)

    # BLS presence proves the *occupation* is real. It says nothing about
    # whether this *query* means that occupation — so it can only settle a
    # claim whose subject is the occupation itself. For kb_profile_new, where
    # the agent invented the profile, "does this role exist at all" is exactly
    # the claim. For alias_patch / title_alias the claim is about the mapping,
    # and letting BLS carry it would make any alias pointing at a BLS-stamped
    # row trivially TRUE — a fresh way to earn a clean Brier for free.
    verdict_signals = [satisfied, reformulated, feedback]
    if claim.patch_type == "kb_profile_new":
        verdict_signals.append(bls)
    else:
        bls = ev.Signal(
            name=bls.name, direction="neutral", found=bls.found, count=bls.count,
            strength="context",
            detail=f"{bls.detail} (context only: proves the role exists, "
                   f"not that {claim.query!r} means it)",
            extra=bls.extra,
        )

    signals = [satisfied, reformulated, feedback, bls]
    payload = {"signals": [s.as_dict() for s in signals]}

    # Negative first: dissatisfaction outweighing satisfaction refutes the claim.
    if reformulated.count > 0 and reformulated.count >= satisfied.count:
        payload["verdict_basis"] = "reformulation"
        return False, (
            f"{reformulated.count} post-patch reformulation(s) vs "
            f"{satisfied.count} satisfied search(es) — users did not get what they meant"
        ), payload

    strong = [s for s in verdict_signals
              if s.direction == "positive" and s.found and s.strength == "strong"]
    if strong:
        payload["verdict_basis"] = "strong"
        return True, "; ".join(s.detail for s in strong), payload

    if satisfied.count >= min_satisfied and reformulated.count == 0:
        payload["verdict_basis"] = "weak"
        return True, (
            f"{satisfied.count} post-patch organic search(es) with zero "
            f"reformulations (weak behavioural evidence, no strong corroboration)"
        ), payload

    payload["verdict_basis"] = "insufficient"
    return None, (
        "no external evidence either way yet — "
        f"{satisfied.count} satisfied search(es), {reformulated.count} reformulation(s), "
        f"no human feedback, {bls.detail}"
    ), payload


def resolve_due_claims(
    cfg: dict[str, Any],
    *,
    agent_cfg: dict[str, Any] | None = None,
    jobs_by_id: dict[str, dict] | None = None,
    log_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    engine=None,
    today: date | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Judge every due claim. The external half of the query agent's loop."""
    agent_cfg = agent_cfg if agent_cfg is not None else cfg.get("job_query_agent", {})
    if not is_enabled(agent_cfg):
        return {"enabled": False, "judged": 0}

    store = store_for(cfg, engine=engine)
    log_path = log_path or agent_cfg.get("discover", {}).get(
        "search_log_path", "data/radar_search_log.jsonl")
    ledger_path = ledger_path or agent_cfg.get(
        "provenance_path", provenance.DEFAULT_LEDGER_PATH)

    results: list[dict[str, Any]] = []
    for claim in store.due(today):
        outcome, why, payload = judge_claim(
            claim,
            agent_cfg=agent_cfg,
            jobs_by_id=jobs_by_id,
            log_path=log_path,
            ledger_path=ledger_path,
            engine=store.engine,
        )
        if not dry_run:
            claim.resolve(outcome, why, payload)
            store.update(claim)
        results.append({
            "claim_id": claim.id,
            "patch_type": claim.patch_type,
            "query": claim.query,
            "confidence": claim.confidence,
            "outcome": outcome,
            "brier": schemas.brier_score(claim.confidence, outcome),
            "basis": payload.get("verdict_basis"),
            "why": why,
        })

    return {
        "enabled": True,
        "judged": len(results),
        "true": sum(1 for r in results if r["outcome"] is True),
        "false": sum(1 for r in results if r["outcome"] is False),
        "ambiguous": sum(1 for r in results if r["outcome"] is None),
        "dry_run": dry_run,
        "results": results,
    }


# ---------------------------------------------------------------------------
# scoring + feedback into the gate
# ---------------------------------------------------------------------------
def claim_scoreboard(
    cfg: dict[str, Any],
    *,
    patch_type: str | None = None,
    engine=None,
) -> dict[str, Any]:
    """Calibration for the agent's self-mutations, via the shared scoreboard math."""
    from services.track_record import scoreboard_subset

    store = store_for(cfg, engine=engine)
    claims = store.load(patch_type)
    sb = scoreboard_subset(claims)          # same buckets the forecaster uses
    sb["patch_type"] = patch_type or "all"
    sb["outstanding"] = len(store.outstanding(patch_type))
    sb["by_type"] = {}
    if patch_type is None:
        for t in CLAIMABLE_TYPES:
            subset = [c for c in claims if c.patch_type == t]
            scored = [c for c in subset if c.brier is not None]
            sb["by_type"][t] = {
                "total": len(subset),
                "resolved": len(scored),
                "mean_brier": (
                    round(sum(c.brier for c in scored) / len(scored), 4)
                    if scored else None
                ),
                "outstanding": len(store.outstanding(t)),
            }
    return sb


def gate_verdict(
    patch_type: str,
    *,
    cfg: dict[str, Any],
    agent_cfg: dict[str, Any],
    engine=None,
) -> tuple[bool, str, float | None]:
    """Should *patch_type* still be allowed to auto-apply? (allowed, why, min_sim_override)

    This is the return path that makes the whole module load-bearing rather
    than an observability dashboard. Two ways a patch type loses trust:

    * **Miscalibration** — enough claims have resolved and the mean Brier is
      worse than ``max_mean_brier``. The agent has been confidently wrong.
    * **Silence** — too many claims are outstanding (open, due, or ambiguous).
      The agent keeps writing cheques the world never cashes, which is exactly
      the failure mode of a self-referential loop, and is *not* detectable from
      Brier alone because unresolved claims have no Brier.

    Fails open by construction: any error returns "allowed", because a bug here
    must never be able to stop the calibration cycle — only to slow it down.
    """
    ccfg = claims_cfg(agent_cfg)
    gcfg = ccfg.get("gate", {}) or {}
    if not is_enabled(agent_cfg) or not gcfg.get("enabled", True):
        return True, "claims gate disabled", None

    try:
        store = store_for(cfg, engine=engine)
        outstanding = len(store.outstanding(patch_type))
        max_outstanding = int(gcfg.get("max_outstanding", 25))
        if outstanding > max_outstanding:
            return False, (
                f"{outstanding} unresolved {patch_type} claim(s) outstanding "
                f"> {max_outstanding} — previous self-mutations are not being "
                f"corroborated; human review required"
            ), None

        scored = store.resolved(patch_type)
        min_resolved = int(gcfg.get("min_resolved", 5))
        if len(scored) < min_resolved:
            return True, (
                f"only {len(scored)} resolved {patch_type} claim(s) "
                f"(< {min_resolved}) — no track record yet"
            ), None

        mean_brier = sum(c.brier for c in scored) / len(scored)
        max_brier = float(gcfg.get("max_mean_brier", 0.35))
        warn_brier = float(gcfg.get("warn_mean_brier", 0.25))
        if mean_brier > max_brier:
            return False, (
                f"{patch_type} mean Brier {mean_brier:.3f} > {max_brier} over "
                f"{len(scored)} resolved claim(s) — auto-apply suspended"
            ), None
        if mean_brier > warn_brier:
            base = float(agent_cfg.get("auto_apply", {}).get("min_sim_after", 0.55))
            penalty = float(gcfg.get("min_sim_penalty", 0.05))
            return True, (
                f"{patch_type} mean Brier {mean_brier:.3f} > warn {warn_brier} — "
                f"raising min_sim_after by {penalty}"
            ), min(0.99, base + penalty)
        return True, (
            f"{patch_type} mean Brier {mean_brier:.3f} over "
            f"{len(scored)} resolved claim(s)"
        ), None
    except Exception as exc:
        return True, f"claims gate unavailable ({exc}) — failing open", None
