"""Tab: accuracy — track record with seed vs live origin split (HR-11)."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import market
from schemas import Prediction, Status
from services.dashboard_data import get_predictions, get_track_record_views
from services.track_record import days_until_resolution, prediction_origin, prediction_to_csv_row
from ui.i18n import filter_all_label, prediction_category_label, t


def _brier_str(val) -> str:
    return f"{val:.4f}" if val is not None else "N/A"


def _scoreboard_cards(sb: dict, *, prefix: str) -> None:
    """HTML metric cards — compatible with Streamlit versions that lack st.metric(key=)."""
    del prefix  # panels are in separate sections; no widget key collision
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["total"]}</div>'
            f'<div class="metric-label">{t("acc_total")}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["open"]}</div>'
            f'<div class="metric-label">{t("acc_open")}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{sb["resolved"]}</div>'
            f'<div class="metric-label">{t("acc_resolved")}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        brier_str = _brier_str(sb["mean_brier"])
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{brier_str}</div>'
            f'<div class="metric-label">{t("acc_brier")}</div></div>',
            unsafe_allow_html=True,
        )


def _resolved_table(preds: list[Prediction], origin_label: str) -> None:
    if not preds:
        st.write(t("acc_no_resolved"))
        return
    col_src_key = t("col_sources")
    rows = []
    for p in preds:
        first_src = (p.sources or [])[0] if p.sources else ""
        rows.append({
            t("col_origin"): origin_label,
            t("col_id"): p.fingerprint(),
            t("col_statement"): p.statement,
            t("col_outcome"): t("outcome_true") if p.outcome else t("outcome_false"),
            t("col_confidence"): f"{p.confidence*100:.0f}%",
            t("col_brier"): f"{p.brier:.4f}" if p.brier is not None else "",
            t("col_rationale"): p.judged_rationale,
            col_src_key: first_src,
        })
    st.dataframe(
        pd.DataFrame(rows),
        column_config={
            col_src_key: st.column_config.LinkColumn(
                t("col_sources"),
                display_text=t("col_sources_label"),
            ),
        },
        use_container_width=True,
        hide_index=True,
    )


def _active_table(preds: list[Prediction], origin_label: str) -> None:
    if not preds:
        st.write(t("acc_no_active"))
        return
    st.dataframe(
        pd.DataFrame([{
            t("col_origin"): origin_label,
            t("col_id"): p.fingerprint(),
            t("col_statement"): p.statement,
            t("col_category"): prediction_category_label(p.category),
            t("col_confidence"): f"{p.confidence*100:.0f}%",
            t("col_horizon"): p.horizon,
            t("col_resolution"): p.resolution_date.strftime("%Y-%m-%d"),
        } for p in preds]),
        use_container_width=True,
        hide_index=True,
    )


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader(t("acc_title"))
    st.markdown(t("acc_intro"))
    st.caption(t("acc_origin_note"))

    try:
        views = get_track_record_views()
        seed_preds = views["seed_preds"]
        live_preds = views["live_preds"]
        seed_sb = views["seed_scoreboard"]
        live_sb = views["live_scoreboard"]
        upcoming = views["upcoming_live"]
        seed_ids = views["seed_ids"]
        all_preds = seed_preds + live_preds
        sb_combined = {
            "total": seed_sb["total"] + live_sb["total"],
            "open": seed_sb["open"] + live_sb["open"],
            "resolved": seed_sb["resolved"] + live_sb["resolved"],
            "mean_brier": None,
        }
        all_briers = [
            p.brier for p in all_preds
            if p.brier is not None
        ]
        if all_briers:
            sb_combined["mean_brier"] = round(sum(all_briers) / len(all_briers), 4)
    except Exception as e:
        st.error(t("acc_registry_err", e=e))
        seed_preds, live_preds, upcoming = [], [], []
        seed_sb = live_sb = sb_combined = {
            "total": 0, "open": 0, "resolved": 0, "mean_brier": None, "calibration": [],
        }
        seed_ids = set()
        all_preds = []

    st.markdown(f"### {t('acc_seed_panel')}")
    st.caption(t("acc_seed_explain"))
    _scoreboard_cards(seed_sb, prefix="seed")

    st.markdown(f"### {t('acc_live_panel')}")
    st.caption(t("acc_live_explain"))
    _scoreboard_cards(live_sb, prefix="live")

    st.caption(t("acc_brier_note"))
    with st.expander(t("acc_brier_explain_title"), expanded=False):
        st.markdown(t("acc_brier_explain_body"))

    # Calibration curve uses all resolved predictions
    resolved_all = [
        p for p in all_preds
        if p.status in (Status.resolved_true, Status.resolved_false)
    ]
    if resolved_all:
        from services.track_record import scoreboard_subset
        calibration = scoreboard_subset(resolved_all).get("calibration", [])
    else:
        calibration = []

    if calibration:
        df_cal = pd.DataFrame(calibration)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[0.5, 1.0], y=[0.5, 1.0],
            mode="lines", name="Perfect",
            line=dict(color="#8b949e", dash="dash"), hoverinfo="none",
        ))
        fig.add_trace(go.Scatter(
            x=df_cal["avg_confidence"], y=df_cal["actual_hit_rate"],
            mode="markers+lines", name="Agent",
            line=dict(color="#58a6ff", width=3),
            marker=dict(size=10, color="#bc8cff", symbol="circle",
                        line=dict(color="#58a6ff", width=2)),
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
        st.plotly_chart(fig, width="stretch")
    else:
        st.info(t("acc_no_cal"))

    st.markdown("---")
    st.markdown(f"### {t('acc_upcoming_title')}")
    st.caption(t("acc_upcoming_intro"))
    if upcoming:
        st.dataframe(
            pd.DataFrame([{
                t("col_statement"): p.statement,
                t("col_confidence"): f"{p.confidence*100:.0f}%",
                t("col_resolution"): p.resolution_date.strftime("%Y-%m-%d"),
                t("col_days_left"): days_until_resolution(p),
                t("col_rationale"): p.resolution_criteria[:120],
            } for p in upcoming]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(t("acc_no_upcoming"))

    st.markdown("---")
    st.subheader(t("acc_explore"))

    all_label = filter_all_label()
    if all_preds:
        cat_options = [all_label] + sorted(list(set(p.category for p in all_preds)))
        selected_cat = st.selectbox(
            t("acc_filter_cat"),
            cat_options,
            format_func=lambda c: all_label if c == all_label else prediction_category_label(c),
        )

        def _filter_group(group: list[Prediction]) -> list[Prediction]:
            if selected_cat == all_label:
                return group
            return [p for p in group if p.category == selected_cat]

        seed_f = _filter_group(seed_preds)
        live_f = _filter_group(live_preds)

        seed_resolved = sorted(
            [p for p in seed_f if p.status in (Status.resolved_true, Status.resolved_false)],
            key=lambda p: p.resolved_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        live_resolved = sorted(
            [p for p in live_f if p.status in (Status.resolved_true, Status.resolved_false)],
            key=lambda p: p.resolved_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        live_open = sorted(
            [p for p in live_f if p.status in (Status.open, Status.due)],
            key=lambda p: p.resolution_date,
        )

        st.markdown(f"#### {t('acc_seed_panel')}")
        st.markdown(f"**{t('acc_resolved_list', n=len(seed_resolved))}**")
        _resolved_table(seed_resolved, t("origin_seed"))

        st.markdown(f"#### {t('acc_live_panel')}")
        col_live_open, col_live_res = st.columns(2)
        with col_live_open:
            st.markdown(f"**{t('acc_active', n=len(live_open))}**")
            _active_table(live_open, t("origin_live"))
        with col_live_res:
            st.markdown(f"**{t('acc_resolved_list', n=len(live_resolved))}**")
            _resolved_table(live_resolved, t("origin_live"))
    else:
        st.write(t("acc_no_preds"))

    # ── Public dataset download ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader(t("acc_download_title"))
    st.markdown(t("acc_download_intro"))
    resolved_all_sorted = sorted(
        [p for p in all_preds if p.status in (Status.resolved_true, Status.resolved_false)],
        key=lambda p: p.resolved_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if resolved_all_sorted:
        csv_rows = [
            prediction_to_csv_row(
                p,
                "seed" if prediction_origin(p, seed_ids) == "seed" else "live",
            )
            for p in resolved_all_sorted
        ]
        buf = io.StringIO()
        pd.DataFrame(csv_rows).to_csv(buf, index=False)
        st.download_button(
            label=t("acc_download_btn"),
            data=buf.getvalue().encode("utf-8"),
            file_name="forecaster_track_record.csv",
            mime="text/csv",
        )

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
                    st.dataframe(lb_df, width="stretch", hide_index=True)
                else:
                    st.info(t("acc_lb_empty"))
        else:
            st.info(t("acc_no_bets"))
    except Exception as e:
        st.error(t("acc_market_err", e=e))
