"""Pydantic models for REST /v1 request bodies."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from services.mcp_handlers import INDUSTRIES


class ScenarioOverrides(BaseModel):
    """Subset of evolution.CURRENT_AI_SCENARIO — all fields optional."""

    augmentation_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    demand_elasticity: Optional[float] = Field(None, ge=0.0, le=1.0)
    oring_leverage: Optional[float] = Field(None, ge=0.0, le=1.0)
    skill_distance: Optional[float] = Field(None, ge=0.0, le=1.0)
    diffusion_years: Optional[float] = Field(None, gt=0.0)
    absorbing_sector: Optional[float] = Field(None, ge=0.0, le=1.0)
    productivity_capture: Optional[float] = Field(None, ge=0.0, le=1.0)
    task_frontier_open: Optional[float] = Field(None, ge=0.0, le=1.0)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class OodRequest(BaseModel):
    scenario: Optional[ScenarioOverrides] = None
    n_bootstrap: Optional[int] = Field(None, ge=1, le=200)


class JobSearchRequest(BaseModel):
    query: str = ""
    industry: str = "All"
    limit: int = Field(10, ge=1, le=50)
    scenario: Optional[ScenarioOverrides] = None

    def validated_industry(self) -> str:
        if self.industry not in INDUSTRIES:
            raise ValueError(f"industry must be one of: {', '.join(INDUSTRIES)}")
        return self.industry


class ContributionSubmitRequest(BaseModel):
    contributor_id: str = Field(..., min_length=1, max_length=128)
    probability: float = Field(..., ge=0.0, le=1.0)
    argument: str = Field(..., min_length=20)
    evidence_urls: list[str] = Field(..., min_length=1)

