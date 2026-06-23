"""Tab: benchmarks."""
from __future__ import annotations

import streamlit as st
import math
import evolution as ev
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ui.i18n import t


@st.cache_resource(show_spinner=False)
def _benchmark_models():
    """Historical case PCA + GMM (independent of user scenario)."""
    cases = ev.CASE_LIBRARY
    reducer = ev.PCAReducer(n_components=3)
    clusterer = ev.BayesianGMMClusterer(max_components=5)
    X = ev._normalise_diffusion(cases)
    reducer.fit(X)
    Z = reducer.transform(X)
    labels = clusterer.fit(Z).predict(Z)
    return Z, labels, reducer


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader(t("bench_title"))
    st.markdown(t("bench_intro"))

    cases = ev.CASE_LIBRARY
    Z, labels, reducer = _benchmark_models()

    cluster_names = {c.label: c.name for c in prior.clusters}

    df_cases = pd.DataFrame([{
        "ID": c.id,
        "Name": c.name,
        "Technology": c.technology,
        "Displaced Occupation": c.displaced_occupation,
        "Period": c.period,
        "Augmentation Ratio": c.augmentation_ratio,
        "Demand Elasticity": c.demand_elasticity,
        "Skill Distance": c.skill_distance,
        "Diffusion Years": c.diffusion_years,
        "Absorbing Sector": c.absorbing_sector,
        "Productivity Capture": c.productivity_capture,
        "Task Frontier Open": c.task_frontier_open,
        "Net Job Multiplier": c.net_job_multiplier,
        "Lag Years": c.lag_years,
        "Notes": c.notes,
        "Sources": ", ".join(c.sources),
        "PCA1": Z[i, 0],
        "PCA2": Z[i, 1],
        "PCA3": Z[i, 2],
        "Cluster Label": labels[i],
        "Cluster Name": cluster_names.get(labels[i], f"Regime {labels[i]}")
    } for i, c in enumerate(cases)])

    # Compute scenario projected point
    scenario_vec = np.array([
        scenario_input.get(v, 0.5) if v != "diffusion_years"
        else math.log1p(scenario_input.get(v, 10)) / math.log1p(50)
        for v in ev.VARIABLE_NAMES
    ], dtype=float).reshape(1, -1)
    z_scenario = reducer.transform(scenario_vec)[0]

    # Select visualization
    col_vis, col_meta = st.columns([3, 2])

    none_label = t("filter_none")
    plot_modes = ("3d", "2d")

    with col_vis:
        col_radio, col_select = st.columns([1, 1])
        with col_radio:
            plot_key = st.radio(
                t("bench_plot_label"),
                plot_modes,
                format_func=lambda k: t(f"bench_plot_{k}"),
                horizontal=True,
            )
        with col_select:
            highlight_case = st.selectbox(
                t("bench_highlight"),
                [none_label] + list(df_cases["Name"].unique()),
                index=0,
            )

        if plot_key == "3d":
            fig_3d = go.Figure()
            for label_val in sorted(df_cases["Cluster Label"].unique()):
                df_c = df_cases[df_cases["Cluster Label"] == label_val]
                c_name = cluster_names.get(label_val, f"Regime {label_val}")
                fig_3d.add_trace(go.Scatter3d(
                    x=df_c["PCA1"], y=df_c["PCA2"], z=df_c["PCA3"],
                    mode='markers',
                    marker=dict(size=7, opacity=0.85),
                    name=c_name,
                    text=df_c["Name"] + "<br>Tech: " + df_c["Technology"] + "<br>Multiplier: " + df_c["Net Job Multiplier"].astype(str),
                    hoverinfo='text'
                ))
            
            fig_3d.add_trace(go.Scatter3d(
                x=[z_scenario[0]], y=[z_scenario[1]], z=[z_scenario[2]],
                mode='markers',
                marker=dict(size=14, color='#ff5555', symbol='diamond', line=dict(color='#ffffff', width=2)),
                name=t("bench_sim_scenario"),
                text=[t("bench_sim_scenario") + "<br>Mahalanobis: " + str(prior.current_scenario_ood["min_mahalanobis"])],
                hoverinfo='text'
            ))

            if highlight_case != none_label:
                selected_row = df_cases[df_cases["Name"] == highlight_case].iloc[0]
                fig_3d.add_trace(go.Scatter3d(
                    x=[selected_row["PCA1"]],
                    y=[selected_row["PCA2"]],
                    z=[selected_row["PCA3"]],
                    mode='markers+text',
                    marker=dict(size=14, color='#f1c40f', symbol='circle', line=dict(color='#ffffff', width=3)),
                    name=f"Highlighted: {highlight_case}",
                    text=[f"👉 {highlight_case}"],
                    textposition="top center",
                    textfont=dict(color='#f1c40f', size=12),
                    hoverinfo='text'
                ))

            fig_3d.update_layout(
                scene=dict(
                    xaxis=dict(title='PCA 1 (Complementarity)', gridcolor='#21262d', backgroundcolor='rgba(0,0,0,0)'),
                    yaxis=dict(title='PCA 2 (Friction)', gridcolor='#21262d', backgroundcolor='rgba(0,0,0,0)'),
                    zaxis=dict(title='PCA 3 (Demand Expansion)', gridcolor='#21262d', backgroundcolor='rgba(0,0,0,0)'),
                    bgcolor='rgba(0,0,0,0)',
                ),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#c9d1d9'),
                height=500,
                margin=dict(l=0, r=0, t=0, b=0),
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
            )
            st.plotly_chart(fig_3d, width="stretch")
            
        else:
            fig_2d = px.scatter(
                df_cases, x="PCA1", y="PCA2",
                color="Cluster Name",
                hover_name="Name",
                hover_data=["Technology", "Net Job Multiplier", "Lag Years"],
                color_discrete_sequence=px.colors.qualitative.Safe,
                title="PCA 2D",
            )
            fig_2d.add_trace(go.Scatter(
                x=[z_scenario[0]], y=[z_scenario[1]],
                mode='markers',
                marker=dict(size=14, color='#ff5555', symbol='diamond', line=dict(color='#ffffff', width=2)),
                name=t("bench_sim_scenario"),
                hoverinfo='text',
                text=[t("bench_sim_scenario") + "<br>Distance: " + str(prior.current_scenario_ood["min_mahalanobis"])]
            ))

            if highlight_case != none_label:
                selected_row = df_cases[df_cases["Name"] == highlight_case].iloc[0]
                fig_2d.add_trace(go.Scatter(
                    x=[selected_row["PCA1"]],
                    y=[selected_row["PCA2"]],
                    mode='markers+text',
                    marker=dict(size=14, color='#f1c40f', symbol='circle', line=dict(color='#ffffff', width=3)),
                    name=f"Highlighted: {highlight_case}",
                    text=[f"👉 {highlight_case}"],
                    textposition="top center",
                    textfont=dict(color='#f1c40f', size=12),
                    hoverinfo='text'
                ))

            fig_2d.update_layout(
                xaxis=dict(title='PCA 1 (Complementarity)', gridcolor='#21262d'),
                yaxis=dict(title='PCA 2 (Friction)', gridcolor='#21262d'),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#c9d1d9'),
                height=500
            )
            st.plotly_chart(fig_2d, width="stretch")

    with col_meta:
        st.markdown(f"### {t('bench_regimes')}")
        st.markdown(t("bench_confidence", p=prior.bootstrap_stability * 100))
        
        profile_data = []
        for c in prior.clusters:
            profile_data.append({
                "Regime Cluster": c.name,
                "Size (Cases)": c.size,
                "Job Multiplier": f"{c.mean_multiplier:.2f}x",
                "Adjustment Lag": f"{c.mean_lag_years:.1f} yr"
            })
        st.dataframe(pd.DataFrame(profile_data), width="stretch", hide_index=True)
        
        st.markdown(t("bench_regimes_tip"))

        if highlight_case != none_label:
            selected_row = df_cases[df_cases["Name"] == highlight_case].iloc[0]
            st.markdown(f"""
            <div style="border: 1px solid #f1c40f; border-radius: 6px; padding: 15px; background-color: #161b22; margin-top: 15px;">
                <h4 style="color:#f1c40f; margin-top:0; margin-bottom:10px;">{t("bench_highlight_details")}</h4>
                <table style="width:100%; border-collapse:collapse; font-size:13px; color:#c9d1d9;">
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Event / Job:</b></td><td style="padding:6px 0;">{selected_row['Name']} ({selected_row['Period']})</td></tr>
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Technology:</b></td><td style="padding:6px 0;">{selected_row['Technology']}</td></tr>
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Displaced Job:</b></td><td style="padding:6px 0;">{selected_row['Displaced Occupation']}</td></tr>
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Job Multiplier:</b></td><td style="padding:6px 0;">{selected_row['Net Job Multiplier']}x</td></tr>
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Transition Lag:</b></td><td style="padding:6px 0;">{selected_row['Lag Years']} years</td></tr>
                    <tr style="border-bottom: 1px solid #21262d;"><td style="padding:6px 0; color:#8b949e;"><b>Regime Cluster:</b></td><td style="padding:6px 0;">{selected_row['Cluster Name']}</td></tr>
                </table>
                <p style="font-size: 12px; color: #8b949e; line-height: 1.4; margin-top: 10px; margin-bottom: 0;"><b>Notes:</b> {selected_row['Notes']}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    with st.expander(t("bench_library")):
        st.dataframe(
            df_cases[["Name", "Cluster Name", "Period", "Technology", "Displaced Occupation", "Net Job Multiplier", "Lag Years", "Notes", "Sources"]],
            width="stretch", hide_index=True
        )
