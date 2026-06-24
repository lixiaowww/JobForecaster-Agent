# Product Requirement Document (PRD) — forecaster-agent

**Version:** 0.10 (Semantic Job Search + Query Calibration Agent)  
**Last updated:** 2026-06-24

An autonomous AI × economy forecasting system that generates, calibrates, and publishes **falsifiable** predictions — with explicit limits on historical extrapolation.

---

## 1. Product Vision

Build a self-correcting forecasting system for how AI technology and the economy co-evolve. Every prediction is dated, judgeable, and Brier-scored; the scoreboard feeds the next cycle.

### Core objectives

| Objective | Definition of done |
|-----------|-------------------|
| **Falsifiability** | Every forecast has `resolution_date` + `resolution_criteria` |
| **Self-calibration** | Mean Brier + 10-decile reliability curve in `registry.scoreboard()` |
| **Evidence-backed** | Signals from ingest; evolution prior from citable case library |
| **Honest extrapolation** | OOD Mahalanobis signal widens confidence when scenario is unprecedented |
| **Crowd wisdom (Phase 2)** | Anti-anchoring contributions filtered by soundness × novelty |

---

## 2. System Architecture (as implemented)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Orchestrator (`loop.py`)                    │
│                                                                     │
│  RESOLVE ──► SCORE      INGEST signals                             │
│  (judge due  (Brier)      (arXiv·RSS·Tavily·FRED)                  │
│  predictions)   │               │                                   │
│                 │    track      │   signals                         │
│                 └──► record ──► EVOLUTION PRIOR                    │
│                                    │    (PCA/GMM/OOD)               │
│                                    ▼                                │
│                               FORECAST ◄── track record             │
│                                    │                                │
│                              [CROWD GATE]  ← Phase 2, not in loop  │
│                                    │                                │
│                                DEDUP ──► REGISTRY (SQLite)         │
│                                    │                                │
│                               PUBLISH ──► site · webhook · git     │
│                           (review gate)                             │
└─────────────────────────────────────────────────────────────────────┘

Parallel surface: `dashboard.py` (Streamlit) + `services/read_model.py` (read API seam)
```

### 2.1 Forecaster loop (`loop.py`, `forecast.py`, `registry.py`, `publish.py`)

| Capability | Status |
|------------|--------|
| Signal ingestion | ✅ arXiv, RSS, Tavily*, FRED* |
| Evolution prior in forecast prompt | ✅ since v0.5 |
| Falsifiable prediction generation | ✅ |
| Due prediction judging | ✅ |
| Brier scoreboard | ✅ |
| SQLite registry | ✅ `data/forecaster.db` |
| Review gate (`require_review`) | ✅ default `true` |
| Crowd gate in loop | 🔧 Phase 2 |

\* Requires API key in environment.

### 2.2 Crowd gate (`crowd.py`, `services/crowd_service.py`)

| Capability | Status |
|------------|--------|
| Soundness + novelty gates | ✅ offline-tested |
| Reputation from Brier | ✅ |
| Anti-anchoring REST submit | ✅ `GET/POST /v1/predictions/{id}/...` |
| Crowd gate in loop | ✅ `process_open_prediction_crowds()` |
| Contribution resolve on prediction resolve | ✅ |
| Discord/Telegram bot adapters | 🔧 Phase 2b |

### 2.3 Job evolution agent (`evolution.py`)

| Capability | Status |
|------------|--------|
| 15+ citable historical cases | ✅ |
| PCA + Bayesian GMM | ✅ |
| Mahalanobis OOD | ✅ |
| `EvolutionPrior.to_prompt_context()` | ✅ wired into `forecast.generate_predictions()` |

### 2.4 Job Radar (`job_radar.py`, `dashboard.py`)

| Capability | Status |
|------------|--------|
| ~80 occupation profiles, 13 industries | ✅ v0.10 |
| Hybrid RAG (α·structural + β·semantic) | ✅ |
| **Search retrieval** (`combined_similarity`: semantic embed + lexical blend) | ✅ v0.10 |
| **Transition recommendation** (`compute_transition_paths`: skill 40% + overlap 15% + risk 25% + demand 20%) | ✅ |
| Search vs transition paths kept separate (HR-12) | ✅ Phase 8 |
| Anchored search hides misleading at-risk column (weak text scores) | ✅ Phase 8 / v0.10 |
| Hot-role KB coverage (`CORE_HOT_ROLE_QUERIES` + `search_aliases`) | ✅ v0.10 |
| Semantic job search (`SentenceEmbedder` / MiniLM, title-only vectors) | ✅ v0.10 |
| Offline CI search (`RadarHashingEmbedder` via `config.ci.yaml`) | ✅ HR-1 |
| Bilingual + CJK queries (multilingual embed + lexical tokens) | ✅ v0.10 |
| Query title normalization (`normalize_search_query`, `title_aliases`) | ✅ v0.10 |
| User-facing match tiers (无匹配 / 弱 / 强) | ✅ Phase 8 |
| Personalized transition weights (experience level, retrain tolerance) | ✅ Phase 8 |
| Field survey: canonical title + experience level (HR-13) | ✅ Phase 8 |
| BLS + field-feedback calibration overlay | ✅ |
| Prediction market UI | ✅ |
| LLM KB expansion for unknown titles | ✅ (needs API key) |

**Two crowd surfaces (do not conflate):**

| Surface | Purpose | Minimum identity |
|---------|---------|------------------|
| **Field feedback** (`JobFeedback`, Radar survey) | Calibrate displacement risk + empirical transition targets | Canonical **job title** + **experience level** (HR-13) |
| **Prediction crowd** (`contribution`, REST/Telegram) | Anti-anchoring probability submissions | `contributor_id` only; optional expert weighting is out of scope |

### 2.5 Job Query Calibration Agent (`services/job_query_agent/`, Phase 9)

Continuous **retrieval QA loop** — discovers search queries, evaluates KB match quality, auto-fixes safe alias gaps, and gates risky changes behind human review.

| Capability | Status |
|------------|--------|
| Query discovery (CORE hot roles, seed file, `JobFeedback` titles) | ✅ |
| Per-query verdict (`ok`, `p0_regression`, `weak_core`, `kb_gap`, `weak_match`) | ✅ |
| Simulate-before-apply (`alias_patch`, `title_alias`) | ✅ |
| Auto-apply safe fixes (`jobs_kb.json` + `config.yaml` title map) | ✅ gated |
| CI guard (`query-agent audit` — P0 + weak-core fail build) | ✅ |
| Daily closed loop (`query-agent run` → commit KB/config) | ✅ |
| Trace log (`data/query_agent_traces.jsonl`, gitignored) | ✅ |
| Human review queue (`pending/job_calibration/`) for `kb_profile_new` | ✅ |
| HF search-log ingest (frequency-weighted gaps) | ✅ P2 |

**Operating modes:**

| Command | When | Behaviour |
|---------|------|-----------|
| `query-agent audit` | CI after pytest | Read-only; raises on P0 regression or weak-core |
| `query-agent once` | Manual triage | Audit + queue non-ok proposals to `pending/` |
| `query-agent run` | Daily cron | Multi-round discover → simulate → auto-apply → re-check; commits diffs |
| `query-agent apply` | After human review | Apply all `pending/job_calibration/*.json` (incl. `kb_profile_new`) |
| `query-agent ingest-logs` | HF export merge | Merge external search JSONL into `data/radar_search_log.jsonl` |

### 2.6 Read model / external integration seam (`services/read_model.py`)

| Capability | Status |
|------------|--------|
| `get_scoreboard()` | ✅ |
| `get_ood_assessment()` | ✅ |
| `search_jobs()` | ✅ |
| `list_open_predictions()` | ✅ |
| MCP Server wrapper | ✅ `mcp_server.py` |
| REST `/v1/*` | ✅ `api_server.py` |

---

## 3. Harness Engineering Invariants (non-negotiable)

| ID | Rule | Enforcement |
|----|------|-------------|
| **HR-1** | Offline-first testability | LLM/embeddings behind Protocol + stubs; `pytest tests/` passes with no API key |
| **HR-2** | Pure scoring core | Brier, JSD, PCA/GMM math side-effect free; tests assert properties |
| **HR-3** | Explicit thresholds | `tau_*`, `alpha`, `beta`, `n_bootstrap` in `config.yaml` only |
| **HR-4** | Citable cases only | `test_case_library_integrity` rejects missing sources |
| **HR-5** | Strict publishing gate | `require_review: true` in default config; PRs flipping default rejected |
| **HR-6** | Model-agnostic LLM | Single seam: `forecast.call_llm()` (Groq → Anthropic) |
| **HR-7** | Citable job profiles | Every `JobProfile.sources` non-empty |
| **HR-8** | BUSL-1.1 license | Commercial SaaS/API requires separate license |
| **HR-9** | Citation integrity | LLM-generated `sources` URLs pass schema check; arXiv IDs must not reference a future YYMM; `example.com` / placeholder domains rejected at parse time. Enforced in `forecast._sanitize_sources()`. |
| **HR-10** | Resolved-state durability | `run.py export` serialises `status`, `outcome`, `brier`, `resolved_at`; `ensure_demo_registry` reloads them via `model_validate_json` preserving resolution. Track record must never regress to all-`open` after a cache eviction. |
| **HR-11** | Origin transparency | Every prediction shown in the Track Record tab carries an explicit `origin` badge (`seed` = curated benchmark, `live` = daily LLM cron). `run.py export` writes **live-only** rows to `predictions_live.jsonl`; `run.py verify-export` fails CI if DB live state diverges from the committed file after a resolve. |
| **HR-12** | Retrieval ≠ recommendation | Job **search** ranks by `combined_similarity` (semantic + lexical blend). **Transition fit** ranks by `transition_score` from `compute_transition_paths()` only. UI and API must not present search hits as career recommendations without an anchor role + transition pass. Thresholds in `config.yaml` (HR-3); use **tier labels** (`tier_no_match` / `tier_weak` / `tier_strong`), not raw cosine intuition (~0.7). Production embedder: `sentence_transformers`; CI/harness: `hashing`. |
| **HR-13** | Field feedback profile | Radar career survey collects **canonical `job_title`** (KB dropdown, not free text) plus **`experience_level`** (bucket: junior / mid / senior, or years-in-role bands). Aggregates keyed by title today; stratify by `(title, experience_level)` when n≥5 per cell. Powers personalized retrain tolerance and transition weight overrides. |

---

## 4. Configuration (`config.yaml`)

| Key | Purpose |
|-----|---------|
| `database_path` | Documented SQLite location (engine in `schemas.py`) |
| `evolution.n_bootstrap` | GMM bootstrap iterations (use `10` in tests) |
| `evolution.scenario` | Optional override of `CURRENT_AI_SCENARIO` |
| `job_radar.*` | Hybrid RAG weights, KB path, transition weights |
| `job_radar.search.*` | `embedder` (`sentence_transformers` \| `hashing`), embed/lex blend, tier thresholds, `title_aliases` (HR-3) |
| `job_radar.personalization.*` | Experience-level weight overrides, max retrain months (Phase 8) |
| `job_query_agent.*` | Discover sources, evaluate gates, `auto_apply` types/limits, traces path (Phase 9) |
| `crowd.*` | Gate thresholds (for Phase 2 API) |
| `require_review` | Publishing safety gate |

---

## 5. Roadmap (honest status)

### Phase 1 — Engineering stabilization ✅ (v0.5)

- [x] Flat-layout import strategy (`try/except` flat vs package imports)
- [x] CLI (`run.py score`) operational
- [x] Tests in `tests/`; CI in `.github/workflows/ci.yml`
- [x] `config.yaml` aligned with SQLite
- [x] Evolution prior wired into forecast loop

### Phase 2 — Crowd contributor surface ✅

- [x] REST anti-anchoring API
- [x] CrowdGate in loop
- [x] Telegram bot (`python -m bots.run_bots telegram`)
- [x] Discord bot (`python -m bots.run_bots discord`)

### Phase 3 — Read-only MCP ✅ + REST ✅

- [x] MCP Server (`mcp_server.py`) — stdio, 4 read tools
- [x] REST API (`api_server.py`) — `/v1/*`, OpenAPI `/docs`
- [x] Shared handlers (`services/mcp_handlers.py`)
- [x] Optional `FORECASTER_API_KEY` + rate limiting
- [ ] API key rotation / multi-tenant auth

### Phase 4 — Dashboard decomposition ✅

- [x] Split `dashboard.py` into `ui/tabs/*` (`accuracy`, `benchmarks`, `guard`, `radar`)
- [x] Dashboard reads via `services/` — `services/dashboard_data.py`, `services/dashboard_seed.py`, `services/config_loader.py`; `dashboard.py` is now a 104-LOC orchestrator only

### Phase 5 — Trust & scale ✅ (v0.7, 2026-06-24)

- [x] **Brier history public dataset**: Resolved predictions downloadable as CSV from the Track Record tab (`⬇ Download track_record.csv`)
- [x] **Non-Western + net-loss evolution cases**: 4 new `TransitionCase` entries added to `CASE_LIBRARY` (total: 19 cases):
  - `china_mobile_payment` — Alipay/WeChat Pay & bank clerks, China 2013-2023 (net loss, multiplier 0.75)
  - `japan_factory_robots` — FANUC/Kawasaki robotic assembly, Japan 1970-2000 (slight net gain)
  - `india_bpo_automation` — RPA + LLM chatbots & BPO agents, India 2015-2025 (net loss, multiplier 0.80)
  - `south_korea_steel_automation` — POSCO continuous casting, South Korea 1980-2010 (net loss, multiplier 0.65)
- [x] **Novice usability score ≥ 7/10** — UX audit identified 5 defects; 4 fixed:
  - Navigation: `st.radio` → `st.tabs` (standard, scannable)
  - Onboarding: session-based welcome banner with 3-step guide
  - Tab names: "Plausibility Guard" → "Scenario Advisor"; "Historical Benchmarks" → "History: How AI Changed Jobs"; "Forecast Accuracy" → "Track Record"
  - Brier score: inline explainer `st.expander` with plain-language table
  - Radar tab: "How to use" hint dismissable caption

### Phase 6 — Integrity & Learning Loop (v0.6, 2026-06-24)

Findings from joint architect / open-source engineer / PM review after first real
LLM accumulation run (12 predictions via Groq):

- [x] **HR-9** Citation sanitiser: `forecast._sanitize_sources()` strips hallucinated arXiv IDs and placeholder domains at parse time
- [x] **Horizon normalisation**: `forecast._normalize_horizon()` coerces `"2027"` → `"2027-Q4"`, `"2027-H1"` → `"2027-Q2"` before persisting
- [x] **Accuracy tab sources**: `judged_rationale` surfaced in resolved-predictions table so users can independently verify
- [x] **Groq rate-limit degradation**: `call_llm` detects 429 / `RateLimitError`, retries once after 60 s, falls back to `RuntimeError` with structured message rather than silent failure
- [x] **User feedback visibility**: Radar tab shows "N jobs calibrated from your feedback" badge when `field_calibration` has data, closing the perception gap
- [x] **ROOT_CAUSE contrastive pairs** in `predictions_seed.json` + `track_record_summary` WRONG entries show 280-char rationale window
- [x] **PR-aligned commit-back**: `predictions_live.jsonl` now correctly detects new/changed file via `git add` before `git diff --cached`

### Phase 7 — Live Track Record Credibility (v0.8, 2026-06-24)

Problem: seed demo data (12 resolved) and daily LLM predictions (12 open) were merged
in the UI with no origin label — users could not tell curated benchmark from real agent
performance.

- [x] **HR-11 Origin split**: Track Record tab shows separate panels for *Curated benchmark*
  (seed) and *Live LLM* with independent resolved counts and mean Brier
- [x] **Upcoming resolutions**: timeline of open live predictions sorted by
  `resolution_date`, showing criteria so users see the loop is active
- [x] **CSV `origin` column**: public download includes `seed|live` for replication
- [x] **Live-only export**: `run.py export` writes only non-seed predictions to
  `predictions_live.jsonl` (seed stays in `predictions_seed.json`)
- [x] **CI guard**: `run.py verify-export` after daily cron; fails if live DB state
  ≠ committed JSONL (catches silent resolve/export regressions)

### Phase 8 — Personalized Job Radar & Search Quality (v0.9, 2026-06-23)

Problem: search retrieval and career recommendation were conflated — e.g. a finance
process-improvement query surfacing an unrelated AI trading role. Legacy hashing-only
embeddings and description-diluted vectors produced weak bilingual matches; recommendations
also ignored user seniority (novice vs senior retrain cost) and field survey lacked tenure.

**Design principles (ranking priorities for transition paths):**

1. **Skill extensibility** — skill-vector proximity + shared skills (bridgeable gap)
2. **User fit** — experience level caps acceptable `retrain_months`; juniors favour lower-gap targets
3. **Forward demand** — scenario-driven demand under active diffusion assumptions

**Shipped pre-Phase-8 (search hotfix, not yet HR-3 compliant):**

- [x] `combined_similarity = 0.45·embed + 0.55·lexical`, multi-word token penalty, industry-only boost
- [x] Code constants `_SIMILARITY_THRESHOLD=0.42`, `_STRONG_MATCH_THRESHOLD=0.55`; sort by `combined_similarity`
- [x] Tests in `tests/test_job_radar.py`

**Phase 8 deliverables:**

- [x] **HR-12** Enforce retrieval≠recommendation in Radar UI: search → pick anchor role → rank browse/related by `transition_score`
- [x] **HR-3** Move search thresholds + embed/lex blend to `config.yaml` → `job_radar.search.*`
- [x] **User-facing tiers** on `combined_similarity`: 无匹配 (&lt; weak) / 弱 / 强 (replace misleading single green banner)
- [x] **HR-13** Add `JobFeedback.experience_level`; survey field + i18n; migration-safe default for existing rows
- [x] **Stratified field calibration** — `get_empirical_metrics()` groups by `(title, experience_level)` when n≥5; fallback to title-only
- [x] **Sidebar user profile** (session): experience level + max retrain months → override `_TRANSITION_WEIGHTS` / filter candidates
- [x] **Strong-match threshold audit** — target ~0.65–0.70 on calibrated combined score (after config move + tier labelling)
- [x] **Anchored-search UX** — when a strong search anchor is set, hide the at-risk column (weak `combined_similarity` must not surface unrelated roles, e.g. engineer → Logistics Dispatcher)

**Explicitly out of Phase 8:** prediction-crowd contributor job-title collection; Indeed/LinkedIn scraping. *(Embedding model swap delivered in v0.10 — see RELEASE_v0.10.md; stays behind `resolve_embedder()` + HR-1 dual config.)*

### Phase 9 — Job Query Calibration Agent (v0.10, 2026-06-24)

Problem: hot-role search gaps (e.g. «software developer» ≠ Software Engineer) were caught only
after user reports. Need a continuous **retrieval QA loop** that discovers queries, evaluates
KB match quality, traces gaps, and **auto-resolves safe calibration** without waiting for
manual bug reports.

**Design principles:**

1. **Retrieval QA only** — agent calibrates search anchors / aliases / KB coverage, not transition recommendations (HR-12)
2. **Simulate before mutate** — every auto-apply runs `simulate_alias_patch` / `simulate_title_alias` and must beat `sim_before`
3. **Tiered mutation policy** — `alias_patch` + `title_alias` may auto-apply when gated; `kb_profile_new` always queues to `pending/` (HR-5)
4. **CORE guard in CI** — P0 regressions fail `run.py query-agent audit`

**Discover sources (`discover_queries`):**

| Source | Config flag | Purpose |
|--------|-------------|---------|
| `CORE_HOT_ROLE_QUERIES` | `discover.include_core` | Regression guardrail for high-traffic titles (EN + zh) |
| `data/query_seed.json` | `discover.include_seed` | Curated long-tail / edge-case queries |
| `JobFeedback.job_title` | `discover.include_feedback_titles` | Real user search intent from field survey |

**Auto-apply gates (`job_query_agent.auto_apply`):**

- `enabled: true` (daily cron); CI `audit` never mutates
- Allowed types: `alias_patch` (→ `jobs_kb.json` `search_aliases`), `title_alias` (→ `job_radar.search.title_aliases`)
- `min_sim_after` ≥ `tier_weak` (default 0.55); CORE queries must resolve to `expected_id`
- `alias_patch` requires strict improvement over `sim_before`
- `max_rounds` (default 3) — reload KB between rounds

**P0 delivered:**

- [x] `services/job_query_agent/` — `discover`, `evaluate`, `propose`, `simulate`, `apply`, `traces`, `audit`, `loop`
- [x] `run.py query-agent audit|once|run|apply|ingest-logs`
- [x] `config.yaml` → `job_query_agent.*` + `job_radar.search.title_aliases`; seed file `data/query_seed.json`
- [x] Hot-role KB entries: `tech_product_manager`, `tech_data_scientist`, `tech_project_manager`; expanded `tech_software_eng` aliases
- [x] CI step: `python run.py query-agent audit` after pytest
- [x] Daily cron: `query-agent run` commits `jobs_kb.json` / `config.yaml` when auto-apply makes changes
- [x] Traces: `data/query_agent_traces.jsonl` (gitignored)
- [x] Tests: `tests/test_job_query_agent.py`, `test_anchored_search_hides_unrelated_at_risk` in `tests/test_radar_render.py`

**Phase 9 backlog:**

- [x] P1: `query-agent run` — simulate + auto-apply `alias_patch` / `title_alias` (gated); manual `pending/` for `kb_profile_new`
- [x] P1: `query-agent apply` — merge human-approved proposals from `pending/job_calibration/`
- [x] P2: HF/Radar search log ingest (`data/radar_search_log.jsonl`) + frequency-weighted discovery
- [x] P3: `kb_profile_new` → LLM/cache KB append via `apply` + gated auto in `run`

### Phase 9b — Semantic job search (v0.10, 2026-06-24)

Production search upgraded from hashing-only to **multilingual sentence embeddings** while CI remains offline.

- [x] `SentenceEmbedder` — `paraphrase-multilingual-MiniLM-L12-v2`; `_job_embed_title()` (title + aliases only)
- [x] `resolve_embedder(search_cfg)` — `config.yaml` → `sentence_transformers`; `config.ci.yaml` → `hashing`
- [x] Lexical fix: preserve 2-char abbreviations (`ml`, `hr`, `qa`, `gp`)
- [x] KB alias corrections + seed tuning; **114–115/115 queries OK**, 0 P0
- [x] Dockerfile pre-downloads MiniLM for HF Space

See [RELEASE_v0.10.md](./RELEASE_v0.10.md) for score lift table and commit list.

---

## 6. Success metrics

| Metric | Target |
|--------|--------|
| Offline test pass rate | 100% |
| Mean Brier (resolved n≥30) | < 0.20 |
| OOD fires → confidence downshift | Qualitative audit |
| P0 bugs open | 0 |
| MCP read tools documented | Phase 3 exit |
| LLM-generated sources with hallucinated arXiv IDs | 0 (HR-9) |
| Resolved predictions surviving cache eviction | 100% (HR-10) |
| `predictions_live.jsonl` committed per real-LLM cron run | ✅ (daily) |
| Track Record UI shows seed vs live origin | HR-11 (Phase 7) |
| Live resolved count visible independently of seed | Phase 7 exit |
| Search strong-match precision (manual audit, n≥20 queries) | ≥ 80% relevant anchor role (Phase 8) |
| Field survey includes experience level | HR-13 (Phase 8) |
| Transition cards respect user retrain cap when profile set | Phase 8 |
| `query-agent audit` passes in CI (CORE + seed) | Phase 9 |
| `query-agent run` daily with zero P0 regressions | Phase 9 |
| Search gaps auto-closed via alias/title_alias (weekly) | Qualitative — trace + commit log |
| LLM fallback rate on top queries (logged) | Phase 9 P2 |

---

## 7. Out of scope (v0.10)

- Auto-publishing with `require_review: false` as default
- Financial advice positioning
- Real-money prediction markets
- Commercial API without BUSL commercial license
- Using raw embedding cosine (~0.7) as user-facing "similarity" without combined score + tier labels
- Collecting job title / tenure on **prediction** crowd submissions (HR-13 applies to field feedback only)
- Indeed/LinkedIn job scraping for query-agent discovery (BLS/O*NET + logs + feedback only)
