"""Tests for forecast.py quality guards (HR-9): citation sanitiser & horizon normaliser.

All tests are offline — no API key required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from forecast import _sanitize_sources, _normalize_horizon


# ---------------------------------------------------------------------------
# _sanitize_sources
# ---------------------------------------------------------------------------

class TestSanitizeSources:
    def test_empty_list_returns_empty(self):
        assert _sanitize_sources([]) == []

    def test_non_list_returns_empty(self):
        assert _sanitize_sources(None) == []
        assert _sanitize_sources("http://example.com") == []

    def test_valid_https_url_kept(self):
        urls = ["https://bls.gov/news.release/empsit.htm"]
        assert _sanitize_sources(urls) == urls

    def test_valid_http_url_kept(self):
        urls = ["http://fred.stlouisfed.org/series/UNRATE"]
        assert _sanitize_sources(urls) == urls

    def test_url_without_scheme_dropped(self):
        assert _sanitize_sources(["bls.gov/something"]) == []

    def test_example_domain_dropped(self):
        assert _sanitize_sources(["https://example.com/foo"]) == []
        assert _sanitize_sources(["http://example.org/bar"]) == []

    def test_placeholder_domain_dropped(self):
        assert _sanitize_sources(["https://placeholder.com/data"]) == []

    def test_empty_string_dropped(self):
        assert _sanitize_sources([""]) == []

    def test_non_string_items_dropped(self):
        assert _sanitize_sources([None, 42, ["nested"]]) == []

    def test_future_arxiv_id_dropped(self):
        # 2699.12345 → year 2026 + 99 months in the future
        bad = "https://arxiv.org/abs/2699.12345"
        assert _sanitize_sources([bad]) == []

    def test_past_arxiv_id_kept(self):
        # 2301.00001 → January 2023, clearly in the past
        good = "https://arxiv.org/abs/2301.00001"
        assert _sanitize_sources([good]) == [good]

    def test_mixed_list_only_good_kept(self):
        sources = [
            "https://bls.gov/good",
            "https://example.com/bad",
            "https://arxiv.org/abs/2699.99999",  # future arXiv
            "not-a-url",
            "https://arxiv.org/abs/2205.12345",  # past arXiv, May 2022
        ]
        result = _sanitize_sources(sources)
        assert result == ["https://bls.gov/good", "https://arxiv.org/abs/2205.12345"]

    def test_www_prefix_stripped_for_domain_check(self):
        assert _sanitize_sources(["https://www.example.com/foo"]) == []


# ---------------------------------------------------------------------------
# _normalize_horizon
# ---------------------------------------------------------------------------

class TestNormalizeHorizon:
    def test_bare_year_becomes_q4(self):
        assert _normalize_horizon("2027") == "2027-Q4"

    def test_h1_becomes_q2(self):
        assert _normalize_horizon("2027-H1") == "2027-Q2"

    def test_h2_becomes_q4(self):
        assert _normalize_horizon("2027-H2") == "2027-Q4"

    def test_canonical_q3_passthrough(self):
        assert _normalize_horizon("2027-Q3") == "2027-Q3"

    def test_canonical_q1_passthrough(self):
        assert _normalize_horizon("2026-Q1") == "2026-Q1"

    def test_none_returns_empty_string(self):
        assert _normalize_horizon(None) == ""

    def test_empty_string_passthrough(self):
        assert _normalize_horizon("") == ""

    def test_arbitrary_string_passthrough(self):
        assert _normalize_horizon("end of 2027") == "end of 2027"

    def test_strip_whitespace(self):
        assert _normalize_horizon("  2026  ") == "2026-Q4"


# ---------------------------------------------------------------------------
# Groq rate-limit retry (offline: mock requests)
# ---------------------------------------------------------------------------

class TestGroqRateLimit:
    def test_429_triggers_retry_and_succeeds(self, monkeypatch):
        """First call returns 429, second returns 200."""
        import forecast as fc
        import types

        call_count = {"n": 0}

        class FakeResp:
            def __init__(self, status_code, body):
                self.status_code = status_code
                self._body = body
                self.headers = {"Retry-After": "0"}
                self.text = body

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

            def json(self):
                import json
                return json.loads(self._body)

        def fake_post(url, json=None, headers=None, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return FakeResp(429, '{"error":"rate limited"}')
            return FakeResp(200, '{"choices":[{"message":{"content":"ok"}}]}')

        monkeypatch.setattr("forecast.time.sleep", lambda s: None)
        import requests as _req
        monkeypatch.setattr(_req, "post", fake_post)

        result = fc._call_groq("sys", "usr", max_tokens=10, model="llama", api_key="x")
        assert result == "ok"
        assert call_count["n"] == 2

    def test_429_twice_raises_runtime_error(self, monkeypatch):
        import forecast as fc
        import requests as _req

        class FakeResp:
            status_code = 429
            headers = {"Retry-After": "0"}
            text = "rate limited"

            def raise_for_status(self):
                raise Exception(f"HTTP {self.status_code}")

        monkeypatch.setattr("forecast.time.sleep", lambda s: None)
        monkeypatch.setattr(_req, "post", lambda *a, **kw: FakeResp())

        with pytest.raises(RuntimeError):
            fc._call_groq("sys", "usr", max_tokens=10, model="llama", api_key="x")
