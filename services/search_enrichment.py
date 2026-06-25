"""Web search enrichment for unknown job profiles.

Calls Tavily when TAVILY_API_KEY is set; returns empty context silently when not.
Used by job_radar.generate_job_profile_via_llm() to ground LLM output in real JD data.
"""
from __future__ import annotations

import os
from typing import Any


def search_job_context(query: str) -> str:
    """Return a ~500-token text block describing the role, or '' if unavailable.

    Searches for real job descriptions and skills so the LLM generates more
    accurate required_skills / displacement_risk / industry values.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return ""

    try:
        from tavily import TavilyClient  # type: ignore
    except ImportError:
        return ""

    try:
        client = TavilyClient(api_key)
        response = client.search(
            query=f"{query} job description skills responsibilities",
            include_answer="basic",
            search_depth="advanced",
            max_results=3,
        )
        return _extract_context(response, query)
    except Exception:
        return ""


def _extract_context(response: dict[str, Any], query: str) -> str:
    parts: list[str] = []

    answer = response.get("answer", "")
    if answer:
        parts.append(f"Summary: {answer}")

    for result in response.get("results", [])[:3]:
        title = result.get("title", "")
        content = result.get("content", "")
        if content:
            snippet = content[:400].replace("\n", " ").strip()
            parts.append(f"[{title}] {snippet}")

    if not parts:
        return ""

    joined = "\n\n".join(parts)
    # Cap to ~600 words to stay within token budget
    words = joined.split()
    if len(words) > 600:
        joined = " ".join(words[:600]) + "…"
    return joined
