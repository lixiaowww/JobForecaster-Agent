"""Core data models for the forecasting loop."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, date, timezone
from enum import Enum
from typing import Optional, List

from pydantic import field_validator
from sqlmodel import SQLModel, Field, JSON


class Status(str, Enum):
    open = "open"               # not yet at resolution date
    due = "due"                 # past resolution date, awaiting judgement
    resolved_true = "resolved_true"
    resolved_false = "resolved_false"
    ambiguous = "ambiguous"     # could not be judged cleanly


class Signal(SQLModel):
    """A single piece of evidence ingested from the world."""
    source: str
    title: str
    url: str = ""
    summary: str = ""
    published: Optional[str] = None
    kind: str = "news"          # news | paper | indicator

    def as_context(self) -> str:
        head = f"[{self.kind}] {self.title}"
        body = f" — {self.summary}" if self.summary else ""
        src = f" ({self.url})" if self.url else ""
        return f"{head}{body}{src}"


class Prediction(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    """A falsifiable, dated, confidence-scored claim about the future."""
    id: str = Field(default="", primary_key=True)
    statement: str                          # the falsifiable claim
    rationale: str                          # the economic reasoning behind it
    category: str = "general"               # labor | compute | macro | capital | policy ...
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: str                            # human label, e.g. "2026-Q4"
    resolution_date: date                   # when it becomes judgeable
    resolution_criteria: str                # how to decide true/false
    sources: List[str] = Field(default_factory=list, sa_type=JSON)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    status: Status = Field(default=Status.open)
    outcome: Optional[bool] = None          # True / False once resolved
    judged_rationale: str = ""              # why it resolved that way
    resolved_at: Optional[datetime] = None
    brier: Optional[float] = None           # (confidence - outcome)^2

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @classmethod
    def model_validate(cls, obj, **kwargs) -> Prediction:
        if isinstance(obj, dict):
            if "resolution_date" in obj and isinstance(obj["resolution_date"], str):
                obj["resolution_date"] = date.fromisoformat(obj["resolution_date"])
            if "created_at" in obj and isinstance(obj["created_at"], str):
                obj["created_at"] = datetime.fromisoformat(obj["created_at"].replace("Z", "+00:00"))
            if "resolved_at" in obj and isinstance(obj["resolved_at"], str):
                obj["resolved_at"] = datetime.fromisoformat(obj["resolved_at"].replace("Z", "+00:00"))
        return super().model_validate(obj, **kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes, **kwargs) -> Prediction:
        import json
        data = json.loads(json_data)
        return cls.model_validate(data, **kwargs)

    def fingerprint(self) -> str:
        key = f"{self.statement.lower().strip()}|{self.horizon.strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def assign_id(self) -> "Prediction":
        if not self.id:
            self.id = self.fingerprint()
        return self

    def resolve(self, outcome: Optional[bool], rationale: str) -> "Prediction":
        self.resolved_at = datetime.now(timezone.utc)
        self.judged_rationale = rationale
        if outcome is None:
            self.status = Status.ambiguous
            self.outcome = None
            self.brier = None
        else:
            self.outcome = outcome
            self.status = Status.resolved_true if outcome else Status.resolved_false
            self.brier = (self.confidence - (1.0 if outcome else 0.0)) ** 2
        return self


class Contribution(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    """One person's forecast + argument on an existing open prediction."""
    id: str = Field(primary_key=True)
    target_id: str = Field(foreign_key="prediction.id")
    contributor_id: str
    probability: float        # contributor's P(statement resolves true), 0..1
    argument: str
    evidence_urls: List[str] = Field(default_factory=list, sa_type=JSON)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    outcome: Optional[bool] = Field(default=None)
    brier: Optional[float] = Field(default=None)

    @classmethod
    def model_validate(cls, obj, **kwargs) -> Contribution:
        if isinstance(obj, dict):
            if "created_at" in obj and isinstance(obj["created_at"], str):
                obj["created_at"] = datetime.fromisoformat(obj["created_at"].replace("Z", "+00:00"))
        return super().model_validate(obj, **kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes, **kwargs) -> Contribution:
        import json
        data = json.loads(json_data)
        return cls.model_validate(data, **kwargs)


class CrowdSnapshot(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    """Latest crowd-gate aggregate for an open prediction."""
    target_id: str = Field(primary_key=True, foreign_key="prediction.id")
    prior_probability: float
    aggregate_probability: float
    selected_contribution_ids: List[str] = Field(default_factory=list, sa_type=JSON)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobFeedback(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    """Crowd-sourced career transition feedback from users."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_title: str
    industry: str
    company: Optional[str] = None
    status: str                 # "employed", "unemployed", "transitioning"
    confidence: float           # 0.0 to 1.0 (subjective job security/confidence)
    experience_level: str = "mid"   # junior | mid | senior (HR-13)
    transition_target: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # P1.2 follow-up tracking
    email: Optional[str] = None              # opt-in for 6-month follow-up
    follow_up_due_at: Optional[datetime] = None   # created_at + 180 days
    follow_up_received: bool = Field(default=False)
    outcome_verified: Optional[bool] = None  # True=transition succeeded, False=didn't


class PredictionBet(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    """P3 — Prediction market: users stake virtual points on open predictions.

    market_probability = stake-weighted average of bet_probability across all bets.
    Log-score payouts computed at settle_market() time.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    prediction_id: str = Field(foreign_key="prediction.id")
    contributor_id: str                 # anonymous session ID or user handle
    bet_probability: float = Field(ge=0.0, le=1.0)   # user's P(true)
    stake: int = Field(default=10, ge=1)              # virtual points (1–1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Filled on settlement
    log_score: Optional[float] = None   # log2(bet_prob) if TRUE, log2(1-bet_prob) if FALSE
    payout_points: Optional[int] = None


import os
from pathlib import Path as _Path
from sqlmodel import create_engine
from sqlalchemy.engine import Engine

_DEFAULT_DB_PATH = "data/forecaster.db"


def make_engine(path: str | _Path) -> Engine:
    """Create (and initialise) a SQLite engine for *path*.

    Creates the parent directory if needed.  All SQLModel tables are created on
    first call (idempotent: ``extend_existing=True`` on every model).

    Use this instead of the module-level ``engine`` whenever you need an
    isolated database — e.g. in tests or when running against a non-default
    database path from config.
    """
    path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{path}", echo=False)
    SQLModel.metadata.create_all(eng)
    _migrate_sqlite_columns(eng)
    return eng


def _migrate_sqlite_columns(eng: Engine) -> None:
    """Lightweight SQLite column adds (no Alembic). Idempotent."""
    from sqlalchemy import inspect, text

    insp = inspect(eng)
    if not insp.has_table("jobfeedback"):
        return
    cols = {c["name"] for c in insp.get_columns("jobfeedback")}
    if "experience_level" not in cols:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE jobfeedback "
                    "ADD COLUMN experience_level VARCHAR NOT NULL DEFAULT 'mid'"
                )
            )


# ---------------------------------------------------------------------------
# Default (production) engine — lazily initialised so that importing schemas
# does NOT create the data/ directory in test environments that pass an
# explicit path to make_engine().
# ---------------------------------------------------------------------------
os.makedirs("data", exist_ok=True)
DATABASE_URL = f"sqlite:///{_DEFAULT_DB_PATH}"
engine = make_engine(_DEFAULT_DB_PATH)  # backward-compat module-level export
