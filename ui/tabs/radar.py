"""Tab: radar."""
from __future__ import annotations

import streamlit as st
import job_radar
import bls_verify
from datetime import datetime, timedelta, timezone
from schemas import JobFeedback


def render(scenario_input: dict, prior, job_radar_cfg: dict):
    st.subheader("🎯 Job Forecast Radar — Occupation Impact & Career Transition Analyst")
    st.markdown("""
    👋 **Welcome to JobForecast Agent!** 
    We use advanced economic models and autonomous AI to predict how AI automation will transform different careers. 

    👉 **How to use:** Enter your job title in the search box below (e.g., *Financial Analyst*, *Software Engineer*, *Tax preparer*) to see if the job is at risk, how it will change, what skills you need, and what transition paths are available.

    *(For technical users: This runs on a Lightweight Hybrid RAG architecture combining structured causal-variable filtering with semantic similarity search.)*
    """)

    # Load and score jobs
    kb_path = job_radar_cfg.get("kb_path", "data/jobs_kb.json")
    all_jobs = job_radar.load_knowledge_base(kb_path)

    if not all_jobs:
        st.warning("⚠️ Job knowledge base could not be loaded. Please ensure `data/jobs_kb.json` exists.")
    else:
        # Score jobs based on scenario inputs
        scored_jobs = job_radar.compute_impact_scores(all_jobs, scenario_input)
        
        # Search & Filter Controls
        col_ctrl1, col_ctrl2 = st.columns([2, 1])
        with col_ctrl1:
            search_query = st.text_input("🔍 Search Jobs or Skills (Semantic Similarity)", placeholder="e.g. Finance Process Improvement...")
                
        with col_ctrl2:
            industry_options = ["All"] + sorted(list(set(j.get("industry") for j in all_jobs if j.get("industry"))))
            selected_industry = st.selectbox("🏢 Filter by Industry", industry_options)
            
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
                with st.spinner(f"🧠 '{search_query}' not found in KB — generating profile via AI..."):
                    llm_generated_profile = job_radar.generate_job_profile_via_llm(search_query)
                    if llm_generated_profile:
                        # Score the new profile and add to results
                        new_scored = job_radar.compute_impact_scores([llm_generated_profile], scenario_input)
                        new_hybrid = job_radar.get_hybrid_scores(new_scored, search_query, alpha, beta)
                        # Apply industry filter to LLM result
                        if selected_industry == "All" or llm_generated_profile.get("industry") == selected_industry:
                            final_jobs = new_hybrid + final_jobs
                        # Also add to all_jobs for the rest of the page (UX-2: badge)
                        llm_generated_profile["title"] += " 🤖 (AI-Generated Estimate)"
                        all_jobs.append(llm_generated_profile)
                        st.info(f"✨ **New profile generated:** '{llm_generated_profile.get('title', search_query)}' has been added to the Knowledge Base via LLM analysis.")
                    else:
                        st.warning("⚠️ Could not generate a profile for this role. Check that an LLM API key is configured (GROQ_API_KEY or ANTHROPIC_API_KEY).")
            else:
                st.success(f"🎯 **Search Active:** Best match '{best_job.get('title', '')}' (similarity: {best_sim:.2f}) — sorted by semantic relevance to '{search_query}'")
            final_jobs.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
        # 1. Split into At-Risk and Emerging Opportunities
        at_risk_list = [j for j in final_jobs if j.get("category") == "at_risk"]
        opportunity_list = [j for j in final_jobs if j.get("category") in ("emerging", "transforming")]
        
        # Sort lists properly based on whether a search query is active
        if search_query:
            # Keep sorted by semantic similarity (hybrid_score)
            at_risk_list.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
            opportunity_list.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
        else:
            # Sort by absolute impact severity
            at_risk_list.sort(key=lambda x: x.get("impact_score", 0.0)) # most negative first
            opportunity_list.sort(key=lambda x: x.get("impact_score", 0.0), reverse=True) # most positive first

        # P2.1 — BLS verification badges (network-optional; returns {} if offline)
        bls_data = bls_verify.compare_kb_to_bls(all_jobs)

        st.markdown("---")
        st.subheader("📊 Occupation Impact Matrix")
        
        col_risk, col_opp = st.columns(2)
        
        with col_risk:
            st.markdown("#### 🔴 At-Risk & Transforming Roles")
            if not at_risk_list:
                st.write("No at-risk roles match the current filters.")
            else:
                for j in at_risk_list[:5]: # Show top 5
                    imp_val = j["impact_score"]
                    color_style = "color: #ff5555;" if imp_val < -0.3 else "color: #ffaa55;"
                    rating_badge = "🔴 High Risk" if imp_val < -0.3 else "🟠 Moderate Risk"
                    bls_info = bls_data.get(j.get("id", ""), {})
                    bls_badge = bls_info.get("badge", "")
                    bls_badge_html = f'<span style="font-size:0.75rem;margin-left:8px;">{bls_badge}</span>' if bls_badge else ""
                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #442222; background: rgba(30, 15, 15, 0.4);">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h4 style="margin: 0; font-size: 1.1rem; color: #ff8888 !important;">{j["title"]} <span style="font-size: 0.85rem; color: #8b949e !important;">({j["industry"]})</span>{bls_badge_html}</h4>
                            <span style="font-weight: bold; {color_style}">{rating_badge} ({imp_val:.2f})</span>
                        </div>
                        <p style="font-size: 0.9rem; margin: 0.4rem 0; color: #c9d1d9 !important; line-height: 1.4;">{j["description"]}</p>
                        <div style="font-size: 0.8rem; color: #8b949e !important; padding-top: 0.3rem; border-top: 1px solid #332222;">
                            <strong>Displacement Risk:</strong> {j["displacement_risk"] * 100:.0f}%<br>
                            <strong>Key Skills:</strong> {", ".join(j["required_skills"])}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                if len(at_risk_list) > 5:
                    with st.expander(f"View {len(at_risk_list) - 5} more at-risk roles"):
                        for j in at_risk_list[5:]:
                            imp_val = j["impact_score"]
                            color_style = "color: #ff5555;" if imp_val < -0.3 else "color: #ffaa55;"
                            rating_badge = "🔴 High Risk" if imp_val < -0.3 else "🟠 Moderate Risk"
                            st.markdown(f"""
                            <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #30363d;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <h5 style="margin: 0; color: #ff8888 !important;">{j["title"]} ({j["industry"]})</h5>
                                    <span style="font-weight: bold; {color_style}">{rating_badge} ({imp_val:.2f})</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.3rem 0; color: #c9d1d9 !important;">{j["description"]}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
        with col_opp:
            st.markdown("#### 🟢 Emerging & High-Opportunity Roles")
            if not opportunity_list:
                st.write("No opportunity roles match the current filters.")
            else:
                for j in opportunity_list[:5]: # Show top 5
                    imp_val = j["impact_score"]
                    color_style = "color: #55ff55;" if imp_val > 0.5 else "color: #58a6ff;"
                    rating_badge = "🟢 Growth Opp" if imp_val >= 0.1 else "🟡 Transforming"
                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #224422; background: rgba(15, 30, 15, 0.4);">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h4 style="margin: 0; font-size: 1.1rem; color: #88ff88 !important;">{j["title"]} <span style="font-size: 0.85rem; color: #8b949e !important;">({j["industry"]})</span></h4>
                            <span style="font-weight: bold; {color_style}">{rating_badge} ({'+' if imp_val >= 0 else ''}{imp_val:.2f})</span>
                        </div>
                        <p style="font-size: 0.9rem; margin: 0.4rem 0; color: #c9d1d9 !important; line-height: 1.4;">{j["description"]}</p>
                        <div style="font-size: 0.8rem; color: #8b949e !important; padding-top: 0.3rem; border-top: 1px solid #223322;">
                            <strong>Role Category:</strong> {j["category"].upper()}<br>
                            <strong>Key Skills:</strong> {", ".join(j["required_skills"])}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                if len(opportunity_list) > 5:
                    with st.expander(f"View {len(opportunity_list) - 5} more opportunity roles"):
                        for j in opportunity_list[5:]:
                            imp_val = j["impact_score"]
                            color_style = "color: #55ff55;" if imp_val > 0.5 else "color: #58a6ff;"
                            rating_badge = "🟢 Growth Opp" if imp_val >= 0.1 else "🟡 Transforming"
                            st.markdown(f"""
                            <div class="metric-card" style="text-align: left; margin-bottom: 0.8rem; border-color: #30363d;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <h5 style="margin: 0; color: #88ff88 !important;">{j["title"]} ({j["industry"]})</h5>
                                    <span style="font-weight: bold; {color_style}">{rating_badge} ({'+' if imp_val >= 0 else ''}{imp_val:.2f})</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.3rem 0; color: #c9d1d9 !important;">{j["description"]}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
        # 2. Transition Explorer
        st.markdown("---")
        st.subheader("🔄 Career Transition Path Explorer (职业转型路径探索)")
        st.markdown("""
        Select your current role below. The system will compare your current skill set with other occupations and recommend the best career transition paths that require the least amount of retraining, along with the specific skills you need to build (the "skill bridge").
        """)
        
        # Sort jobs alphabetically by English title for dropdown
        dropdown_jobs = sorted(all_jobs, key=lambda x: x["title"])
        job_options = [j["title"] + " (" + j["industry"] + ")" for j in dropdown_jobs]
        
        selected_job_label = st.selectbox("🎯 Select your current role:", job_options)
        
        # Find ID of selected job
        current_job_id = None
        current_job_obj = None
        for j in all_jobs:
            if j["title"] + " (" + j["industry"] + ")" == selected_job_label:
                current_job_id = j["id"]
                current_job_obj = j
                break
                
        if current_job_obj:
            # Display current job stats
            col_curr_lbl, col_curr_desc = st.columns([1, 3])
            with col_curr_lbl:
                status_color = "#ff5555" if current_job_obj["category"] == "at_risk" else ("#ffaa55" if current_job_obj["category"] == "transforming" else "#55ff55")
                status_label = "High Displacement Risk" if current_job_obj["category"] == "at_risk" else ("Transforming" if current_job_obj["category"] == "transforming" else "Emerging Opportunity")
                st.markdown(f"""
                <div style="background: rgba(22, 27, 34, 0.8); border: 1px solid #30363d; border-radius: 8px; padding: 1rem; text-align: center;">
                    <span style="font-size: 0.8rem; color: #8b949e !important;">Role Classification</span>
                    <h4 style="margin: 0.2rem 0; color: {status_color} !important;">{status_label}</h4>
                    <span style="font-size: 0.8rem; color: #8b949e !important;">Baseline Growth: {current_job_obj["base_demand_trend"]*100:+.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
            with col_curr_desc:
                st.markdown(f"**Role Description:** {current_job_obj['description']}")
                st.markdown(f"**Key Skill Tags:** " + " ".join([f"`{s}`" for s in current_job_obj["required_skills"]]))
                
            # Get transitions
            transitions = job_radar.get_transition_details(current_job_id, all_jobs)
            
            # Load empirical metrics for the selected job
            empirical_data = job_radar.get_empirical_metrics()
            job_emp = empirical_data.get(current_job_obj["title"])
            
            if job_emp:
                st.markdown(f"""
                <div style="background: rgba(188, 140, 255, 0.05); border-left: 4px solid #bc8cff; padding: 12px; margin: 1.2rem 0; border-radius: 4px;">
                    <h5 style="margin: 0; color: #bc8cff !important; font-size: 1.05rem;">👥 Empirical Crowd Feedback (N = {job_emp['total_responses']} responses)</h5>
                    <p style="margin: 6px 0 0 0; font-size: 0.9rem; color: #c9d1d9 !important; line-height: 1.5;">
                        <strong>Empirical Displacement Rate:</strong> <span style="color: #ff5555; font-weight: bold;">{job_emp['empirical_displacement_rate']*100:.1f}%</span> 
                        (vs Theoretical Displacement Risk: {current_job_obj['displacement_risk']*100:.0f}%) <br>
                        <strong>Average Worker Confidence:</strong> <span style="color: #58a6ff; font-weight: bold;">{job_emp['average_confidence']*100:.1f}%</span> <br>
                        <strong>Top Crowd-reported Transition Targets:</strong> {', '.join([f"<code>{t}</code>" for t in job_emp['top_empirical_targets']]) if job_emp['top_empirical_targets'] else 'None reported yet.'}
                    </p>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("<br><b>💡 Recommended Transition Paths:</b>", unsafe_allow_html=True)
            
            col_trans_cards = st.columns(3)
            for idx, t in enumerate(transitions[:3]):
                with col_trans_cards[idx]:
                    salary_color = "#55ff55" if t["salary_delta"] > 0 else "#ff5555"
                    cat_badge = "🟢 Emerging" if t["category"] == "emerging" else "🟡 Transforming"
                    
                    st.markdown(f"""
                    <div class="metric-card" style="text-align: left; height: 100%; border-color: #30363d;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-size: 0.75rem; background: #1f2328; padding: 2px 6px; border-radius: 4px; color: #8b949e !important;">{cat_badge} · {t["industry"]}</span>
                            <span style="font-size: 0.9rem; font-weight: bold; color: {salary_color} !important;">Salary: {t["salary_delta"]*100:+.0f}%</span>
                        </div>
                        <h4 style="margin-top: 0; color: #58a6ff !important; font-size: 1.1rem;">{t["title"]}</h4>
                        <p style="font-size: 0.85rem; color: #c9d1d9 !important; line-height: 1.4; min-height: 50px;">{t["description"]}</p>
                        <div style="background: rgba(88, 166, 255, 0.05); border-left: 2px solid #58a6ff; padding: 6px 10px; margin-bottom: 0.8rem; font-size: 0.8rem; color: #f0f6fc !important;">
                            <strong>Skill Bridge:</strong> Develop proficiency in {', '.join(t.get('required_skills_preview', [t['title']]))}
                        </div>
                        <div style="font-size: 0.8rem; color: #8b949e !important; border-top: 1px solid #21262d; padding-top: 0.5rem; text-align: right;">
                            ⏱️ Est. retraining: <strong style="color: #bc8cff;">{t["retrain_months"]} months</strong>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
        # 3. Timeline
        st.markdown("---")
        st.subheader("📅 Emerging Occupations Timeline")
        st.markdown("Projected emergence years for new roles, dynamically scaled by the `Diffusion Years` parameter in the left sidebar.")
        
        timeline_data = job_radar.compute_timeline(scored_jobs, scenario_input.get("diffusion_years", 10.0))
        
        if timeline_data:
            df_timeline = pd.DataFrame([{
                "Job Title": t["title"],
                "Projected Emergence Year": t["projected_emergence_year"],
                "Opportunity Score": max(0.01, t["impact_score"]),
                "Industry": t["industry"]
            } for t in timeline_data])
            
            # Scatter plot for timeline
            fig_timeline = px.scatter(
                df_timeline,
                x="Projected Emergence Year",
                y="Job Title",
                color="Industry",
                size="Opportunity Score",
                title="Emerging Roles — Projected Scale Adoption Timeline",
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
            st.plotly_chart(fig_timeline, use_container_width=True)
            
            st.markdown("""
            *Timeline logic: Baseline AI diffusion speed = 10 years. Reducing `Diffusion Years` in the sidebar accelerates adoption, pulling emergence years forward; increasing it delays them.*
            """)
        else:
            st.write("No emerging roles available for timeline projection.")

        # 3.5 Crowd-sourced Transition Survey Form
        st.markdown("---")
        st.subheader("👥 Crowd-sourced Career Transition Survey")
        st.markdown(
            "Help calibrate our predictions! Share your employment status, confidence, and "
            "transition goals to correct our theoretical AI displacement models. "
            "**Optional:** leave your email to receive a 6-month follow-up — "
            "your outcome data directly improves prediction accuracy."
        )

        with st.form("job_feedback_form", clear_on_submit=True):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                fb_job = st.selectbox("Your current or most recent job title:", sorted(list(set(j["title"] for j in all_jobs))))
                fb_industry = st.selectbox("Industry:", ["Finance", "Tech", "Manufacturing", "Healthcare", "Education", "Legal", "Logistics", "Retail", "Agriculture", "Construction", "Hospitality", "Government", "Media"])
                fb_company = st.text_input("Company name (optional):")
                fb_email = st.text_input(
                    "Email for 6-month follow-up (optional):",
                    placeholder="you@example.com",
                    help="We will ask in 6 months whether your transition succeeded. Never shared or sold."
                )
            with col_f2:
                fb_status = st.selectbox("Employment status:", ["Employed", "Unemployed", "Transitioning"])
                fb_confidence = st.slider("Job security confidence (0 = extremely worried, 100 = completely secure):", min_value=0, max_value=100, value=50) / 100.0
                fb_target = st.selectbox("If transitioning, what is your target role?", ["None"] + sorted(list(set(j["title"] for j in all_jobs))))

            submit_btn = st.form_submit_button("Submit Survey Response")
            if submit_btn:
                from schemas import JobFeedback
                from datetime import timedelta
                import re
                email_val = fb_email.strip() if fb_email and re.match(r"[^@]+@[^@]+\.[^@]+", fb_email) else None
                feedback_obj = JobFeedback(
                    job_title=fb_job,
                    industry=fb_industry,
                    company=fb_company if fb_company else None,
                    status=fb_status.lower(),
                    confidence=fb_confidence,
                    transition_target=fb_target if fb_target != "None" else None,
                    email=email_val,
                    follow_up_due_at=datetime.now(timezone.utc) + timedelta(days=180) if email_val else None,
                )
                job_radar.save_job_feedback(feedback_obj)
                if email_val:
                    st.success("Thank you! Your response has been submitted. We will follow up in 6 months to see how your transition went.")
                else:
                    st.success("Thank you! Your response has been submitted and will calibrate the empirical models.")


        # 4. HR-7 Compliance Citations Drawer
        st.markdown("---")
        with st.expander("📚 Data Sources & Authoritative Citations (HR-7 Compliance)"):
            st.markdown("""
            All occupation profiles and displacement risk estimates reference the following authoritative labour market research databases and publications:
            """)
            for j in all_jobs:
                st.markdown(f"**{j['title']} ({j['industry']}):**")
                for s in j.get("sources", []):
                    st.markdown(f"- 📖 *{s}*")
