"""Ingestion layer: pull recent AI-tech and economic signals from the world.

Sources are pluggable. arXiv and RSS need no API key and work out of the box.
Tavily (web search) and FRED (economic indicators) activate only if their keys
are present in the environment. Add your own source by implementing `.gather()`.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Protocol

import requests

try:
    from schemas import Signal
except ImportError:
    from .schemas import Signal

UA = {"User-Agent": "forecaster-agent/1.0 (+https://example.com)"}


class Source(Protocol):
    name: str
    def gather(self, limit: int) -> list[Signal]: ...


class ArxivSource:
    """Recent papers from arXiv categories (default: AI + economics)."""
    name = "arxiv"

    def __init__(self, categories: list[str] | None = None):
        self.categories = categories or ["cs.AI", "cs.LG", "econ.GN"]

    def gather(self, limit: int = 15) -> list[Signal]:
        import feedparser
        q = "+OR+".join(f"cat:{c}" for c in self.categories)
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query={q}&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={limit}"
        )
        feed = feedparser.parse(url)
        sigs = []
        for e in feed.entries:
            sigs.append(Signal(
                source="arxiv",
                title=e.title.replace("\n", " ").strip(),
                url=e.link,
                summary=e.summary.replace("\n", " ").strip()[:500],
                published=getattr(e, "published", None),
                kind="paper",
            ))
        return sigs


class RSSSource:
    """Generic RSS/Atom feeds for AI + economy news."""
    name = "rss"
    DEFAULT_FEEDS = [
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://feeds.bbci.co.uk/news/business/economy/rss.xml",
        "https://blog.google/technology/ai/rss/",
    ]

    def __init__(self, feeds: list[str] | None = None):
        self.feeds = feeds or self.DEFAULT_FEEDS

    def gather(self, limit: int = 20) -> list[Signal]:
        import feedparser
        sigs: list[Signal] = []
        per = max(1, limit // max(1, len(self.feeds)))
        for url in self.feeds:
            feed = feedparser.parse(url)
            for e in feed.entries[:per]:
                sigs.append(Signal(
                    source=feed.feed.get("title", "rss"),
                    title=getattr(e, "title", "").strip(),
                    url=getattr(e, "link", ""),
                    summary=getattr(e, "summary", "")[:400],
                    published=getattr(e, "published", None),
                    kind="news",
                ))
        return sigs


class TavilySource:
    """Web search via Tavily. Activates only if TAVILY_API_KEY is set."""
    name = "tavily"

    def __init__(self, queries: list[str] | None = None):
        self.key = os.getenv("TAVILY_API_KEY")
        self.queries = queries or [
            "AI labor market impact this week",
            "AI capex compute data center spending latest",
            "macroeconomic outlook AI productivity",
        ]

    def gather(self, limit: int = 9) -> list[Signal]:
        if not self.key:
            return []
        sigs: list[Signal] = []
        per = max(1, limit // len(self.queries))
        for query in self.queries:
            try:
                r = requests.post(
                    "https://api.tavily.com/search",
                    json={"api_key": self.key, "query": query,
                          "max_results": per, "topic": "news"},
                    timeout=30,
                )
                for item in r.json().get("results", []):
                    sigs.append(Signal(
                        source="tavily", title=item.get("title", ""),
                        url=item.get("url", ""),
                        summary=item.get("content", "")[:400], kind="news"))
            except Exception:
                continue
        return sigs


class FredSource:
    """Key US economic indicators via FRED. Activates only if FRED_API_KEY is set."""
    name = "fred"
    SERIES = {"UNRATE": "unemployment rate", "GDPC1": "real GDP",
              "CPIAUCSL": "CPI", "PAYEMS": "nonfarm payrolls"}

    def __init__(self):
        self.key = os.getenv("FRED_API_KEY")

    def gather(self, limit: int = 4) -> list[Signal]:
        if not self.key:
            return []
        sigs: list[Signal] = []
        for sid, label in self.SERIES.items():
            try:
                r = requests.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={"series_id": sid, "api_key": self.key,
                            "file_type": "json", "sort_order": "desc", "limit": 2},
                    timeout=30,
                )
                obs = r.json().get("observations", [])
                if len(obs) >= 2:
                    cur, prev = obs[0], obs[1]
                    sigs.append(Signal(
                        source="FRED", title=f"{label} ({sid})",
                        summary=f"latest {cur['value']} on {cur['date']} "
                                f"(prev {prev['value']})",
                        published=cur["date"], kind="indicator"))
            except Exception:
                continue
        return sigs


def gather_signals(sources: list[Source], max_total: int = 40) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for src in sources:
        for s in src.gather(limit=max_total):
            key = (s.url or s.title).strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(s)
    return out[:max_total]


def default_sources() -> list[Source]:
    return [ArxivSource(), RSSSource(), TavilySource(), FredSource()]
