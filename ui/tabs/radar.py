"""Tab: radar."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
import job_radar
import bls_verify
from datetime import datetime, timedelta, timezone
from schemas import JobFeedback
from ui.i18n import (
    EMPLOYMENT_STATUS_CODES,
    INDUSTRY_CODES,
    employment_status_label,
    filter_all_label,
    industry_label,
    job_category_label,
    job_description,
    job_title,
    t,
)


def _risk_badge(imp_val: float) -> str:
    return t("risk_high") if imp_val < -0.3 else t("risk_moderate")


def _opp_badge(imp_val: float) -> str:
    return t("opp_growth") if imp_val >= 0.1 else t("opp_transform")


def _role_status(category: str) -> str:
    if category == "at_risk":
        return t("status_high_disp")
    if category == "transforming":
        return t("status_transforming")
    return t("status_emerging")


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader(t("radar_title"))
    st.markdown(t("radar_intro"))

    # First-visit usage hint
    if not st.session_state.get("_radar_hint_dismissed"):
        col_hint, col_btn = st.columns([10, 2])
        with col_hint:
            st.caption(t("radar_usage_hint"))
        with col_btn:
            if st.button("✕", key="radar_hint_close", help=t("welcome_dismiss")):
                st.session_state["_radar_hint_dismissed"] = True
                st.rerun()

    # Load and score jobs
    kb_path = job_radar_cfg.get("kb_path", "data/jobs_kb.json")
    all_jobs = job_radar.load_knowledge_base(kb_path)

    # Field-feedback calibration: blend real user-submitted outcomes into
    # displacement risk before scoring. No-op when there is no real data yet.
    empirical_data: dict = {}
    try:
        from services.job_market import (
            compute_field_calibration,
            merge_field_calibration_into_jobs,
        )

        empirical_data = job_radar.get_empirical_metrics()
        _field_recs = compute_field_calibration(all_jobs, empirical_data)
        if _field_recs:
            all_jobs = merge_field_calibration_into_jobs(all_jobs, _field_recs)
            total_responses = sum(
                empirical_data.get(jid, {}).get("n_responses", 0)
                for jid in _field_recs
            )
            st.info(
                t(
                    "radar_field_calibrated_badge",
                    n=len(_field_recs),
                    total=total_responses,
                )
            )
        else:
            _field_recs = {}
    except Exception:
        empirical_data = {}
        _field_recs = {}

    if not all_jobs:
        st.warning(t("radar_kb_missing"))
    else:
        # Score jobs based on scenario inputs
        scored_jobs = job_radar.compute_impact_scores(all_jobs, scenario_input)
        
        # Search & Filter Controls
        col_ctrl1, col_ctrl2 = st.columns([2, 1])
        with col_ctrl1:
            search_query = st.text_input(
                t("radar_search"),
                placeholder=t("radar_search_ph"),
            )

        with col_ctrl2:
            industry_options = ["All"] + sorted(list(set(j.get("industry") for j in all_jobs if j.get("industry"))))
            selected_industry = st.selectbox(
                t("radar_industry"),
                industry_options,
                format_func=lambda x: filter_all_label() if x == "All" else industry_label(x),
            )
            
        # Get hybrid score
        alpha = job_radar_cfg.get("alpha", 0.6)
        beta = job_radar_cfg.get("beta", 0.4)
        
        filtered_jobs = job_radar.filter_by_industry(scored_jobs, selected_industry)
        final_jobs = job_radar.get_hybrid_scores(filtered_jobs, search_query, alpha, beta)
        
        # Dynamic KB expansion: if query has no close match, ask LLM to generate a profile
        llm_generated_profile = None
        if search_query:
            best_sim, best_job = job_radar.find_best_match(search_query, final_jobs)
            if best_sim < job_radar._SIMILARITY_THRESHOLD:
                with st.spinner(t("radar_llm_spin", q=search_query)):
                    llm_generated_profile = job_radar.generate_job_profile_via_llm(search_query)
                    if llm_generated_profile:
                        # Score the new profile and add to results
                        new_scored = job_radar.compute_impact_scores([llm_generated_profile], scenario_input)
                        new_hybrid = job_radar.get_hybrid_scores(new_scored, search_query, alpha, beta)
                        # Apply industry filter to LLM result
                        if selected_industry == "All" or llm_generated_profile.get("industry") == selected_industry:
                            final_jobs = new_hybrid + final_jobs
                        # Also add to all_jobs for the rest of the page (UX-2: badge)
                        llm_generated_profile["title"] += " 🤖" + t("radar_ai_badge")
                        all_jobs.append(llm_generated_profile)
                        st.info(t("radar_llm_ok", title=job_title(llm_generated_profile)))
                    else:
                        st.warning(t("radar_llm_fail"))
            elif best_sim < job_radar._STRONG_MATCH_THRESHOLD:
                st.warning(t(
                    "radar_search_weak",
                    title=job_title(best_job),
                    sim=best_sim,
                    q=search_query,
                ))
            else:
                st.success(t(
                    "radar_search_hit",
                    title=job_title(best_job),
                    sim=best_sim,
                    q=search_query,
                ))
            final_jobs.sort(
                key=lambda x: (
                    x.get("combined_similarity", 0.0),
                    x.get("hybrid_score", 0.0),
                ),
                reverse=True,
            )
        # 1. Split into At-Risk and Emerging Opportunities
        at_risk_list = [j for j in final_jobs if j.get("category") == "at_risk"]
        opportunity_list = [j for j in final_jobs if j.get("category") in ("emerging", "transforming")]
        
        # Sort lists properly based on whether a search query is active
        if search_query:
            at_risk_list.sort(
                key=lambda x: (x.get("combined_similarity", 0.0), x.get("hybrid_score", 0.0)),
                reverse=True,
            )
            opportunity_list.sort(
                key=lambda x: (x.get("combined_similarity", 0.0), x.get("hybrid_score", 0.0)),
                reverse=True,
            )
        else:
            # Sort by absolute impact severity
            at_risk_list.sort(key=lambda x: x.get("impact_score", 0.0)) # most negative first
            opportunity_list.sort(key=lambda x: x.get("impact_score", 0.0), reverse=True) # most positive first

        # P2.1 — BLS verification badges (network-optional; returns {} if offline)
        bls_data = bls_verify.compare_kb_to_bls(all_jobs)

        st.markdown("---")
        st.subheader(t("radar_matrix"))

        col_risk, col_opp = st.columns(2)

        with col_risk:
            st.markdown(f"#### {t('radar_at_risk')}")
            if not at_risk_list:
                st.write(t("radar_no_at_risk"))
            else:
                for j in at_risk_list[:5]:
                    imp_val = j["impact_score"]
                    color_style = "color: #ff5555;" if imp_val < -0.3 else "color: #ffaa55;"
                    rating_badge = _risk_badge(imp_val)
                    bls_info = bls_data.get(j.get("id", ""), {})
                    bls_badge = bls_info.get("badge", "")
                    bls_badge_html = f'<span style="font-size:0.75rem;margin-left:8px;">{bls_badge}</span>' if bls_badge else ""
                    title = job_title(j)
                    desc = job_description(j)
                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #442222; background: rgba(30, 15, 15, 0.4);">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h4 style="margin: 0; font-size: 1.1rem; color: #ff8888 !important;">{title} <span style="font-size: 0.85rem; color: #8b949e !important;">({industry_label(j["industry"])})</span>{bls_badge_html}</h4>
                            <span style="font-weight: bold; {color_style}">{rating_badge} ({imp_val:.2f})</span>
                        </div>
                        <p style="font-size: 0.9rem; margin: 0.4rem 0; color: #c9d1d9 !important; line-height: 1.4;">{desc}</p>
                        <div style="font-size: 0.8rem; color: #8b949e !important; padding-top: 0.3rem; border-top: 1px solid #332222;">
                            <strong>{t("lbl_displacement")}:</strong> {j["displacement_risk"] * 100:.0f}%<br>
                            <strong>{t("lbl_skills")}:</strong> {", ".join(j["required_skills"])}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                if len(at_risk_list) > 5:
                    with st.expander(t("radar_more_at_risk", n=len(at_risk_list) - 5)):
                        for j in at_risk_list[5:]:
                            imp_val = j["impact_score"]
                            color_style = "color: #ff5555;" if imp_val < -0.3 else "color: #ffaa55;"
                            rating_badge = _risk_badge(imp_val)
                            st.markdown(f"""
                            <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #30363d;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <h5 style="margin: 0; color: #ff8888 !important;">{job_title(j)} ({industry_label(j["industry"])})</h5>
                                    <span style="font-weight: bold; {color_style}">{rating_badge} ({imp_val:.2f})</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.3rem 0; color: #c9d1d9 !important;">{job_description(j)}</p>
                            </div>
                            """, unsafe_allow_html=True)

        with col_opp:
            st.markdown(f"#### {t('radar_opportunity')}")
            if not opportunity_list:
                st.write(t("radar_no_opp"))
            else:
                for j in opportunity_list[:5]:
                    imp_val = j["impact_score"]
                    color_style = "color: #55ff55;" if imp_val > 0.5 else "color: #58a6ff;"
                    rating_badge = _opp_badge(imp_val)
                    is_ai = job_radar.is_ai_role(j)
                    ai_badge = t("badge_ai") if is_ai else t("badge_non_ai")
                    ai_color = "#bc8cff" if is_ai else "#3fb950"
                    ai_tag_html = f'<span style="font-size:0.65rem; border:1px solid {ai_color}; color:{ai_color} !important; padding:1px 6px; border-radius:10px; margin-left:6px;">{ai_badge}</span>'
                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #224422; background: rgba(15, 30, 15, 0.4);">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h4 style="margin: 0; font-size: 1.1rem; color: #88ff88 !important;">{job_title(j)} <span style="font-size: 0.85rem; color: #8b949e !important;">({industry_label(j["industry"])})</span>{ai_tag_html}</h4>
                            <span style="font-weight: bold; {color_style}">{rating_badge} ({'+' if imp_val >= 0 else ''}{imp_val:.2f})</span>
                        </div>
                        <p style="font-size: 0.9rem; margin: 0.4rem 0; color: #c9d1d9 !important; line-height: 1.4;">{job_description(j)}</p>
                        <div style="font-size: 0.8rem; color: #8b949e !important; padding-top: 0.3rem; border-top: 1px solid #223322;">
                            <strong>{t("lbl_category")}:</strong> {job_category_label(j["category"])}<br>
                            <strong>{t("lbl_skills")}:</strong> {", ".join(j["required_skills"])}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                if len(opportunity_list) > 5:
                    with st.expander(t("radar_more_opp", n=len(opportunity_list) - 5)):
                        for j in opportunity_list[5:]:
                            imp_val = j["impact_score"]
                            color_style = "color: #55ff55;" if imp_val > 0.5 else "color: #58a6ff;"
                            rating_badge = _opp_badge(imp_val)
                            st.markdown(f"""
                            <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #30363d;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <h5 style="margin: 0; color: #88ff88 !important;">{job_title(j)} ({industry_label(j["industry"])})</h5>
                                    <span style="font-weight: bold; {color_style}">{rating_badge} ({'+' if imp_val >= 0 else ''}{imp_val:.2f})</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.3rem 0; color: #c9d1d9 !important;">{job_description(j)}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
        st.markdown("---")
        st.subheader(t("radar_transition"))
        st.markdown(t("radar_transition_help"))

        dropdown_jobs = sorted(all_jobs, key=lambda x: job_title(x))
        job_by_id = {j["id"]: j for j in dropdown_jobs}
        job_ids = [j["id"] for j in dropdown_jobs]

        selected_job_id = st.selectbox(
            t("radar_select_role"),
            job_ids,
            format_func=lambda jid: job_title(job_by_id[jid])
            + " ("
            + industry_label(job_by_id[jid]["industry"])
            + ")",
        )

        current_job_id = selected_job_id
        current_job_obj = job_by_id[selected_job_id]

        if current_job_obj:
            # Display current job stats
            col_curr_lbl, col_curr_desc = st.columns([1, 3])
            with col_curr_lbl:
                status_color = "#ff5555" if current_job_obj["category"] == "at_risk" else ("#ffaa55" if current_job_obj["category"] == "transforming" else "#55ff55")
                status_label = _role_status(current_job_obj["category"])
                st.markdown(f"""
                <div style="background: rgba(22, 27, 34, 0.8); border: 1px solid #30363d; border-radius: 8px; padding: 1rem; text-align: center;">
                    <span style="font-size: 0.8rem; color: #8b949e !important;">{t("radar_role_class")}</span>
                    <h4 style="margin: 0.2rem 0; color: {status_color} !important;">{status_label}</h4>
                    <span style="font-size: 0.8rem; color: #8b949e !important;">{t("radar_baseline_growth")}: {current_job_obj.get("base_demand_trend", 0.0)*100:+.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
            with col_curr_desc:
                st.markdown(f"**{t('radar_role_desc')}:** {job_description(current_job_obj)}")
                st.markdown(f"**{t('radar_skill_tags')}:** " + " ".join([f"`{s}`" for s in current_job_obj["required_skills"]]))
                
            # Transition paths derived live from skill-vector distance,
            # risk reduction and scenario demand (not a static KB list).
            transitions = job_radar.compute_transition_paths(
                current_job_obj, all_jobs, scenario_input, top_k=3
            )
            
            # Empirical metrics for the selected job (reuse the calibration query)
            job_emp = empirical_data.get(current_job_obj["title"])
            
            if job_emp:
                targets = ', '.join([f"<code>{x}</code>" for x in job_emp['top_empirical_targets']]) or t("radar_emp_none")
                st.markdown(f"""
                <div style="background: rgba(188, 140, 255, 0.05); border-left: 4px solid #bc8cff; padding: 12px; margin: 1.2rem 0; border-radius: 4px;">
                    <h5 style="margin: 0; color: #bc8cff !important; font-size: 1.05rem;">{t("radar_empirical", n=job_emp['total_responses'])}</h5>
                    <p style="margin: 6px 0 0 0; font-size: 0.9rem; color: #c9d1d9 !important; line-height: 1.5;">
                        <strong>{t("radar_emp_disp")}:</strong> <span style="color: #ff5555; font-weight: bold;">{job_emp['empirical_displacement_rate']*100:.1f}%</span>
                        ({t("radar_theo_disp")}: {current_job_obj['displacement_risk']*100:.0f}%) <br>
                        <strong>{t("radar_emp_conf")}:</strong> <span style="color: #58a6ff; font-weight: bold;">{job_emp['average_confidence']*100:.1f}%</span> <br>
                        <strong>{t("radar_emp_targets")}:</strong> {targets}
                    </p>
                </div>
                """, unsafe_allow_html=True)

            # Transparency: show when field feedback actually moved the risk number.
            fc = current_job_obj.get("field_calibration")
            if fc:
                st.caption(t(
                    "radar_field_calibrated",
                    n=fc["n_responses"],
                    base=fc["displacement_risk_base"] * 100,
                    cal=fc["displacement_risk_calibrated"] * 100,
                ))

            st.markdown(f"<br><b>{t('radar_trans_paths')}:</b>", unsafe_allow_html=True)
            st.caption(t("radar_trans_method"))

            col_trans_cards = st.columns(3)
            for idx, tr in enumerate(transitions[:3]):
                with col_trans_cards[idx]:
                    demand = tr.get("demand_outlook", 0.0)
                    demand_color = "#55ff55" if demand > 0 else "#ff5555"
                    cat_badge = t("status_emerging") if tr["category"] == "emerging" else t("status_transforming")
                    ai_badge = t("badge_ai") if tr.get("is_ai") else t("badge_non_ai")
                    ai_color = "#bc8cff" if tr.get("is_ai") else "#3fb950"
                    tr_title = job_title(tr)
                    tr_desc = job_description(tr)

                    # Reasoning signals — all model-derived
                    cur_risk = (tr.get("current_displacement_risk") or 0.0) * 100
                    tgt_risk = (tr.get("target_displacement_risk") or 0.0) * 100
                    proximity = tr.get("skill_proximity", 0.0) * 100
                    rationale_bits = [t("rationale_skill_match", pct=proximity)]
                    if tgt_risk < cur_risk:
                        rationale_bits.append(t("rationale_low_risk", frm=cur_risk, to=tgt_risk))
                    rationale_bits.append(t("rationale_theory"))
                    rationale_html = "; ".join(rationale_bits)

                    bridge_skills = tr.get("skill_bridge_skills") or tr.get("required_skills_preview", [])
                    bridge_html = ", ".join(bridge_skills) if bridge_skills else "—"
                    match_pct = tr.get("transition_score", 0.0) * 100

                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; height: 100%; border-color: #30363d;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-size: 0.75rem; background: #1f2328; padding: 2px 6px; border-radius: 4px; color: #8b949e !important;">{cat_badge} · {industry_label(tr["industry"])}</span>
                            <span style="font-size: 0.85rem; font-weight: bold; color: #58a6ff !important;">{t("lbl_match_score")}: {match_pct:.0f}%</span>
                        </div>
                        <div style="margin-bottom: 0.4rem;">
                            <span style="font-size: 0.7rem; background: rgba(255,255,255,0.05); border: 1px solid {ai_color}; color: {ai_color} !important; padding: 1px 6px; border-radius: 10px;">{ai_badge}</span>
                        </div>
                        <h4 style="margin-top: 0; color: #58a6ff !important; font-size: 1.1rem;">{tr_title}</h4>
                        <p style="font-size: 0.85rem; color: #c9d1d9 !important; line-height: 1.4; min-height: 50px;">{tr_desc}</p>
                        <div style="background: rgba(63, 185, 80, 0.06); border-left: 2px solid #3fb950; padding: 6px 10px; margin-bottom: 0.6rem; font-size: 0.78rem; color: #f0f6fc !important;">
                            <strong>{t("lbl_rationale")}:</strong> {rationale_html}
                        </div>
                        <div style="background: rgba(88, 166, 255, 0.05); border-left: 2px solid #58a6ff; padding: 6px 10px; margin-bottom: 0.8rem; font-size: 0.8rem; color: #f0f6fc !important;">
                            <strong>{t("lbl_skill_bridge")}:</strong> {bridge_html}
                        </div>
                        <div style="font-size: 0.8rem; color: #8b949e !important; border-top: 1px solid #21262d; padding-top: 0.5rem; display: flex; justify-content: space-between;">
                            <span>{t("lbl_demand_outlook")}: <strong style="color: {demand_color};">{demand:+.2f}</strong></span>
                            <span>{t("lbl_retrain")}: <strong style="color: #bc8cff;">{tr["retrain_months"]} {t("lbl_months")}</strong></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader(t("radar_timeline"))
        st.markdown(t("radar_timeline_help"))

        timeline_data = job_radar.compute_timeline(scored_jobs, scenario_input.get("diffusion_years", 10.0))

        if timeline_data:
            df_timeline = pd.DataFrame([{
                "Job Title": job_title(row),
                "Projected Emergence Year": row["projected_emergence_year"],
                "Opportunity Score": max(0.01, row["impact_score"]),
                "Industry": industry_label(row["industry"]),
            } for row in timeline_data])
            
            # Scatter plot for timeline
            fig_timeline = px.scatter(
                df_timeline,
                x="Projected Emergence Year",
                y="Job Title",
                color="Industry",
                size="Opportunity Score",
                title=t("radar_timeline"),
                hover_data=["Projected Emergence Year", "Opportunity Score"],
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            
            fig_timeline.update_layout(
                xaxis=dict(
                    title='Projected Emergence Year',
                    gridcolor='#21262d',
                    dtick=1,
                    tickformat="d"
                ),
                yaxis=dict(title='', gridcolor='#21262d'),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#c9d1d9'),
                height=450,
                margin=dict(l=40, r=40, t=60, b=40)
            )
            st.plotly_chart(fig_timeline, width="stretch")
            
            st.caption(t("radar_timeline_note"))
        else:
            st.write(t("radar_timeline_empty"))

        st.markdown("---")
        st.subheader(t("radar_survey"))
        st.markdown(t("radar_survey_help"))

        none_lbl = t("filter_none")
        with st.form("job_feedback_form", clear_on_submit=True):
            col_f1, col_f2 = st.columns(2)
            # Map localized labels back to canonical English titles so saved
            # feedback keys match get_empirical_metrics() (which groups by title).
            title_by_label = {}
            for j in all_jobs:
                title_by_label.setdefault(job_title(j), j.get("title", job_title(j)))
            sorted_labels = sorted(title_by_label.keys())
            with col_f1:
                fb_job_label = st.selectbox(
                    t("radar_fb_job"),
                    sorted_labels,
                )
                fb_job = title_by_label[fb_job_label]
                fb_industry = st.selectbox(
                    t("radar_fb_industry"),
                    list(INDUSTRY_CODES),
                    format_func=industry_label,
                )
                fb_company = st.text_input(t("radar_fb_company"))
                fb_email = st.text_input(
                    t("radar_fb_email"),
                    placeholder="you@example.com",
                    help=t("radar_fb_email_help"),
                )
            with col_f2:
                fb_status = st.selectbox(
                    t("radar_fb_status"),
                    list(EMPLOYMENT_STATUS_CODES),
                    format_func=employment_status_label,
                )
                fb_confidence = st.slider(
                    t("radar_fb_confidence"), min_value=0, max_value=100, value=50,
                ) / 100.0
                fb_target_label = st.selectbox(
                    t("radar_fb_target"),
                    [none_lbl] + sorted_labels,
                )
                fb_target = (
                    none_lbl if fb_target_label == none_lbl
                    else title_by_label[fb_target_label]
                )

            submit_btn = st.form_submit_button(t("radar_fb_submit"))
            if submit_btn:
                from datetime import timedelta
                import re
                email_val = fb_email.strip() if fb_email and re.match(r"[^@]+@[^@]+\.[^@]+", fb_email) else None
                feedback_obj = JobFeedback(
                    job_title=fb_job,
                    industry=fb_industry,
                    company=fb_company if fb_company else None,
                    status=fb_status,
                    confidence=fb_confidence,
                    transition_target=fb_target if fb_target != none_lbl else None,
                    email=email_val,
                    follow_up_due_at=datetime.now(timezone.utc) + timedelta(days=180) if email_val else None,
                )
                job_radar.save_job_feedback(feedback_obj)
                if email_val:
                    st.success(t("radar_fb_ok_email"))
                else:
                    st.success(t("radar_fb_ok"))

        st.markdown("---")
        with st.expander(t("radar_sources")):
            st.markdown(t("radar_sources_intro"))
            for j in all_jobs:
                st.markdown(f"**{job_title(j)} ({industry_label(j['industry'])}):**")
                for s in j.get("sources", []):
                    st.markdown(f"- {s}")
