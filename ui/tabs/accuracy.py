"""Tab: accuracy."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

import streamlit as st
from services.dashboard_data import get_predictions, get_scoreboard_data
import market
from schemas import Status


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader("📈 Forecast Accuracy Tracker")
    st.markdown("""
    Tracks how well our AI's forecasts align with real-world outcomes over time. The **Reliability Curve** compares predicted probability (confidence) with actual outcome frequency. Lower **Mean Brier Score** indicates higher prediction accuracy.
    """)
    try:
        sb = get_scoreboard_data()
        preds = get_predictions()
    except Exception as e:
        st.error(f"Error loading registry: {e}")
        sb = {"total": 0, "open": 0, "resolved": 0, "mean_brier": None, "calibration": []}
        preds = []

    # Display KPI Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{sb["total"]}</div><div class="metric-label">Total Predictions</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{sb["open"]}</div><div class="metric-label">Active / Open</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{sb["resolved"]}</div><div class="metric-label">Resolved</div></div>', unsafe_allow_html=True)
    with col4:
        brier_str = f"{sb['mean_brier']:.4f}" if sb['mean_brier'] is not None else "N/A"
        st.markdown(f'<div class="metric-card"><div class="metric-value">{brier_str}</div><div class="metric-label">Prediction Deviation (Brier Score)</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("💡 *Note: Brier Score measures forecast error. 0.0000 is perfect accuracy (zero error), and 0.2500 is equivalent to random guessing.*")

    # Reliability curve
    calibration = sb.get("calibration", [])
    if calibration:
        df_cal = pd.DataFrame(calibration)
        
        # Plotly Reliability Curve
        fig = go.Figure()
        
        # Perfect calibration diagonal
        fig.add_trace(go.Scatter(
            x=[0.5, 1.0], y=[0.5, 1.0],
            mode='lines',
            name='Perfect Calibration',
            line=dict(color='#8b949e', dash='dash'),
            hoverinfo='none'
        ))
        
        # Actual calibration curve
        fig.add_trace(go.Scatter(
            x=df_cal['avg_confidence'], y=df_cal['actual_hit_rate'],
            mode='markers+lines',
            name='Agent Calibration',
            line=dict(color='#58a6ff', width=3),
            marker=dict(size=10, color='#bc8cff', symbol='circle', line=dict(color='#58a6ff', width=2)),
            text=[f"Bucket: {row['bucket']}<br>Sample size (N): {row['n']}" for _, row in df_cal.iterrows()],
            hoverinfo='text+x+y'
        ))
        
        fig.update_layout(
            title="Reliability Curve (Predicted Confidence vs Actual Accuracy)",
            xaxis_title="Average Predicted Probability (Confidence)",
            yaxis_title="Observed Frequency (Actual Hit Rate)",
            xaxis=dict(range=[-0.05, 1.05], gridcolor='#21262d'),
            yaxis=dict(range=[-0.05, 1.05], gridcolor='#21262d'),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#c9d1d9'),
            height=450,
            margin=dict(l=40, r=40, t=60, b=40),
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No calibration data available. Ensure there are resolved predictions in the registry.")
    st.markdown("---")
    st.subheader("🔍 Explore Predictions")

    if preds:
        cat_options = ["All"] + sorted(list(set(p.category for p in preds)))
        selected_cat = st.selectbox("Filter by Category", cat_options)

        filtered_preds = preds
        if selected_cat != "All":
            filtered_preds = [p for p in preds if p.category == selected_cat]

        open_preds = [p for p in filtered_preds if p.status in (Status.open, Status.due)]
        open_preds.sort(key=lambda p: p.confidence, reverse=True)

        resolved_preds = [p for p in filtered_preds if p.status in (Status.resolved_true, Status.resolved_false)]
        resolved_preds.sort(key=lambda p: p.resolved_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        col_active, col_resolved = st.columns(2)
        with col_active:
            st.markdown(f"### 🏃\u200d♂️ Active Predictions ({len(open_preds)})")
            if open_preds:
                active_df = pd.DataFrame([{
                    "ID": p.fingerprint(),
                    "Statement": p.statement,
                    "Category": p.category,
                    "Confidence": f"{p.confidence*100:.0f}%",
                    "Horizon": p.horizon,
                    "Resolution Date": p.resolution_date.strftime("%Y-%m-%d")
                } for p in open_preds])
                st.dataframe(active_df, use_container_width=True, hide_index=True)
            else:
                st.write("No active predictions in this category.")

        with col_resolved:
            st.markdown(f"### 🏆 Resolved Predictions ({len(resolved_preds)})")
            if resolved_preds:
                resolved_df = pd.DataFrame([{
                    "ID": p.fingerprint(),
                    "Statement": p.statement,
                    "Outcome": "✅ TRUE" if p.outcome else "❌ FALSE",
                    "Confidence": f"{p.confidence*100:.0f}%",
                    "Brier": f"{p.brier:.4f}" if p.brier is not None else "",
                    "Judged Rationale": p.judged_rationale
                } for p in resolved_preds])
                st.dataframe(resolved_df, use_container_width=True, hide_index=True)
            else:
                st.write("No resolved predictions in this category.")
    else:
        st.write("No predictions loaded in the registry database.")

    # ── P3: Prediction Market ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🎲 Crowd Consensus & Prediction Competition (预测市场竞猜)")
    st.markdown("""
    **What is this?**
    Here you can challenge or support the AI's forecasts by casting your vote (placing a "bet" with virtual points).

    *   **Crowd Wisdom (群体智慧):** The **Consensus Probability** represents the combined judgment of all human forecasters and the AI. Combined crowd consensus is statistically proven to be more accurate than any single AI or human expert.
    *   **How to participate:** Select an active prediction, estimate the probability of it happening (0% to 100%), and stake virtual points.
    *   **Rewards & Leaderboard:** When the forecast target date is reached and outcomes are verified in the real world, points are distributed. Accurately calibrated predictions yield higher scores. Top forecasters rise on the leaderboard!
    """)

    try:
        all_open = [p for p in get_predictions() if p.status in (Status.open, Status.due)]
        if all_open:
            lb = market.leaderboard(top_n=10)
            col_market, col_lb = st.columns([3, 2])

            with col_market:
                st.markdown("#### 🗳️ Submit Your Forecast Vote (参与预测下注)")
                bettor_id = st.text_input(
                    "Your Nickname / Forecaster Name (你的竞猜昵称):",
                    value="anonymous",
                    key="bettor_id",
                    help="Used for the leaderboard. Does not need to be real."
                )
                pred_labels = {f"{p.statement[:70]}… [{p.horizon}]": p.id for p in all_open}
                chosen_label = st.selectbox("Choose a forecast statement to vote on (选择你要研判的预测):", list(pred_labels.keys()))
                chosen_id = pred_labels[chosen_label]

                mkt_prob = market.market_probability(chosen_id)
                n_bets = market.bet_count(chosen_id)
                if mkt_prob is not None:
                    st.markdown(
                        f'<div class="metric-card" style="border-color:#bc8cff;">'
                        f'<div class="metric-value" style="color:#bc8cff;">{mkt_prob*100:.1f}%</div>'
                        f'<div class="metric-label">Market Consensus Probability (共识成真概率, {n_bets} votes)</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                bet_prob = st.slider(
                    "Your estimate of probability this event will happen (你认为该事件成真的概率):",
                    min_value=0.01, max_value=0.99, value=0.50, step=0.01,
                    format="%.0f%%",
                    key="bet_prob_slider"
                )
                stake_pts = st.slider(
                    "Stake amount (Virtual Points) / 下注筹码 (虚拟积分):",
                    min_value=1, max_value=100, value=10, step=1,
                    key="bet_stake_slider"
                )

                if st.button("🎲 Submit Vote / 提交预测", key="place_bet_btn", type="primary"):
                    try:
                        market.place_bet(chosen_id, bettor_id, bet_prob, stake_pts)
                        st.success(f"Vote submitted successfully! Your estimate is {bet_prob*100:.0f}% probability, staking {stake_pts} points.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Bet failed: {e}")

            with col_lb:
                st.markdown("#### 🏅 Leaderboard")
                if lb:
                    lb_df = pd.DataFrame(lb)
                    lb_df.columns = ["Rank", "Contributor", "Points"]
                    st.dataframe(lb_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No settled predictions yet. Points will be distributed when predictions reach their horizon dates and real-world outcomes are verified.")
        else:
            st.info("No open predictions available for betting right now.")
    except Exception as e:
        st.error(f"Market error: {e}")
