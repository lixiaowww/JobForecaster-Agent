"""P3 — Prediction Market.

Users stake virtual points on open predictions. The market consensus probability
is the stake-weighted average of all bets — providing a crowd-wisdom signal
independent of the LLM prior.

Scoring: log2 scoring rule (proper scoring rule; incentive-compatible).
  - Correct bet: log2(bet_probability)          if outcome=TRUE
  - Correct bet: log2(1 - bet_probability)      if outcome=FALSE

All functions are pure (no hidden state) and offline-safe.
The market persists bets via the shared SQLite engine from schemas.py.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

try:
    from schemas import engine, PredictionBet, Prediction
except ImportError:
    from .schemas import engine, PredictionBet, Prediction


# ---------------------------------------------------------------------------
# Core market operations
# ---------------------------------------------------------------------------

def place_bet(
    prediction_id: str,
    contributor_id: str,
    bet_probability: float,
    stake: int = 10,
) -> PredictionBet:
    """Record or update a user's bet on a prediction.

    If the contributor already has an active bet on this prediction, it is
    replaced (upsert semantics). Stake is clamped to [1, 1000].
    """
    bet_probability = max(0.01, min(0.99, bet_probability))  # avoid log(0)
    stake = max(1, min(1000, stake))

    with Session(engine) as session:
        # Check for existing bet from this contributor on this prediction
        existing = session.exec(
            select(PredictionBet).where(
                PredictionBet.prediction_id == prediction_id,
                PredictionBet.contributor_id == contributor_id,
                PredictionBet.log_score == None,  # unsettled  # noqa: E711
            )
        ).first()

        if existing:
            existing.bet_probability = bet_probability
            existing.stake = stake
            existing.created_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        bet = PredictionBet(
            prediction_id=prediction_id,
            contributor_id=contributor_id,
            bet_probability=bet_probability,
            stake=stake,
        )
        session.add(bet)
        session.commit()
        session.refresh(bet)
        return bet


def market_probability(prediction_id: str) -> Optional[float]:
    """Stake-weighted average bet probability for a prediction.

    Returns None when no bets have been placed yet.
    """
    with Session(engine) as session:
        bets = session.exec(
            select(PredictionBet).where(
                PredictionBet.prediction_id == prediction_id,
                PredictionBet.log_score == None,  # noqa: E711
            )
        ).all()

    if not bets:
        return None

    total_stake = sum(b.stake for b in bets)
    weighted_prob = sum(b.bet_probability * b.stake for b in bets) / total_stake
    return round(weighted_prob, 4)


def bet_count(prediction_id: str) -> int:
    """Number of active (unsettled) bets on a prediction."""
    with Session(engine) as session:
        bets = session.exec(
            select(PredictionBet).where(
                PredictionBet.prediction_id == prediction_id,
                PredictionBet.log_score == None,  # noqa: E711
            )
        ).all()
    return len(bets)


def settle_market(prediction_id: str, outcome: bool) -> list[dict]:
    """Score all bets once a prediction resolves.

    Applies the log2 proper scoring rule, converts to integer payout points
    (floored at 0 — no debt), and returns a leaderboard sorted by payout.
    """
    with Session(engine) as session:
        bets = session.exec(
            select(PredictionBet).where(
                PredictionBet.prediction_id == prediction_id,
                PredictionBet.log_score == None,  # noqa: E711
            )
        ).all()

        settled = []
        for bet in bets:
            p = bet.bet_probability
            # Log2 scoring rule: range [-∞, 0], normalized to approx [-10, 0]
            if outcome:
                raw_score = math.log2(max(p, 1e-9))
            else:
                raw_score = math.log2(max(1 - p, 1e-9))
            bet.log_score = round(raw_score, 4)
            # Payout: scale by stake, breakeven (1x) at 50%, double (2x) at 100%, lose all at 25%
            raw_payout = bet.stake * (2.0 + raw_score)
            bet.payout_points = max(0, round(raw_payout))
            session.add(bet)
            settled.append({
                "contributor_id": bet.contributor_id,
                "bet_probability": bet.bet_probability,
                "stake": bet.stake,
                "log_score": bet.log_score,
                "payout_points": bet.payout_points,
            })

        session.commit()

    return sorted(settled, key=lambda x: x["payout_points"], reverse=True)


def leaderboard(top_n: int = 10) -> list[dict]:
    """Global leaderboard: sum of payout_points per contributor across all settled bets."""
    with Session(engine) as session:
        bets = session.exec(
            select(PredictionBet).where(
                PredictionBet.payout_points != None  # noqa: E711
            )
        ).all()

    scores: dict[str, int] = {}
    for bet in bets:
        scores[bet.contributor_id] = scores.get(bet.contributor_id, 0) + (bet.payout_points or 0)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {"rank": i + 1, "contributor_id": cid, "total_points": pts}
        for i, (cid, pts) in enumerate(ranked[:top_n])
    ]
