"""Tab: guard."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader("Plausibility Guard")
    st.markdown("""
    **What is this?**
    When you adjust simulation parameters in the sidebar (such as productivity capture or diffusion speed),
    you might configure a scenario that is unprecedented in human history.

    This page calculates the **Scenario Divergence Index** (Mahalanobis distance) to check whether your
    inputs are historically plausible.

    * **Within envelope (blue):** Your scenario has historical precedents. The model anchors on similar past transitions.
    * **Out of distribution (red):** Your scenario is historically extreme. Safety guards widen uncertainty automatically.
    """)
    ood = prior.current_scenario_ood
    divergence = float(ood["min_mahalanobis"])
    threshold = float(ood["threshold"])
    axis_max = max(8.0, divergence * 1.3, threshold * 1.15)

    col_metric1, col_metric2 = st.columns(2)
    with col_metric1:
        st.metric("Divergence index", f"{divergence:.2f}")
    with col_metric2:
        st.metric("Safety threshold", f"{threshold:.2f}")

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=divergence,
        number={"valueformat": ".2f", "font": {"size": 36}},
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "Scenario divergence (Mahalanobis distance)", "font": {"size": 18}},
        gauge={
            "axis": {"range": [0, axis_max], "tickcolor": "#c9d1d9"},
            "bar": {"color": "#ff5555" if ood["is_ood"] else "#38bdf8"},
            "bgcolor": "#161b22",
            "borderwidth": 2,
            "bordercolor": "#30363d",
            "steps": [
                {"range": [0, threshold], "color": "#21262d"},
                {
                    "range": [threshold, axis_max],
                    "color": "#3a1f1f" if ood["is_ood"] else "#1f2e3d",
                },
            ],
            "threshold": {
                "line": {"color": "#ff5555", "width": 4},
                "thickness": 0.75,
                "value": threshold,
            },
        },
    ))

    fig_gauge.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c9d1d9"),
        height=380,
        margin=dict(l=50, r=50, t=50, b=50),
    )

    col_gauge, col_info = st.columns([2, 3])
    with col_gauge:
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_info:
        st.subheader("Safety correction actions")

        if ood["is_ood"]:
            st.error(
                f"**Status: unprecedented scenario**\n\n"
                f"Index {divergence:.2f} exceeds the safe threshold ({threshold:.2f})."
            )
            st.markdown("""
            **Safety corrections activated:**
            * Widen confidence intervals for experimental scenarios.
            * Reduce weight on historical analogies that no longer apply.
            * Flag forecasts as high-uncertainty and unprecedented.
            """)
        else:
            st.success(
                f"**Status: historically plausible**\n\n"
                f"Index {divergence:.2f} is within the safe envelope (limit {threshold:.2f})."
            )
            st.markdown(f"""
            **Baseline settings applied:**
            * Anchor on the **{prior.nearest_cluster.name}** transition pattern.
            * Use historical job multiplier **{prior.nearest_cluster.mean_multiplier:.2f}x**
              and lag **{prior.nearest_cluster.mean_lag_years:.1f} years** as anchors.
            """)

    st.markdown("---")
    st.subheader("Simulated AI impact: emerging occupations")
    st.info(
        "Occupation analysis and career transition paths live on the **Job Forecast Radar** tab."
    )

    st.markdown("---")

    col_rules, col_vars = st.columns(2)
    with col_rules:
        st.subheader("Case library conditional rules")
        for r in prior.conditional_rules:
            st.markdown(f"• {r}")

    with col_vars:
        st.subheader("Scenario vector")
        st.markdown("Adjust sidebar variables to see live vector updates.")
