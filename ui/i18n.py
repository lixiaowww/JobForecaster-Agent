"""Dashboard i18n — English default, optional 中文."""
from __future__ import annotations

LANG_KEY = "dashboard_lang"
DEFAULT_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    # ── chrome ──────────────────────────────────────────────────────────────
    "lang_label": {"en": "Language", "zh": "语言"},
    "lang_en": {"en": "English", "zh": "English"},
    "lang_zh": {"en": "中文", "zh": "中文"},
    "page_subtitle": {
        "en": "Autonomous AI × economy forecasting system dashboard",
        "zh": "自主 AI 经济预测系统仪表盘",
    },
    "tab_radar": {"en": "Job Forecast Radar", "zh": "岗位预测雷达"},
    "tab_accuracy": {"en": "Forecast Accuracy", "zh": "预测准确度"},
    "tab_benchmarks": {"en": "Historical Benchmarks", "zh": "历史基准对比"},
    "tab_guard": {"en": "Plausibility Guard", "zh": "合理性校验"},
    "filter_all": {"en": "All", "zh": "全部"},
    "filter_none": {"en": "None", "zh": "无"},
    "gmm_spinner": {"en": "Computing GMM clustering…", "zh": "正在计算 GMM 聚类…"},

    # ── sidebar ─────────────────────────────────────────────────────────────
    "sidebar_framework": {"en": "Theoretical framework", "zh": "理论框架"},
    "sidebar_framework_body": {
        "en": """**Economic theories**
* **Autor task model** — augmentation vs substitution
* **Jevons paradox** — demand elasticity
* **O-Ring theory** — task complementarity
* **Baumol cost disease** — absorbing sectors

**Math & AI**
* Bayesian GMM clustering · PCA · Mahalanobis OOD · LLM prompting""",
        "zh": """**经济理论**
* **Autor 任务模型** — 增强 vs 替代
* **杰文斯悖论** — 需求弹性
* **O-Ring 理论** — 任务互补性
* **鲍莫尔成本病** — 吸收型部门

**数学与 AI**
* 贝叶斯 GMM 聚类 · PCA · 马氏距离 OOD · LLM 结构化推理""",
    },
    "sidebar_presets": {"en": "AI scenario presets", "zh": "AI 情景预设"},
    "sidebar_presets_help": {
        "en": "How will AI shape the future economy? Pick a preset or tune advanced variables below.",
        "zh": "AI 将如何重塑未来经济？选择预设情景，或在下方微调高级变量。",
    },
    "sidebar_preset_label": {"en": "Macro-economic scenario", "zh": "宏观经济情景"},
    "preset_baseline": {"en": "Baseline AI evolution", "zh": "基准 AI 演进"},
    "preset_agi": {"en": "AGI rapid emergence", "zh": "AGI 快速涌现"},
    "preset_robotics": {"en": "Physical robotics era", "zh": "实体机器人时代"},
    "preset_winter": {"en": "AI winter / slow adoption", "zh": "AI 寒冬 / 缓慢普及"},
    "preset_custom": {"en": "Custom configuration", "zh": "自定义配置"},
    "sidebar_advanced": {"en": "Advanced economic variables", "zh": "高级经济变量"},
    "sidebar_advanced_help": {"en": "Fine-tune underlying economic drivers.", "zh": "微调底层经济驱动因子。"},
    "sidebar_harness": {
        "en": """**Harness compliance**
* Offline-first stubs
* Deterministic GMM/PCA
* Explicit configured thresholds""",
        "zh": """**Harness 合规**
* 离线优先桩实现
* 确定性 GMM/PCA
* 显式配置阈值""",
    },
    "sidebar_donation": {"en": "Support & donation", "zh": "支持项目"},
    "sidebar_donation_body": {
        "en": "If this dashboard is useful, consider supporting our work!",
        "zh": "如果这个仪表盘对你有帮助，欢迎支持我们的工作！",
    },

    # ── economic variables ───────────────────────────────────────────────────
    "var_augmentation_ratio_label": {"en": "Augmentation ratio", "zh": "增强比例"},
    "var_augmentation_ratio_help": {
        "en": "How much AI assists workers (1.0) vs replaces them (0.0).",
        "zh": "AI 辅助人类（1.0）还是替代人类（0.0）的程度。",
    },
    "var_demand_elasticity_label": {"en": "Demand elasticity", "zh": "需求弹性"},
    "var_demand_elasticity_help": {
        "en": "How much lower costs raise total demand (1.0 = strong Jevons effect).",
        "zh": "成本下降带来需求增长的程度（1.0 = 强杰文斯效应）。",
    },
    "var_oring_leverage_label": {"en": "O-Ring leverage", "zh": "O-Ring 杠杆"},
    "var_oring_leverage_help": {
        "en": "How costly a single human error is (1.0 = forces automation).",
        "zh": "单点人为失误的代价（1.0 = 倒逼自动化）。",
    },
    "var_skill_distance_label": {"en": "Skill distance", "zh": "技能距离"},
    "var_skill_distance_help": {
        "en": "Difficulty of retraining (1.0 = total reskilling).",
        "zh": "再培训难度（1.0 = 几乎完全转岗）。",
    },
    "var_diffusion_years_label": {"en": "Diffusion years", "zh": "扩散年限"},
    "var_diffusion_years_help": {
        "en": "Years until full industry adoption.",
        "zh": "技术在全行业普及所需年数。",
    },
    "var_absorbing_sector_label": {"en": "Absorbing sector", "zh": "吸收型部门"},
    "var_absorbing_sector_help": {
        "en": "Can displaced workers move into service sectors?",
        "zh": "失业劳动力能否转入服务业等部门？",
    },
    "var_productivity_capture_label": {"en": "Productivity capture", "zh": "生产率捕获"},
    "var_productivity_capture_help": {
        "en": "Share of gains kept by capital (1.0) vs labour (0.0).",
        "zh": "生产率收益归资本（1.0）还是劳动者（0.0）的比例。",
    },
    "var_task_frontier_open_label": {"en": "Task frontier open", "zh": "新任务前沿"},
    "var_task_frontier_open_help": {
        "en": "Does the technology create brand-new human tasks?",
        "zh": "技术是否会创造全新的人类任务？",
    },

    # ── guard tab ───────────────────────────────────────────────────────────
    "guard_title": {"en": "Plausibility guard", "zh": "合理性校验"},
    "guard_intro": {
        "en": """**What is this?**
Extreme sidebar settings may describe scenarios with no historical precedent.

This page computes the **scenario divergence index** (Mahalanobis distance).

* **Within envelope (blue):** historical precedents exist; forecasts anchor on past transitions.
* **Out of distribution (red):** historically extreme; safety guards widen uncertainty.""",
        "zh": """**这是什么？**
侧边栏的极端参数可能对应历史上从未出现过的情景。

本页计算 **情景偏离指数**（马氏距离）。

* **包络线内（蓝色）：** 有历史先例，预测锚定类似转型。
* **分布外（红色）：** 历史极端情景，安全护栏自动放宽不确定性。""",
    },
    "guard_divergence": {"en": "Divergence index", "zh": "偏离指数"},
    "guard_threshold": {"en": "Safety threshold", "zh": "安全阈值"},
    "guard_gauge_title": {
        "en": "Scenario divergence (Mahalanobis distance)",
        "zh": "情景偏离（马氏距离）",
    },
    "guard_actions": {"en": "Safety correction actions", "zh": "安全校正措施"},
    "guard_ood_status": {
        "en": "**Status: unprecedented scenario**\n\nIndex {d:.2f} exceeds safe threshold ({t:.2f}).",
        "zh": "**状态：史无前例情景**\n\n指数 {d:.2f} 超过安全阈值（{t:.2f}）。",
    },
    "guard_ood_actions": {
        "en": """**Safety corrections activated:**
* Widen confidence intervals
* Reduce weight on historical analogies
* Flag forecasts as high-uncertainty""",
        "zh": """**已启用安全校正：**
* 放宽置信区间
* 降低历史类比权重
* 标记为高不确定性预测""",
    },
    "guard_ok_status": {
        "en": "**Status: historically plausible**\n\nIndex {d:.2f} within safe envelope (limit {t:.2f}).",
        "zh": "**状态：历史范围内合理**\n\n指数 {d:.2f} 处于安全包络内（上限 {t:.2f}）。",
    },
    "guard_ok_actions": {
        "en": """**Baseline settings applied:**
* Anchor on **{regime}** transition pattern
* Job multiplier **{mult:.2f}x**, lag **{lag:.1f} years**""",
        "zh": """**已应用基线设置：**
* 锚定 **{regime}** 转型模式
* 就业倍数 **{mult:.2f}x**，滞后 **{lag:.1f} 年**""",
    },
    "guard_emerging": {"en": "Simulated AI impact: emerging occupations", "zh": "模拟 AI 影响：新兴职业"},
    "guard_emerging_info": {
        "en": "Occupation analysis lives on the **Job Forecast Radar** tab.",
        "zh": "岗位分析与转型路径请见 **岗位预测雷达** 标签页。",
    },
    "guard_rules": {"en": "Case library conditional rules", "zh": "案例库条件规则"},
    "guard_vector": {"en": "Scenario vector", "zh": "情景向量"},
    "guard_vector_help": {
        "en": "Adjust sidebar variables to see live vector updates.",
        "zh": "调整侧边栏变量可实时更新向量。",
    },

    # ── benchmarks tab ───────────────────────────────────────────────────────
    "bench_title": {"en": "Historical analogy & transition regimes", "zh": "历史类比与转型范式"},
    "bench_intro": {
        "en": """**What is this?**
Compare your AI scenario with **15+ historical tech transitions**.

* **Chart:** cases in PCA space; your scenario is the **red diamond**.
* **Axes:** complementarity (PCA1) · friction (PCA2) · demand expansion (PCA3)""",
        "zh": """**这是什么？**
将 AI 情景与 **15+ 次历史技术转型** 对比。

* **图表：** 案例分布于 PCA 空间；你的情景为 **红色菱形**。
* **三轴：** 互补性（PCA1）· 摩擦（PCA2）· 需求扩张（PCA3）""",
    },
    "bench_plot_label": {"en": "Visualization", "zh": "可视化"},
    "bench_plot_3d": {"en": "3D PCA space", "zh": "三维 PCA"},
    "bench_plot_2d": {"en": "2D projection (PCA1 vs PCA2)", "zh": "二维投影（PCA1 vs PCA2）"},
    "bench_highlight": {"en": "Highlight historical case", "zh": "高亮历史案例"},
    "bench_sim_scenario": {"en": "Simulated AI scenario", "zh": "模拟 AI 情景"},
    "bench_regimes": {"en": "Job transition regimes", "zh": "就业转型范式"},
    "bench_confidence": {
        "en": "**Pattern match confidence:** `{p:.1f}%` *(target > 70%)*",
        "zh": "**模式匹配置信度：** `{p:.1f}%` *（目标 > 70%）*",
    },
    "bench_regimes_tip": {
        "en": "Clusters group historical cases; table shows mean job multiplier and lag per pattern.",
        "zh": "聚类将历史案例分组；表格展示各范式的平均就业倍数与转型滞后。",
    },
    "bench_library": {"en": "Historical cases library (N=15)", "zh": "历史案例库（N=15）"},
    "bench_highlight_details": {"en": "Highlighted case details", "zh": "高亮案例详情"},

    # ── accuracy tab ─────────────────────────────────────────────────────────
    "acc_title": {"en": "Forecast accuracy tracker", "zh": "预测准确度追踪"},
    "acc_intro": {
        "en": "Tracks AI forecasts vs real outcomes. Lower **Brier score** = better calibration.",
        "zh": "追踪 AI 预测与现实结果。**Brier 分数**越低表示校准越好。",
    },
    "acc_total": {"en": "Total predictions", "zh": "预测总数"},
    "acc_open": {"en": "Active / open", "zh": "进行中"},
    "acc_resolved": {"en": "Resolved", "zh": "已解析"},
    "acc_brier": {"en": "Brier score", "zh": "Brier 分数"},
    "acc_brier_note": {
        "en": "Brier score: 0.0000 = perfect; 0.2500 ≈ random guessing at 50%.",
        "zh": "Brier 分数：0.0000 = 完美；0.2500 ≈ 50% 随机猜测。",
    },
    "acc_no_cal": {
        "en": "No calibration data yet. Resolved predictions are required. Demo seed loads on empty HF Spaces.",
        "zh": "暂无校准数据，需要已解析的预测。HF Space 空库时会自动加载演示种子数据。",
    },
    "acc_explore": {"en": "Explore predictions", "zh": "浏览预测"},
    "acc_filter_cat": {"en": "Filter by category", "zh": "按类别筛选"},
    "acc_active": {"en": "Active predictions ({n})", "zh": "进行中预测（{n}）"},
    "acc_resolved_list": {"en": "Resolved predictions ({n})", "zh": "已解析预测（{n}）"},
    "acc_no_active": {"en": "No active predictions in this category.", "zh": "该类别无进行中预测。"},
    "acc_no_resolved": {"en": "No resolved predictions in this category.", "zh": "该类别无已解析预测。"},
    "acc_no_preds": {"en": "No predictions in the registry.", "zh": "注册表中无预测记录。"},
    "acc_market_title": {"en": "Crowd consensus & prediction market", "zh": "群体共识与预测市场"},
    "acc_market_intro": {
        "en": "Stake virtual points on open predictions. Leaderboard settles when outcomes resolve.",
        "zh": "对开放预测下注虚拟积分；结果揭晓后结算排行榜。",
    },
    "acc_vote_title": {"en": "Submit your forecast vote", "zh": "提交你的预测投票"},
    "acc_bettor": {"en": "Your forecaster name", "zh": "你的预测昵称"},
    "acc_bettor_help": {"en": "Used for the leaderboard; can be anonymous.", "zh": "用于排行榜，可匿名。"},
    "acc_choose_pred": {"en": "Choose a forecast", "zh": "选择预测条目"},
    "acc_consensus": {"en": "Market consensus ({n} votes)", "zh": "市场共识（{n} 票）"},
    "acc_prob": {"en": "Your probability this happens", "zh": "你认为发生的概率"},
    "acc_stake": {"en": "Stake (virtual points)", "zh": "下注（虚拟积分）"},
    "acc_submit": {"en": "Submit vote", "zh": "提交投票"},
    "acc_vote_ok": {
        "en": "Vote submitted: {p:.0f}% probability, {s} points staked.",
        "zh": "投票已提交：概率 {p:.0f}%，下注 {s} 积分。",
    },
    "acc_leaderboard": {"en": "Leaderboard", "zh": "排行榜"},
    "acc_lb_empty": {
        "en": "No settled predictions yet.",
        "zh": "尚无已结算预测。",
    },
    "acc_no_bets": {"en": "No open predictions for betting.", "zh": "暂无可下注的开放预测。"},
    "acc_registry_err": {"en": "Error loading registry: {e}", "zh": "加载注册表失败：{e}"},
    "acc_market_err": {"en": "Market error: {e}", "zh": "市场模块错误：{e}"},

    # ── radar tab (selected keys; HTML labels passed as vars) ─────────────────
    "radar_title": {"en": "Job forecast radar", "zh": "岗位预测雷达"},
    "radar_intro": {
        "en": """**Welcome!** Search a job title to see displacement risk, skill shifts, and transition paths.

*Example: Financial Analyst, Software Engineer, Tax preparer.*

*Technical: Lightweight Hybrid RAG (structural filters + semantic search).*""",
        "zh": """**欢迎！** 搜索岗位名称，查看替代风险、技能变化与转型路径。

*例如：金融分析师、软件工程师、报税员。*

*技术说明：轻量混合 RAG（结构化因果过滤 + 语义检索）。*""",
    },
    "radar_kb_missing": {
        "en": "Job knowledge base not loaded. Ensure `data/jobs_kb.json` exists.",
        "zh": "岗位知识库未加载，请确认 `data/jobs_kb.json` 存在。",
    },
    "radar_search": {"en": "Search jobs or skills", "zh": "搜索岗位或技能"},
    "radar_search_ph": {"en": "e.g. finance process improvement", "zh": "例如：财务流程优化"},
    "radar_industry": {"en": "Filter by industry", "zh": "按行业筛选"},
    "radar_llm_spin": {"en": "Generating AI profile for '{q}'…", "zh": "正在为「{q}」生成 AI 岗位画像…"},
    "radar_llm_ok": {
        "en": "New profile added: **{title}**",
        "zh": "已添加新画像：**{title}**",
    },
    "radar_llm_fail": {
        "en": "Could not generate profile. Set `GROQ_API_KEY` or `ANTHROPIC_API_KEY`.",
        "zh": "无法生成画像，请配置 `GROQ_API_KEY` 或 `ANTHROPIC_API_KEY`。",
    },
    "radar_search_hit": {
        "en": "Most relevant role for «{q}»: **{title}** (search relevance {sim:.2f}). "
              "This is a text-search match, not a career recommendation.",
        "zh": "与「{q}」最相关的岗位：**{title}**（检索相关度 {sim:.2f}）。"
              "这是文本检索匹配，并非职业推荐。",
    },
    "badge_ai": {"en": "AI-native", "zh": "AI 原生"},
    "badge_non_ai": {"en": "Non-AI", "zh": "非 AI"},
    "lbl_skill_overlap": {"en": "Skill overlap", "zh": "技能重叠度"},
    "lbl_risk_change": {"en": "Displacement risk", "zh": "替代风险"},
    "lbl_rationale": {"en": "Why this path", "zh": "推理依据"},
    "rationale_low_risk": {
        "en": "lower automation risk ({frm:.0f}%→{to:.0f}%)",
        "zh": "自动化风险更低（{frm:.0f}%→{to:.0f}%）",
    },
    "rationale_skills": {
        "en": "{n} shared skill(s)",
        "zh": "{n} 项可迁移技能",
    },
    "rationale_theory": {
        "en": "Autor task model: redeploys human-complementary tasks",
        "zh": "Autor 任务模型：迁移至人类互补型任务",
    },
    "rationale_skill_match": {
        "en": "{pct:.0f}% skill-vector proximity",
        "zh": "技能向量贴近度 {pct:.0f}%",
    },
    "lbl_demand_outlook": {"en": "Demand outlook", "zh": "需求前景"},
    "lbl_match_score": {"en": "Match", "zh": "匹配度"},
    "radar_trans_method": {
        "en": "Paths are derived live from 8-D skill-vector distance, automation-risk "
              "reduction, and scenario demand — not a fixed list.",
        "zh": "转型路径由 8 维技能向量距离、自动化风险下降与情景需求**实时推导**，并非固定清单。",
    },
    "radar_ai_badge": {"en": " (AI estimate)", "zh": "（AI 估算）"},
    "radar_matrix": {"en": "Occupation impact matrix", "zh": "职业影响矩阵"},
    "radar_at_risk": {"en": "At-risk & transforming roles", "zh": "高风险与转型中岗位"},
    "radar_opportunity": {"en": "Emerging & high-opportunity roles", "zh": "新兴与高机会岗位"},
    "radar_no_at_risk": {"en": "No at-risk roles match filters.", "zh": "无符合筛选的高风险岗位。"},
    "radar_no_opp": {"en": "No opportunity roles match filters.", "zh": "无符合筛选的机会型岗位。"},
    "radar_more_at_risk": {"en": "View {n} more at-risk roles", "zh": "查看更多 {n} 个高风险岗位"},
    "radar_more_opp": {"en": "View {n} more opportunity roles", "zh": "查看更多 {n} 个机会型岗位"},
    "risk_high": {"en": "High risk", "zh": "高风险"},
    "risk_moderate": {"en": "Moderate risk", "zh": "中等风险"},
    "opp_growth": {"en": "Growth opp", "zh": "增长机会"},
    "opp_transform": {"en": "Transforming", "zh": "转型中"},
    "lbl_displacement": {"en": "Displacement risk", "zh": "替代风险"},
    "lbl_skills": {"en": "Key skills", "zh": "关键技能"},
    "lbl_category": {"en": "Role category", "zh": "岗位类别"},
    "radar_transition": {"en": "Career transition path explorer", "zh": "职业转型路径探索"},
    "radar_transition_help": {
        "en": "Pick your current role to see low-retraining transition paths and skill bridges.",
        "zh": "选择当前岗位，查看再培训成本较低的转型路径与技能桥梁。",
    },
    "radar_select_role": {"en": "Select your current role", "zh": "选择你当前的岗位"},
    "radar_role_class": {"en": "Role classification", "zh": "岗位分类"},
    "radar_baseline_growth": {"en": "Baseline growth", "zh": "基线需求趋势"},
    "radar_role_desc": {"en": "Role description", "zh": "岗位描述"},
    "radar_skill_tags": {"en": "Key skill tags", "zh": "技能标签"},
    "status_high_disp": {"en": "High displacement risk", "zh": "高替代风险"},
    "status_transforming": {"en": "Transforming", "zh": "转型中"},
    "status_emerging": {"en": "Emerging opportunity", "zh": "新兴机会"},
    "radar_empirical": {"en": "Empirical crowd feedback (N = {n})", "zh": "群体实证反馈（N = {n}）"},
    "radar_emp_disp": {"en": "Empirical displacement", "zh": "实证替代率"},
    "radar_theo_disp": {"en": "Theoretical displacement", "zh": "理论替代风险"},
    "radar_emp_conf": {"en": "Average worker confidence", "zh": "劳动者平均信心"},
    "radar_emp_targets": {"en": "Top crowd-reported targets", "zh": "群体报告的热门转型目标"},
    "radar_emp_none": {"en": "None reported yet", "zh": "暂无报告"},
    "radar_trans_paths": {"en": "Recommended transition paths", "zh": "推荐转型路径"},
    "lbl_skill_bridge": {"en": "Skill bridge", "zh": "技能桥梁"},
    "lbl_retrain": {"en": "Est. retraining", "zh": "预计再培训"},
    "lbl_months": {"en": "months", "zh": "个月"},
    "lbl_salary": {"en": "Salary", "zh": "薪资"},
    "radar_timeline": {"en": "Emerging occupations timeline", "zh": "新兴职业时间线"},
    "radar_timeline_help": {
        "en": "Emergence years scale with sidebar **Diffusion years**.",
        "zh": "涌现年份随侧边栏 **扩散年限** 动态缩放。",
    },
    "radar_timeline_empty": {"en": "No emerging roles for timeline.", "zh": "暂无可用于时间线的新兴岗位。"},
    "radar_timeline_note": {
        "en": "Baseline diffusion = 10 years. Lower **Diffusion years** pulls emergence forward.",
        "zh": "基线扩散 10 年。降低 **扩散年限** 会提前涌现年份。",
    },
    "radar_survey": {"en": "Crowd-sourced career survey", "zh": "群体职业转型问卷"},
    "radar_survey_help": {
        "en": "Share status and transition goals to calibrate models. Optional 6-month email follow-up.",
        "zh": "分享就业状态与转型目标以校准模型。可选 6 个月邮件回访。",
    },
    "radar_fb_job": {"en": "Your current or recent job", "zh": "当前或最近岗位"},
    "radar_fb_industry": {"en": "Industry", "zh": "行业"},
    "radar_fb_company": {"en": "Company (optional)", "zh": "公司（可选）"},
    "radar_fb_email": {"en": "Email for 6-month follow-up (optional)", "zh": "回访邮箱（可选）"},
    "radar_fb_email_help": {
        "en": "We ask in 6 months if your transition succeeded. Never sold.",
        "zh": "6 个月后询问转型结果，不会出售或共享。",
    },
    "radar_fb_status": {"en": "Employment status", "zh": "就业状态"},
    "radar_fb_confidence": {"en": "Job security confidence (0–100)", "zh": "工作安全感（0–100）"},
    "radar_fb_target": {"en": "Target role if transitioning", "zh": "转型目标岗位"},
    "radar_fb_submit": {"en": "Submit survey", "zh": "提交问卷"},
    "radar_fb_ok": {"en": "Thank you! Response recorded.", "zh": "感谢提交！已记录你的反馈。"},
    "radar_fb_ok_email": {
        "en": "Thank you! We will follow up in 6 months.",
        "zh": "感谢提交！我们将在 6 个月后回访。",
    },
    "radar_sources": {"en": "Data sources & citations (HR-7)", "zh": "数据来源与引用（HR-7）"},
    "radar_sources_intro": {
        "en": "Occupation profiles reference authoritative labour-market research.",
        "zh": "岗位画像引用权威劳动力市场研究来源。",
    },

    # ── industries ────────────────────────────────────────────────────────────
    "industry_agriculture": {"en": "Agriculture", "zh": "农业"},
    "industry_construction": {"en": "Construction", "zh": "建筑业"},
    "industry_education": {"en": "Education", "zh": "教育"},
    "industry_finance": {"en": "Finance", "zh": "金融"},
    "industry_government": {"en": "Government", "zh": "政府/公共部门"},
    "industry_healthcare": {"en": "Healthcare", "zh": "医疗健康"},
    "industry_hospitality": {"en": "Hospitality", "zh": "酒店餐饮/旅游"},
    "industry_legal": {"en": "Legal", "zh": "法律"},
    "industry_logistics": {"en": "Logistics", "zh": "物流"},
    "industry_manufacturing": {"en": "Manufacturing", "zh": "制造业"},
    "industry_media": {"en": "Media", "zh": "媒体"},
    "industry_retail": {"en": "Retail", "zh": "零售"},
    "industry_tech": {"en": "Tech", "zh": "科技"},

    # ── employment status ─────────────────────────────────────────────────────
    "emp_status_employed": {"en": "Employed", "zh": "在职"},
    "emp_status_unemployed": {"en": "Unemployed", "zh": "失业"},
    "emp_status_transitioning": {"en": "Transitioning", "zh": "转型中"},

    # ── job role categories (KB) ──────────────────────────────────────────────
    "cat_at_risk": {"en": "At risk", "zh": "高风险"},
    "cat_emerging": {"en": "Emerging", "zh": "新兴"},
    "cat_transforming": {"en": "Transforming", "zh": "转型中"},

    # ── prediction categories (registry) ────────────────────────────────────
    "pred_labor": {"en": "Labor", "zh": "劳动力"},
    "pred_compute": {"en": "Compute", "zh": "算力"},
    "pred_macro": {"en": "Macro", "zh": "宏观经济"},
    "pred_capital": {"en": "Capital", "zh": "资本"},
    "pred_policy": {"en": "Policy", "zh": "政策"},
    "pred_general": {"en": "General", "zh": "综合"},

    # ── accuracy table columns ────────────────────────────────────────────────
    "col_id": {"en": "ID", "zh": "ID"},
    "col_statement": {"en": "Statement", "zh": "预测陈述"},
    "col_category": {"en": "Category", "zh": "类别"},
    "col_confidence": {"en": "Confidence", "zh": "置信度"},
    "col_horizon": {"en": "Horizon", "zh": "时间窗口"},
    "col_resolution": {"en": "Resolution date", "zh": "解析日期"},
    "col_outcome": {"en": "Outcome", "zh": "结果"},
    "col_brier": {"en": "Brier", "zh": "Brier"},
    "col_rationale": {"en": "Rationale", "zh": "判定理由"},
    "outcome_true": {"en": "TRUE", "zh": "成立"},
    "outcome_false": {"en": "FALSE", "zh": "不成立"},
}

_VARIABLES = (
    "augmentation_ratio",
    "demand_elasticity",
    "oring_leverage",
    "skill_distance",
    "diffusion_years",
    "absorbing_sector",
    "productivity_capture",
    "task_frontier_open",
)

INDUSTRY_CODES: tuple[str, ...] = (
    "Agriculture", "Construction", "Education", "Finance", "Government",
    "Healthcare", "Hospitality", "Legal", "Logistics", "Manufacturing",
    "Media", "Retail", "Tech",
)

EMPLOYMENT_STATUS_CODES: tuple[str, ...] = (
    "employed", "unemployed", "transitioning",
)


def lang() -> str:
    import streamlit as st
    return st.session_state.get(LANG_KEY, DEFAULT_LANG)


def t(key: str, **kwargs) -> str:
    return _translate(lang(), key, **kwargs)


def _translate(code: str, key: str, **kwargs) -> str:
    entry = _STRINGS.get(key, {})
    text = entry.get(code, entry.get("en", key))
    return text.format(**kwargs) if kwargs else text


def init_language() -> None:
    import streamlit as st
    if LANG_KEY not in st.session_state:
        st.session_state[LANG_KEY] = DEFAULT_LANG


def render_language_selector() -> None:
    import streamlit as st
    init_language()
    options = ("en", "zh")
    labels = {code: t(f"lang_{code}") for code in options}
    inv = {labels[c]: c for c in options}
    current_label = labels[lang()]
    choice = st.sidebar.selectbox(
        t("lang_label"),
        list(inv.keys()),
        index=list(inv.keys()).index(current_label),
        key="lang_selector",
    )
    selected = inv[choice]
    if selected != st.session_state[LANG_KEY]:
        st.session_state[LANG_KEY] = selected
        st.rerun()


def var_label(name: str) -> str:
    return t(f"var_{name}_label")


def var_help(name: str) -> str:
    return t(f"var_{name}_help")


def job_title(job: dict) -> str:
    return _job_title_for(lang(), job)


def job_description(job: dict) -> str:
    return _job_description_for(lang(), job)


def _job_title_for(code: str, job: dict) -> str:
    if code == "zh" and job.get("title_zh"):
        return job["title_zh"]
    return job.get("title", "")


def _job_description_for(code: str, job: dict) -> str:
    if code == "zh" and job.get("description_zh"):
        return job["description_zh"]
    return job.get("description", "")


def filter_all_label() -> str:
    return t("filter_all")


def industry_label(name: str) -> str:
    return _industry_label_for(lang(), name)


def employment_status_label(code: str) -> str:
    key = f"emp_status_{code.lower()}"
    if key in _STRINGS:
        return _translate(lang(), key)
    return code


def job_category_label(category: str) -> str:
    return _job_category_label_for(lang(), category)


def _industry_label_for(code: str, name: str) -> str:
    key = f"industry_{name.lower()}"
    if key in _STRINGS:
        return _translate(code, key)
    return name


def _job_category_label_for(code: str, category: str) -> str:
    key = f"cat_{category}"
    if key in _STRINGS:
        return _translate(code, key)
    return category.replace("_", " ").title()


def prediction_category_label(category: str) -> str:
    key = f"pred_{category}"
    if key in _STRINGS:
        return _translate(lang(), key)
    return category.replace("_", " ").title()
