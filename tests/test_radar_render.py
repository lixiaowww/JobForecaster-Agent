"""End-to-end render() smoke tests for the Job Forecast Radar tab.

Drives ui.tabs.radar.render() with a fake Streamlit so UI-layer crashes
(None comparisons, KeyErrors, format_func errors) are caught offline.
"""
from __future__ import annotations

import sys
import types

import pytest

import evolution as ev
import job_radar
from services.dashboard_data import build_evolution_prior


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeStreamlit(types.ModuleType):
    """Minimal Streamlit stand-in that records calls and never touches a browser."""

    def __init__(self, select_overrides=None, lang="en", search_text=""):
        super().__init__("streamlit")
        self.errors: list[str] = []
        self.markdowns: list[str] = []
        self.session_state: dict = {"dashboard_lang": lang}
        self._select_overrides = select_overrides or {}
        self._search_text = search_text

    # passthrough display sinks
    def subheader(self, *a, **k):
        pass

    def markdown(self, body="", *a, **k):
        self.markdowns.append(str(body))

    def write(self, *a, **k):
        pass

    def caption(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def success(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, body="", *a, **k):
        self.errors.append(str(body))

    def code(self, *a, **k):
        pass

    def metric(self, *a, **k):
        pass

    def plotly_chart(self, *a, **k):
        pass

    # layout / containers
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Ctx() for _ in range(n)]

    def expander(self, *a, **k):
        return _Ctx()

    def spinner(self, *a, **k):
        return _Ctx()

    def form(self, *a, **k):
        return _Ctx()

    def button(self, *a, **k):
        return False  # never "clicked" in tests

    def form_submit_button(self, *a, **k):
        return False  # never submit → no DB writes

    # inputs — exercise format_func to catch label-rendering crashes
    def text_input(self, label="", value="", **k):
        # the radar search box is the only free-text input that affects logic
        return self._search_text

    def selectbox(self, label="", options=None, format_func=None, **k):
        options = list(options or [])
        if format_func:
            for opt in options:  # render every label to surface crashes
                format_func(opt)
        if label in self._select_overrides:
            return self._select_overrides[label]
        return options[0] if options else None

    def slider(self, label="", min_value=0, max_value=100, value=0, **k):
        return value

    def radio(self, label="", options=None, **k):
        options = list(options or [])
        return options[0] if options else None


class _FakeFig:
    def update_layout(self, *a, **k):
        pass

    def update_traces(self, *a, **k):
        pass


def _install_fake_plotly(monkeypatch):
    px = types.ModuleType("plotly.express")
    px.scatter = lambda *a, **k: _FakeFig()
    px.bar = lambda *a, **k: _FakeFig()
    colors = types.SimpleNamespace(qualitative=types.SimpleNamespace(Safe=["#1f77b4"]))
    px.colors = colors
    go = types.ModuleType("plotly.graph_objects")
    go.Figure = lambda *a, **k: _FakeFig()
    go.Scatter = lambda *a, **k: None
    go.Indicator = lambda *a, **k: None
    plotly = types.ModuleType("plotly")
    plotly.express = px
    plotly.graph_objects = go
    monkeypatch.setitem(sys.modules, "plotly", plotly)
    monkeypatch.setitem(sys.modules, "plotly.express", px)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", go)


def _install_fake(monkeypatch, overrides=None, lang="en", search_text=""):
    fake = FakeStreamlit(select_overrides=overrides, lang=lang, search_text=search_text)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    _install_fake_plotly(monkeypatch)
    # reimport radar so its module-level `import streamlit as st` binds the fake
    for mod in ("ui.tabs.radar", "ui.sidebar"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    import importlib
    radar = importlib.import_module("ui.tabs.radar")
    return radar, fake


@pytest.fixture
def cfg():
    return {"alpha": 0.6, "beta": 0.4, "impact_threshold": 0.15, "kb_path": "data/jobs_kb.json"}


@pytest.fixture(scope="module")
def prior():
    return build_evolution_prior(ev.CURRENT_AI_SCENARIO, n_bootstrap=5)


def test_render_no_query_runs_clean(monkeypatch, cfg, prior):
    radar, fake = _install_fake(monkeypatch)
    radar.render(dict(ev.CURRENT_AI_SCENARIO), prior, cfg)
    assert fake.errors == []


def test_render_selecting_role_with_transitions(monkeypatch, cfg, prior):
    """Selecting an at-risk role must render its transition cards safely (BUG-1/2)."""
    kb = job_radar.load_knowledge_base("data/jobs_kb.json")
    # find a role that actually has resolvable transition targets
    ids = {j["id"] for j in kb}
    role_id = next(
        j["id"] for j in kb
        if any(
            (job_radar._normalize_transition_target(t) or {}).get("target_id") in ids
            for t in j.get("transition_targets", [])
        )
    )
    from ui.i18n import _STRINGS
    role_label = _STRINGS["radar_select_role"]["en"]
    radar, fake = _install_fake(monkeypatch, overrides={role_label: role_id})
    radar.render(dict(ev.CURRENT_AI_SCENARIO), prior, cfg)
    assert fake.errors == []


def test_render_extreme_scenario_values(monkeypatch, cfg, prior):
    radar, fake = _install_fake(monkeypatch)
    extreme = {k: 1.0 for k in ev.VARIABLE_NAMES}
    extreme["diffusion_years"] = 50.0
    radar.render(extreme, prior, cfg)
    assert fake.errors == []


def test_render_empty_kb(monkeypatch, prior):
    radar, fake = _install_fake(monkeypatch)
    radar.render(dict(ev.CURRENT_AI_SCENARIO), prior, {"kb_path": "data/does_not_exist.json"})
    # empty KB → warning path, no crash
    assert fake.errors == []


def test_render_chinese_mode(monkeypatch, cfg, prior):
    radar, fake = _install_fake(monkeypatch, lang="zh")
    radar.render(dict(ev.CURRENT_AI_SCENARIO), prior, cfg)
    assert fake.errors == []


def test_render_with_search_query_hit(monkeypatch, cfg, prior):
    """Search query that matches the KB exercises the find_best_match success path."""
    radar, fake = _install_fake(monkeypatch, search_text="financial analyst")
    radar.render(dict(ev.CURRENT_AI_SCENARIO), prior, cfg)
    assert fake.errors == []
