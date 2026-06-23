#!/usr/bin/env python3
"""Read-only MCP server for forecaster-agent (Phase 3).

Exposes calibration scoreboard, OOD assessment, job search, and open predictions
via the Harness `services/` read model. No write tools; no LLM calls at runtime.

Run (stdio — for Cursor / Claude Desktop):
  python mcp_server.py

Cursor config example: see docs/MCP.md
"""
from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap project root before any local imports
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path = [p for p in sys.path if p != "/home/sean"]

from mcp.server.fastmcp import FastMCP

from services.mcp_handlers import (
    INDUSTRIES,
    handle_get_calibration_scoreboard,
    handle_get_ood_assessment,
    handle_list_open_predictions,
    handle_search_jobs,
)

mcp = FastMCP(
    "forecaster-agent",
    instructions=(
        "Read-only access to the forecaster-agent job radar and calibration data. "
        "Use get_ood_assessment when extrapolating beyond historical tech transitions. "
        "All outputs are speculative — not financial or career advice."
    ),
)


@mcp.tool(
    name="get_calibration_scoreboard",
    description=(
        "Return Brier calibration metrics: total/open/resolved counts, mean Brier, "
        "and 10-decile reliability curve. Lower Brier is better (0=perfect)."
    ),
)
def get_calibration_scoreboard() -> dict:
    return handle_get_calibration_scoreboard()


@mcp.tool(
    name="get_ood_assessment",
    description=(
        "Assess whether the current AI×economy scenario is out-of-distribution vs "
        "15+ historical tech transitions. Returns Mahalanobis distance, nearest "
        "historical regime, conditional rules, and prompt_context. "
        "Optional scenario_json: JSON object overriding evolution scenario variables "
        "(augmentation_ratio, demand_elasticity, oring_leverage, skill_distance, "
        "diffusion_years, absorbing_sector, productivity_capture, task_frontier_open)."
    ),
)
def get_ood_assessment(
    scenario_json: str | None = None,
    n_bootstrap: int | None = None,
) -> dict:
    return handle_get_ood_assessment(scenario_json=scenario_json, n_bootstrap=n_bootstrap)


@mcp.tool(
    name="search_jobs",
    description=(
        "Hybrid RAG job search: ranked occupations by impact score and semantic "
        f"similarity to query. industry filter: {', '.join(INDUSTRIES)}."
    ),
)
def search_jobs_tool(
    query: str = "",
    industry: str = "All",
    limit: int = 10,
    scenario_json: str | None = None,
) -> dict:
    return handle_search_jobs(
        query=query, industry=industry, limit=limit, scenario_json=scenario_json
    )


@mcp.tool(
    name="list_open_predictions",
    description=(
        "List open (unresolved) falsifiable AI×economy predictions from the registry, "
        "sorted by confidence descending."
    ),
)
def list_open_predictions_tool(limit: int = 20) -> dict:
    return handle_list_open_predictions(limit=limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
