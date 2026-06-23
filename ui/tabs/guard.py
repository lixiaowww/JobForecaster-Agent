"""Tab: guard."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader("🚨 Plausibility Guard (设定合理性校验)")
    st.markdown("""
    **What is this?**
    When you adjust simulation parameters in the sidebar (such as productivity capture or diffusion speed), you might configure a scenario that is completely unprecedented in human history (e.g., 100x productivity gains in a single year).

    This page calculates the **Scenario Divergence Index** (Mahalanobis Distance) to check if your inputs are historically plausible.

    *   **Within Envelope (绿/蓝色):** Your scenario has historical precedents. The AI model will use historical data (e.g., the transition of secretaries during the PC revolution) to guide its forecasts.
    *   **Out of Distribution (红色警告):** Your scenario is historically extreme. The safety guard will automatically step in and adjust the forecasting parameters to prevent the AI from generating absurd or highly distorted predictions.
    """)
    ood = prior.current_scenario_ood

    # Gauge Chart for Mahalanobis Distance
    fig_gauge = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = ood["min_mahalanobis"],
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Scenario Divergence Index (Deviation from History)", 'font': {'size': 18}},
        gauge = {
            'axis': {'range': [0, max(8.0, ood["min_mahalanobis"] * 1.3)], 'tickcolor': '#c9d1d9'},
            'bar': {'color': "#ff5555" if ood["is_ood"] else "#38bdf8"},
            'bgcolor': "#161b22",
            'borderwidth': 2,
            'bordercolor': "#30363d",
            'steps': [
                {'range': [0, ood["threshold"]], 'color': '#21262d'},
                {'range': [ood["threshold"], max(8.0, ood["min_mahalanobis"] * 1.3)], 'color': '#3a1f1f' if ood["is_ood"] else '#1f2e3d'}
            ],
            'threshold': {
                'line': {'color': "#ff5555", 'width': 4},
                'thickness': 0.75,
                'value': ood["threshold"]
            }
        }
    ))

    fig_gauge.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#c9d1d9'),
        height=380,
        margin=dict(l=50, r=50, t=50, b=50)
    )

    col_gauge, col_info = st.columns([2, 3])
    with col_gauge:
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_info:
        st.subheader("🛠️ Safety Correction Actions (模型平滑校正)")
        
        if ood["is_ood"]:
            st.error(f"🚨 **STATUS: UNPRECEDENTED SCENARIO (超出历史范围)**\n\nYour inputs deviate from historical benchmarks (Index: {ood['min_mahalanobis']:.2f} / Max Safe Threshold: {ood['threshold']:.2f}).")
            st.markdown("""
            **Safety corrections activated to keep forecasts realistic:**
            * ⚠️ **Prepare for High Uncertainty:** AI will widen the confidence intervals (broaden the predicted ranges).
            * ⚠️ **Reduce Reliance on History:** AI will lower the weight of historical analogies since this scenario is unique.
            * ⚠️ **Highlight Novelty:** AI will flag these predictions as highly experimental and unprecedented.
            """)
        else:
            st.success(f"✅ **STATUS: HISTORICALLY PLAUSIBLE (符合历史范围)**\n\nYour inputs are within historical benchmarks (Index: {ood['min_mahalanobis']:.2f} / Limit: {ood['threshold']:.2f}).")
            st.markdown(f"""
            **AI baseline settings applied:**
            * 📌 **Anchor Historical Pattern:** AI will reference the **{prior.nearest_cluster.name}** technological transition.
            * 📌 **Apply Historical Baselines:** AI will use the historical job growth rate multiplier (**{prior.nearest_cluster.mean_multiplier:.2f}x**) and lag time (**{prior.nearest_cluster.mean_lag_years:.1f} years**) as anchor points.
            """)

    st.markdown("---")
    st.subheader("🔮 Simulated AI Impact: Emerging Occupations")
    st.info("💡 Detailed occupation analysis, career transition paths, and emergence timelines have moved to the **🎯 Job Predict Radar** tab. Visit that tab to explore the full knowledge base and Lightweight Hybrid RAG retrieval system.")

    st.markdown("---")

    col_rules, col_vars = st.columns(2)
    with col_rules:
        st.subheader("📋 Case Library Conditional Rules")
        for r in prior.conditional_rules:
            st.markdown(f"• {r}")
            
    with col_vars:
        st.subheader("⚙️ Scenario Vector Configurations")
        st.markdown("Adjust sidebar variables to see live vector updates.")
