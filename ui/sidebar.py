"""Sidebar scenario controls."""
from __future__ import annotations

import streamlit as st
import evolution as ev

from ui.i18n import render_language_selector, t, var_help, var_label

_PRESETS: dict[str, dict] = {
    "baseline": ev.CURRENT_AI_SCENARIO,
    "agi": {
        "augmentation_ratio": 0.9, "demand_elasticity": 0.8, "oring_leverage": 0.9,
        "skill_distance": 0.2, "diffusion_years": 3.0, "absorbing_sector": 0.0,
        "productivity_capture": 0.8, "task_frontier_open": 1.0,
    },
    "robotics": {
        "augmentation_ratio": 0.7, "demand_elasticity": 0.5, "oring_leverage": 0.6,
        "skill_distance": 0.8, "diffusion_years": 15.0, "absorbing_sector": 0.0,
        "productivity_capture": 0.6, "task_frontier_open": 0.0,
    },
    "winter": {
        "augmentation_ratio": 0.3, "demand_elasticity": 0.3, "oring_leverage": 0.3,
        "skill_distance": 0.7, "diffusion_years": 20.0, "absorbing_sector": 1.0,
        "productivity_capture": 0.2, "task_frontier_open": 1.0,
    },
}


def render_sidebar() -> dict:
    render_language_selector()

    with st.sidebar.expander(f"🧠 {t('sidebar_framework')}", expanded=False):
        st.markdown(t("sidebar_framework_body"))

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"### ⚙️ {t('sidebar_presets')}")
    st.sidebar.markdown(t("sidebar_presets_help"))

    preset_ids = list(_PRESETS.keys()) + ["custom"]
    selected_id = st.sidebar.selectbox(
        t("sidebar_preset_label"),
        preset_ids,
        format_func=lambda pid: t(f"preset_{pid}"),
    )

    base_scenario = dict(ev.CURRENT_AI_SCENARIO)
    if selected_id in _PRESETS:
        base_scenario.update(_PRESETS[selected_id])

    scenario_input: dict = {}
    with st.sidebar.expander(
        f"🛠️ {t('sidebar_advanced')}",
        expanded=(selected_id == "custom"),
    ):
        st.markdown(t("sidebar_advanced_help"))
        for var in ev.VARIABLE_NAMES:
            if var == "diffusion_years":
                scenario_input[var] = st.slider(
                    var_label(var),
                    min_value=1.0, max_value=50.0,
                    value=float(base_scenario[var]),
                    step=0.5,
                    help=var_help(var),
                )
            elif var in ("absorbing_sector", "task_frontier_open"):
                checked = st.checkbox(
                    var_label(var),
                    value=bool(base_scenario[var]),
                    help=var_help(var),
                )
                scenario_input[var] = 1.0 if checked else 0.0
            else:
                scenario_input[var] = st.slider(
                    var_label(var),
                    min_value=0.0, max_value=1.0,
                    value=float(base_scenario[var]),
                    step=0.05,
                    help=var_help(var),
                )

    st.sidebar.markdown("---")
    st.sidebar.markdown(t("sidebar_harness"))

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"### ☕ {t('sidebar_donation')}")
    st.sidebar.markdown(f"""
    <div class="metric-card" style="text-align: left; padding: 12px; border-color: #38bdf8; background: rgba(56, 139, 253, 0.05); border-radius: 8px;">
        <p style="margin: 0; font-size: 0.85rem; line-height: 1.4; color: #8b949e !important;">
            {t("sidebar_donation_body")}
        </p>
        <div style="margin-top: 10px; text-align: center;">
            <a href="https://buymeacoffee.com/lixiaowww" target="_blank" style="text-decoration: none;">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 40px !important;width: 145px !important;" >
            </a>
        </div>
    </div>
    """, unsafe_allow_html=True)
    return scenario_input
