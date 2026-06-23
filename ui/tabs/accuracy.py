"""Tab: accuracy."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

import streamlit as st
from services.dashboard_data import get_predictions, get_scoreboard_data
import market
from schemas import Status
from ui.i18n import filter_all_label, t


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader(t("acc_title"))
    st.markdown(t("acc_intro"))
    try:
        sb = get_scoreboard_data()
        preds = get_predictions()
    except Exception as e:
        st.error(t("acc_registry_err", e=e))
        sb = {"total": 0, "open": 0, "resolved": 0, "mean_brier": None, "calibration": []}
        preds = []

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["total"]}</div>'
            f'<div class="metric-label">{t("acc_total")}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["open"]}</div>'
            f'<div class="metric-label">{t("acc_open")}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["resolved"]}</div>'
            f'<div class="metric-label">{t("acc_resolved")}</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        brier_str = f"{sb['mean_brier']:.4f}" if sb['mean_brier'] is not None else "N/A"
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{brier_str}</div>'
            f'<div class="metric-label">{t("acc_brier")}</div></div>',
            unsafe_allow_html=True,
        )

    st.caption(t("acc_brier_note"))

    calibration = sb.get("calibration", [])
    if calibration:
        df_cal = pd.DataFrame(calibration)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[0.5, 1.0], y=[0.5, 1.0],
            mode="lines",
            name="Perfect",
            line=dict(color="#8b949e", dash="dash"),
            hoverinfo="none",
        ))
        fig.add_trace(go.Scatter(
            x=df_cal["avg_confidence"], y=df_cal["actual_hit_rate"],
            mode="markers+lines",
            name="Agent",
            line=dict(color="#58a6ff", width=3),
            marker=dict(size=10, color="#bc8cff", symbol="circle", line=dict(color="#58a6ff", width=2)),
            text=[f"N={row['n']}" for _, row in df_cal.iterrows()],
            hoverinfo="text+x+y",
        ))
        fig.update_layout(
            title=t("acc_title"),
            xaxis_title=t("acc_prob"),
            yaxis_title=t("acc_resolved"),
            xaxis=dict(range=[-0.05, 1.05], gridcolor="#21262d"),
            yaxis=dict(range=[-0.05, 1.05], gridcolor="#21262d"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c9d1d9"),
            height=450,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(t("acc_no_cal"))

    st.markdown("---")
    st.subheader(t("acc_explore"))

    all_label = filter_all_label()
    if preds:
        cat_options = [all_label] + sorted(list(set(p.category for p in preds)))
        selected_cat = st.selectbox(t("acc_filter_cat"), cat_options)

        filtered_preds = preds
        if selected_cat != all_label:
            filtered_preds = [p for p in preds if p.category == selected_cat]

        open_preds = [p for p in filtered_preds if p.status in (Status.open, Status.due)]
        open_preds.sort(key=lambda p: p.confidence, reverse=True)

        resolved_preds = [
            p for p in filtered_preds
            if p.status in (Status.resolved_true, Status.resolved_false)
        ]
        resolved_preds.sort(
            key=lambda p: p.resolved_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        col_active, col_resolved = st.columns(2)
        with col_active:
            st.markdown(f"### {t('acc_active', n=len(open_preds))}")
            if open_preds:
                active_df = pd.DataFrame([{
                    "ID": p.fingerprint(),
                    "Statement": p.statement,
                    "Category": p.category,
                    "Confidence": f"{p.confidence*100:.0f}%",
                    "Horizon": p.horizon,
                    "Resolution": p.resolution_date.strftime("%Y-%m-%d"),
                } for p in open_preds])
                st.dataframe(active_df, use_container_width=True, hide_index=True)
            else:
                st.write(t("acc_no_active"))

        with col_resolved:
            st.markdown(f"### {t('acc_resolved_list', n=len(resolved_preds))}")
            if resolved_preds:
                resolved_df = pd.DataFrame([{
                    "ID": p.fingerprint(),
                    "Statement": p.statement,
                    "Outcome": "TRUE" if p.outcome else "FALSE",
                    "Confidence": f"{p.confidence*100:.0f}%",
                    "Brier": f"{p.brier:.4f}" if p.brier is not None else "",
                    "Rationale": p.judged_rationale,
                } for p in resolved_preds])
                st.dataframe(resolved_df, use_container_width=True, hide_index=True)
            else:
                st.write(t("acc_no_resolved"))
    else:
        st.write(t("acc_no_preds"))

    st.markdown("---")
    st.subheader(t("acc_market_title"))
    st.markdown(t("acc_market_intro"))

    try:
        all_open = [p for p in get_predictions() if p.status in (Status.open, Status.due)]
        if all_open:
            lb = market.leaderboard(top_n=10)
            col_market, col_lb = st.columns([3, 2])

            with col_market:
                st.markdown(f"#### {t('acc_vote_title')}")
                bettor_id = st.text_input(
                    t("acc_bettor"),
                    value="anonymous",
                    key="bettor_id",
                    help=t("acc_bettor_help"),
                )
                pred_labels = {f"{p.statement[:70]}… [{p.horizon}]": p.id for p in all_open}
                chosen_label = st.selectbox(t("acc_choose_pred"), list(pred_labels.keys()))
                chosen_id = pred_labels[chosen_label]

                mkt_prob = market.market_probability(chosen_id)
                n_bets = market.bet_count(chosen_id)
                if mkt_prob is not None:
                    st.markdown(
                        f'<div class="metric-card" style="border-color:#bc8cff;">'
                        f'<div class="metric-value" style="color:#bc8cff;">{mkt_prob*100:.1f}%</div>'
                        f'<div class="metric-label">{t("acc_consensus", n=n_bets)}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                bet_prob = st.slider(
                    t("acc_prob"),
                    min_value=0.01, max_value=0.99, value=0.50, step=0.01,
                    format="%.0f%%",
                    key="bet_prob_slider",
                )
                stake_pts = st.slider(
                    t("acc_stake"),
                    min_value=1, max_value=100, value=10, step=1,
                    key="bet_stake_slider",
                )

                if st.button(t("acc_submit"), key="place_bet_btn", type="primary"):
                    try:
                        market.place_bet(chosen_id, bettor_id, bet_prob, stake_pts)
                        st.success(t("acc_vote_ok", p=bet_prob * 100, s=stake_pts))
                        st.rerun()
                    except Exception as e:
                        st.error(t("acc_market_err", e=e))

            with col_lb:
                st.markdown(f"#### {t('acc_leaderboard')}")
                if lb:
                    lb_df = pd.DataFrame(lb)
                    lb_df.columns = ["Rank", "Contributor", "Points"]
                    st.dataframe(lb_df, use_container_width=True, hide_index=True)
                else:
                    st.info(t("acc_lb_empty"))
        else:
            st.info(t("acc_no_bets"))
    except Exception as e:
        st.error(t("acc_market_err", e=e))
