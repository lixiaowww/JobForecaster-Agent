"""The reasoning core: turn evidence + track record into falsifiable predictions,
and judge whether past predictions came true.

LLM backend is selected at runtime:
  1. GROQ_API_KEY present  → Groq chat-completions (free tier, OpenAI-compatible)
  2. ANTHROPIC_API_KEY present → Anthropic Messages API
  3. Neither               → RuntimeError with setup instructions

The forecasting system prompt (forecast_system.md) grounds the model in the same
economic theory used elsewhere: Autor's augmentation/automation framework,
Schumpeterian creative destruction, Baumol's cost disease, Jevons' paradox,
comparative advantage, the O-ring theory.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from .schemas import Prediction, Signal
except ImportError:
    from schemas import Prediction, Signal

PROMPT_PATH = Path(__file__).resolve().parent / "forecast_system.md"

# ---------------------------------------------------------------------------
# Provider-routing LLM helper (harness seam: pure HTTP, no hidden SDK state)
# ---------------------------------------------------------------------------

_GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
_MOCK_MODE = False


def set_mock_mode(enabled: bool) -> None:
    """Enable deterministic LLM stub (for `run.py once --mock` and offline harness)."""
    global _MOCK_MODE
    _MOCK_MODE = enabled


def mock_mode_enabled() -> bool:
    if _MOCK_MODE:
        return True
    flag = os.environ.get("FORECASTER_MOCK_LLM", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _resolve_groq_model(model: Optional[str]) -> str:
    """Use config model only if it looks Groq-compatible; else default."""
    if model and not model.startswith("claude-"):
        return model
    return _GROQ_DEFAULT_MODEL


def call_llm(
    system: str,
    user: str,
    *,
    max_tokens: int = 4000,
    model: Optional[str] = None,
) -> str:
    """Route an LLM call to mock, Groq, or Anthropic (first available)."""
    if mock_mode_enabled():
        from services.mock_llm import mock_llm_response
        return mock_llm_response(system, user)

    groq_key = os.environ.get("GROQ_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if groq_key:
        return _call_groq(system, user, max_tokens=max_tokens,
                          model=_resolve_groq_model(model), api_key=groq_key)
    if anthropic_key:
        return _call_anthropic(system, user, max_tokens=max_tokens,
                               model=model or _ANTHROPIC_DEFAULT_MODEL)
    raise RuntimeError(
        "No LLM API key found. Set GROQ_API_KEY (free: https://console.groq.com) "
        "or ANTHROPIC_API_KEY in your environment or .env file."
    )


def _call_groq(system: str, user: str, *, max_tokens: int, model: str, api_key: str) -> str:
    """Call Groq's OpenAI-compatible chat completions endpoint."""
    import requests  # already in requirements.txt

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(_GROQ_ENDPOINT, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_anthropic(system: str, user: str, *, max_tokens: int, model: str) -> str:
    """Call Anthropic Messages API (fallback when GROQ_API_KEY is absent)."""
    import anthropic  # optional dep; imported lazily

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction: strip code fences, take the outermost object."""
    t = text.strip()
    if "```" in t:
        t = t.split("```")[1]
        t = t[4:] if t.lstrip().startswith("json") else t
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end + 1]
    return json.loads(t)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_predictions(
    signals: list[Signal],
    track_record: str,
    *,
    model: Optional[str] = None,
    max_predictions: int = 6,
    evolution_prior: Optional[str] = None,
) -> list[Prediction]:
    """Generate up to *max_predictions* new falsifiable predictions.

    Uses call_llm() for provider routing. External evidence should be pre-ingested
    as Signal objects via ingest.py. When *evolution_prior* is provided (from
    evolution.build_prior().to_prompt_context()), the model widens confidence when
    the current AI scenario is out-of-distribution vs historical transitions.
    """
    system = PROMPT_PATH.read_text()
    today = date.today().isoformat()
    evidence = "\n".join(f"- {s.as_context()}" for s in signals) or "(no fresh signals)"
    prior_block = evolution_prior or "(no evolution prior supplied)"

    user = f"""Today is {today}.

## Your own track record so far (use it to calibrate your confidence)
{track_record}

{prior_block}

## Fresh evidence ingested in this cycle
{evidence}

## Task
Produce up to {max_predictions} NEW, concrete, falsifiable predictions about how AI
technology and the economy will co-evolve. Each must be judgeable as clearly
true or false by a specific date. Avoid vague or unfalsifiable claims.

Return ONLY a JSON object of this exact shape, nothing else:
{{
  "predictions": [
    {{
      "statement": "specific falsifiable claim with a number/threshold where possible",
      "rationale": "1-3 sentences grounding it in economic theory + the evidence above",
      "category": "labor | compute | macro | capital | policy | adoption",
      "confidence": 0.0-1.0,
      "horizon": "e.g. 2026-Q4",
      "resolution_date": "YYYY-MM-DD",
      "resolution_criteria": "exactly how to decide true/false, naming the data source",
      "sources": ["url", "url"]
    }}
  ]
}}

Calibrate honestly: if your past resolved predictions show over-confidence, lower
your confidence accordingly. If the job-evolution prior shows OUTSIDE HISTORY, widen
confidence intervals and avoid precise point estimates. Reserve high confidence (>0.8)
for near-certainties."""

    text = call_llm(system, user, max_tokens=4000, model=model)
    data = _parse_json(text)

    preds: list[Prediction] = []
    for item in data.get("predictions", []):
        try:
            preds.append(Prediction.model_validate(item).assign_id())
        except Exception as e:
            print(f"  ! skipped malformed prediction: {e}")
    return preds


def judge_prediction(
    pred: Prediction,
    signals: list[Signal],
    *,
    model: Optional[str] = None,
) -> tuple[bool | None, str]:
    """Decide whether a due prediction came true. Returns (outcome, rationale).
    outcome is True/False, or None when genuinely undecidable.
    """
    system = (
        "You are a strict, impartial forecasting judge. Decide whether the prediction "
        "resolved TRUE or FALSE based on real-world facts as of today. If the evidence "
        "is genuinely insufficient, answer AMBIGUOUS. Do not be charitable to the "
        "forecaster. Cite the facts you relied on."
    )
    evidence = "\n".join(f"- {s.as_context()}" for s in signals) or "(none)"
    user = f"""Prediction: {pred.statement}
Made on: {pred.created_at.date()}  |  Resolution date: {pred.resolution_date}
Resolution criteria: {pred.resolution_criteria}

Fresh evidence available:
{evidence}

Return ONLY JSON: {{"verdict": "TRUE|FALSE|AMBIGUOUS", "rationale": "facts you relied on"}}"""

    text = call_llm(system, user, max_tokens=1200, model=model)
    data = _parse_json(text)
    verdict = data.get("verdict", "AMBIGUOUS").upper()
    rationale = data.get("rationale", "")
    outcome = {"TRUE": True, "FALSE": False}.get(verdict, None)
    return outcome, rationale
