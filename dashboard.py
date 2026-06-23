"""Streamlit dashboard entrypoint."""
from __future__ import annotations

import sys

import streamlit as st

from paths import PROJECT_ROOT

_root = str(PROJECT_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)
sys.path = [p for p in sys.path if p != "/home/sean"]

from services.config_loader import load_config
from services.dashboard_data import build_evolution_prior
from services.dashboard_seed import ensure_demo_registry
from ui.sidebar import render_sidebar
from ui.styles import CUSTOM_CSS
from ui.tabs import accuracy, benchmarks, guard, radar

st.set_page_config(
    page_title="JobForecast Agent",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

ensure_demo_registry()

config = load_config()
job_radar_cfg = config.get("job_radar", {
    "alpha": 0.6,
    "beta": 0.4,
    "impact_threshold": 0.15,
    "kb_path": "data/jobs_kb.json",
})

scenario_input = render_sidebar()


@st.cache_resource(show_spinner="Computing GMM clustering...")
def get_cached_prior(scenario: dict):
    return build_evolution_prior(scenario)


prior = get_cached_prior(scenario_input)

st.markdown("""
<div class="header-container">
    <div class="main-title">JobForecast Agent</div>
    <div class="subtitle">Autonomous AI × economy forecasting system dashboard</div>
</div>
""", unsafe_allow_html=True)

tab_radar, tab_accuracy, tab_benchmarks, tab_guard = st.tabs([
    "🎯 Job Forecast Radar",
    "📈 Forecast Accuracy",
    "🧬 Historical Benchmarks",
    "🚨 Plausibility Guard",
])

with tab_radar:
    radar.render(scenario_input, prior, job_radar_cfg)
with tab_accuracy:
    accuracy.render(scenario_input, prior, job_radar_cfg)
with tab_benchmarks:
    benchmarks.render(scenario_input, prior, job_radar_cfg)
with tab_guard:
    guard.render(scenario_input, prior, job_radar_cfg)
