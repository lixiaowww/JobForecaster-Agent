"""Streamlit dashboard entrypoint."""
from __future__ import annotations

import os
import sys
import traceback

import streamlit as st

# set_page_config must be the first Streamlit command (before session_state, etc.)
st.set_page_config(
    page_title="JobForecast Agent",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

_root = str(__import__("paths").PROJECT_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)
sys.path = [p for p in sys.path if p != "/home/sean"]

from services.config_loader import load_config
from services.dashboard_data import build_evolution_prior
from services.dashboard_seed import ensure_demo_registry
from ui.i18n import init_language, lang, t
from ui.sidebar import render_sidebar
from ui.styles import CUSTOM_CSS
from ui.tabs import accuracy, benchmarks, guard, radar

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

init_language()


def _space_bootstrap_iters() -> int | None:
    """Use fewer GMM iterations on HF Spaces (slow free CPU)."""
    if os.getenv("SPACE_ID"):
        return int(os.getenv("EVOLUTION_N_BOOTSTRAP", "15"))
    return None


def _render_main() -> None:
    ensure_demo_registry()

    config = load_config()
    job_radar_cfg = config.get("job_radar", {
        "alpha": 0.6,
        "beta": 0.4,
        "impact_threshold": 0.15,
        "kb_path": "data/jobs_kb.json",
    })

    scenario_input = render_sidebar(job_radar_cfg)

    st.markdown(f"""
    <div class="header-container">
        <div class="main-title">JobForecast Agent</div>
        <div class="subtitle">{t("page_subtitle")}</div>
    </div>
    """, unsafe_allow_html=True)

    @st.cache_resource(show_spinner=False)
    def get_cached_prior(scenario: dict, _lang: str, n_boot: int):
        del _lang
        return build_evolution_prior(scenario, n_bootstrap=n_boot)

    n_boot = _space_bootstrap_iters()
    if n_boot is None:
        n_boot = int(config.get("evolution", {}).get("n_bootstrap", 50))

    with st.spinner(t("gmm_spinner")):
        prior = get_cached_prior(scenario_input, lang(), n_boot)

    # Welcome banner — shown only on the first visit per session
    if not st.session_state.get("_welcome_dismissed"):
        with st.container():
            st.info(
                t("welcome_banner"),
                icon="🔮",
            )
            if st.button(t("welcome_dismiss"), key="welcome_dismiss_btn"):
                st.session_state["_welcome_dismissed"] = True
                st.rerun()

    tab_radar, tab_accuracy, tab_benchmarks, tab_guard = st.tabs([
        f"🎯 {t('tab_radar')}",
        f"📈 {t('tab_accuracy')}",
        f"🧬 {t('tab_benchmarks')}",
        f"🛡️ {t('tab_guard')}",
    ])

    with tab_radar:
        radar.render(scenario_input, prior, job_radar_cfg)
    with tab_accuracy:
        accuracy.render(scenario_input, prior, job_radar_cfg)
    with tab_benchmarks:
        benchmarks.render(scenario_input, prior, job_radar_cfg)
    with tab_guard:
        guard.render(scenario_input, prior, job_radar_cfg)


try:
    _render_main()
except Exception:
    st.error("Dashboard failed to load. Details below (share with support if this persists).")
    st.code(traceback.format_exc())
