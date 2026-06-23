"""Deterministic LLM stub responses for offline harness (HR-1)."""
from __future__ import annotations

import json
from datetime import date, timedelta


def mock_llm_response(system: str, user: str) -> str:
    """Return fixed JSON for judge or forecast prompts — no network."""
    if "verdict" in user.lower() or "TRUE|FALSE|AMBIGUOUS" in user:
        return json.dumps({
            "verdict": "AMBIGUOUS",
            "rationale": "Mock judge (offline): evidence insufficient for deterministic resolution.",
        })

    resolution = (date.today() + timedelta(days=180)).isoformat()
    return json.dumps({
        "predictions": [
            {
                "statement": (
                    "Mock harness: aggregate US hyperscaler AI capex exceeds $350B "
                    "in the next measured fiscal year"
                ),
                "rationale": (
                    "Because this is offline mock mode therefore the claim is deterministic; "
                    "however it mirrors capital-expenditure forecasting structure for harness tests."
                ),
                "category": "capital",
                "confidence": 0.55,
                "horizon": "2027-H1",
                "resolution_date": resolution,
                "resolution_criteria": "Sum of disclosed capex in 10-K filings (mock/offline).",
                "sources": ["https://example.com/mock-harness"],
            }
        ]
    })
