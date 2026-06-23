"""Tab: guard."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from ui.i18n import t


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader(t("guard_title"))
    st.markdown(t("guard_intro"))
    ood = prior.current_scenario_ood
    divergence = float(ood["min_mahalanobis"])
    threshold = float(ood["threshold"])
    axis_max = max(8.0, divergence * 1.3, threshold * 1.15)

    col_metric1, col_metric2 = st.columns(2)
    with col_metric1:
        st.metric(t("guard_divergence"), f"{divergence:.2f}")
    with col_metric2:
        st.metric(t("guard_threshold"), f"{threshold:.2f}")

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=divergence,
        number={"valueformat": ".2f", "font": {"size": 36}},
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": t("guard_gauge_title"), "font": {"size": 18}},
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
        st.plotly_chart(fig_gauge, width="stretch")

    with col_info:
        st.subheader(t("guard_actions"))

        if ood["is_ood"]:
            st.error(t("guard_ood_status", d=divergence, t=threshold))
            st.markdown(t("guard_ood_actions"))
        else:
            st.success(t("guard_ok_status", d=divergence, t=threshold))
            st.markdown(t(
                "guard_ok_actions",
                regime=prior.nearest_cluster.name,
                mult=prior.nearest_cluster.mean_multiplier,
                lag=prior.nearest_cluster.mean_lag_years,
            ))

    st.markdown("---")
    st.subheader(t("guard_emerging"))
    st.info(t("guard_emerging_info"))

    st.markdown("---")

    col_rules, col_vars = st.columns(2)
    with col_rules:
        st.subheader(t("guard_rules"))
        for r in prior.conditional_rules:
            st.markdown(f"• {r}")

    with col_vars:
        st.subheader(t("guard_vector"))
        st.markdown(t("guard_vector_help"))
