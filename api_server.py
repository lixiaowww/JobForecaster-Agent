#!/usr/bin/env python3
"""Read-only REST API for forecaster-agent (Phase 3b).

Shares handlers with MCP (`services/mcp_handlers.py`). OpenAPI at /docs.

  uvicorn api_server:app --host 127.0.0.1 --port 8765
  # or: python api_server.py

Auth: set FORECASTER_API_KEY to require X-API-Key header (optional in local dev).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path = [p for p in sys.path if p != "/home/sean"]

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.api_auth import RateLimiter, configured_api_key, verify_api_key
from services.api_schemas import ContributionSubmitRequest, JobSearchRequest, OodRequest
from services.config_loader import load_config
from services.crowd_service import (
    get_blind_contribution_target,
    get_crowd_result,
    submit_contribution,
)
from services.mcp_handlers import (
    INDUSTRIES,
    handle_get_calibration_scoreboard,
    handle_get_ood_assessment,
    handle_list_open_predictions,
    handle_search_jobs,
)

_cfg = load_config()
_api_cfg = _cfg.get("api", {})
_limiter = RateLimiter(int(_api_cfg.get("rate_limit_per_minute", 60)))

app = FastAPI(
    title="forecaster-agent API",
    version="0.6.0",
    description=(
        "Read-only calibration, OOD, job radar, and open predictions; plus crowd "
        "contributions (anti-anchoring submit flow). Speculative outputs — not "
        "financial or career advice. BUSL-1.1; commercial use requires a license."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_api_cfg.get("cors_origins", ["http://localhost:8501", "http://127.0.0.1:8501"]),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def _rate_limit(request: Request) -> None:
    _limiter.check(request)


AuthDep = Annotated[None, Depends(verify_api_key)]
LimitDep = Annotated[None, Depends(_rate_limit)]


@app.get("/health")
def health(_auth: AuthDep, _limit: LimitDep) -> dict[str, str]:
    return {"status": "ok", "auth": "required" if configured_api_key() else "open"}


@app.get("/v1/scoreboard")
def get_scoreboard(_auth: AuthDep, _limit: LimitDep) -> dict[str, Any]:
    return handle_get_calibration_scoreboard()


@app.get("/v1/ood")
def get_ood(
    _auth: AuthDep,
    _limit: LimitDep,
    scenario_json: Optional[str] = Query(
        None,
        description="JSON object merging onto evolution.CURRENT_AI_SCENARIO",
    ),
    n_bootstrap: Optional[int] = Query(None, ge=1, le=200),
) -> dict[str, Any]:
    return handle_get_ood_assessment(scenario_json=scenario_json, n_bootstrap=n_bootstrap)


@app.post("/v1/ood")
def post_ood(body: OodRequest, _auth: AuthDep, _limit: LimitDep) -> dict[str, Any]:
    scenario = body.scenario.to_dict() if body.scenario else None
    return handle_get_ood_assessment(
        n_bootstrap=body.n_bootstrap,
        scenario=scenario,
    )


@app.get("/v1/jobs/search")
def search_jobs_get(
    _auth: AuthDep,
    _limit: LimitDep,
    query: str = "",
    industry: str = Query("All", description=f"One of: {', '.join(INDUSTRIES)}"),
    limit: int = Query(10, ge=1, le=50),
    scenario_json: Optional[str] = None,
) -> dict[str, Any]:
    try:
        return handle_search_jobs(
            query=query, industry=industry, limit=limit, scenario_json=scenario_json
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/jobs/search")
def search_jobs_post(body: JobSearchRequest, _auth: AuthDep, _limit: LimitDep) -> dict[str, Any]:
    try:
        body.validated_industry()
        scenario = body.scenario.to_dict() if body.scenario else None
        return handle_search_jobs(
            query=body.query,
            industry=body.industry,
            limit=body.limit,
            scenario=scenario,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/predictions/open")
def list_predictions(
    _auth: AuthDep,
    _limit: LimitDep,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return handle_list_open_predictions(limit=limit)


@app.get("/v1/predictions/{target_id}/contribute")
def get_contribution_target(
    target_id: str,
    _auth: AuthDep,
    _limit: LimitDep,
) -> dict[str, Any]:
    try:
        return get_blind_contribution_target(target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/v1/predictions/{target_id}/contributions")
def post_contribution(
    target_id: str,
    body: ContributionSubmitRequest,
    _auth: AuthDep,
    _limit: LimitDep,
) -> dict[str, Any]:
    try:
        return submit_contribution(
            target_id=target_id,
            contributor_id=body.contributor_id,
            probability=body.probability,
            argument=body.argument,
            evidence_urls=body.evidence_urls,
            cfg=_cfg,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/predictions/{target_id}/crowd")
def get_prediction_crowd(
    target_id: str,
    _auth: AuthDep,
    _limit: LimitDep,
    contributor_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    try:
        return get_crowd_result(target_id, contributor_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def main() -> None:
    import uvicorn

    host = _api_cfg.get("host", "127.0.0.1")
    port = int(_api_cfg.get("port", 8765))
    uvicorn.run("api_server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
