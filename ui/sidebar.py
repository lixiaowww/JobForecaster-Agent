"""Sidebar scenario controls."""
from __future__ import annotations

import streamlit as st
import evolution as ev


VARIABLE_HELP = {
    "augmentation_ratio": "How much AI assists human workers (closer to 1.0) vs. replacing them (closer to 0.0).",
    "demand_elasticity": "How much lower costs increase demand. High elasticity (1.0) means lower costs create a massive boom in new jobs.",
    "oring_leverage": "How critical a single mistake is. High leverage (1.0) means even tiny human errors will force companies to automate.",
    "skill_distance": "How hard it is for workers to learn new skills. High distance (1.0) means transitioning to new jobs is extremely difficult.",
    "diffusion_years": "How many years it takes for this AI technology to be fully adopted across all industries.",
    "absorbing_sector": "Are there service sectors that can absorb displaced workers? If checked, other industries will absorb laid-off workers.",
    "productivity_capture": "How much of the productivity gains are kept by companies as profit (1.0) vs. shared with workers (0.0).",
    "task_frontier_open": "Does the technology create brand-new tasks and jobs? If checked, it will unlock new career paths that don't exist today.",
}


def render_sidebar() -> dict:
    with st.sidebar.expander("🧠 Theoretical Framework", expanded=False):
        st.markdown("""
    **Economic Theories:**
    * **Autor's Task Model**: Augmentation vs Substitution
    * **Jevons Paradox**: Demand Elasticity
    * **O-Ring Theory (Kremer)**: Task Complementarity
    * **Baumol's Cost Disease**: Absorbing Sectors

    **Mathematical & AI Methods:**
    * **Bayesian Gaussian Mixture**: Regime Clustering
    * **PCA Factor Analysis**: Latent Frictions
    * **Mahalanobis Distance**: OOD Detection
    * **LLM**: Structural Prompting & Reasoning
    """)


    st.sidebar.markdown("---")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ AI Scenario Presets")
    st.sidebar.markdown("""
    **How will AI shape the future economy?**
    Select a preset scenario below to see how different adoption speeds impact the job market, or expand the Advanced variables below to customize.
    """)

    # Define intuitive presets
    presets = {
        "🤖 Baseline AI Evolution": ev.CURRENT_AI_SCENARIO,
        "🧠 AGI Rapid Emergence": {
            "augmentation_ratio": 0.9, "demand_elasticity": 0.8, "oring_leverage": 0.9,
            "skill_distance": 0.2, "diffusion_years": 3.0, "absorbing_sector": 0.0,
            "productivity_capture": 0.8, "task_frontier_open": 1.0
        },
        "🦾 Physical Robotics Era": {
            "augmentation_ratio": 0.7, "demand_elasticity": 0.5, "oring_leverage": 0.6,
            "skill_distance": 0.8, "diffusion_years": 15.0, "absorbing_sector": 0.0,
            "productivity_capture": 0.6, "task_frontier_open": 0.0
        },
        "📉 AI Winter / Slow Adoption": {
            "augmentation_ratio": 0.3, "demand_elasticity": 0.3, "oring_leverage": 0.3,
            "skill_distance": 0.7, "diffusion_years": 20.0, "absorbing_sector": 1.0,
            "productivity_capture": 0.2, "task_frontier_open": 1.0
        }
    }

    selected_preset_name = st.sidebar.selectbox(
        "Select a macro-economic scenario:", 
        list(presets.keys()) + ["⚙️ Custom Configuration"]
    )

    # Load base scenario and override if a preset is selected
    base_scenario = dict(ev.CURRENT_AI_SCENARIO)
    if selected_preset_name in presets:
        base_scenario.update(presets[selected_preset_name])

    # Sidebar sliders for real-time scenario simulation
    scenario_input = {}
    VARIABLE_HELP = {
        "augmentation_ratio": "How much AI assists human workers (closer to 1.0) vs. replacing them (closer to 0.0).",
        "demand_elasticity": "How much lower costs increase demand. High elasticity (1.0) means lower costs create a massive boom in new jobs.",
        "oring_leverage": "How critical a single mistake is. High leverage (1.0) means even tiny human errors will force companies to automate.",
        "skill_distance": "How hard it is for workers to learn new skills. High distance (1.0) means transitioning to new jobs is extremely difficult.",
        "diffusion_years": "How many years it takes for this AI technology to be fully adopted across all industries.",
        "absorbing_sector": "Are there service sectors that can absorb displaced workers? If checked, other industries will absorb laid-off workers.",
        "productivity_capture": "How much of the productivity gains are kept by companies as profit (1.0) vs. shared with workers (0.0).",
        "task_frontier_open": "Does the technology create brand-new tasks and jobs? If checked, it will unlock new career paths that don't exist today."
    }

    with st.sidebar.expander("🛠️ Advanced Economic Variables", expanded=(selected_preset_name == "⚙️ Custom Configuration")):
        st.markdown("Fine-tune the underlying economic drivers:")
        for var in ev.VARIABLE_NAMES:
            title = var.replace("_", " ").title()
            var_help = VARIABLE_HELP.get(var, "")
            if var == "diffusion_years":
                scenario_input[var] = st.slider(
                    title, 
                    min_value=1.0, max_value=50.0, 
                    value=float(base_scenario[var]), 
                    step=0.5,
                    help=var_help
                )
            elif var in ["absorbing_sector", "task_frontier_open"]:
                # Use a checkbox for binary variables but convert to float
                checked = st.checkbox(
                    title, 
                    value=bool(base_scenario[var]),
                    help=var_help
                )
                scenario_input[var] = 1.0 if checked else 0.0
            else:
                scenario_input[var] = st.slider(
                    title, 
                    min_value=0.0, max_value=1.0, 
                    value=float(base_scenario[var]), 
                    step=0.05,
                    help=var_help
                )

    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    **Harness Compliance Check**
    * ✅ **Offline-First:** Runs stubs locally
    * ✅ **Pure Math:** Deterministic GMM/PCA
    * ✅ **Explicit Thresholds:** Configured stubs
    """)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ☕ Support & Donation")
    st.sidebar.markdown("""
    <div class="metric-card" style="text-align: left; padding: 12px; border-color: #38bdf8; background: rgba(56, 139, 253, 0.05); border-radius: 8px;">
        <p style="margin: 0; font-size: 0.85rem; line-height: 1.4; color: #8b949e !important;">
            If you find this forecasting dashboard useful, consider supporting our work!
        </p>
        <div style="margin-top: 10px; text-align: center;">
            <a href="https://buymeacoffee.com/lixiaowww" target="_blank" style="text-decoration: none;">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 40px !important;width: 145px !important;" >
            </a>
        </div>
    </div>
    """, unsafe_allow_html=True)
    return scenario_input
