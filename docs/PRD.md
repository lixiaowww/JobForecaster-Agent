# Product Requirement Document (PRD) — forecaster-agent

**Version:** 0.8 (Live Track Record Credibility)  
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
| 65 occupation profiles, 13 industries | ✅ |
| Hybrid RAG (α·structural + β·semantic) | ✅ |
| Career transition paths | ✅ |
| BLS verification layer | ✅ |
| Prediction market UI | ✅ |
| LLM KB expansion for unknown titles | ✅ (needs API key) |

### 2.5 Read model / external integration seam (`services/read_model.py`)

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

---

## 4. Configuration (`config.yaml`)

| Key | Purpose |
|-----|---------|
| `database_path` | Documented SQLite location (engine in `schemas.py`) |
| `evolution.n_bootstrap` | GMM bootstrap iterations (use `10` in tests) |
| `evolution.scenario` | Optional override of `CURRENT_AI_SCENARIO` |
| `job_radar.*` | Hybrid RAG weights and KB path |
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

---

## 7. Out of scope (v0.8)

- Auto-publishing with `require_review: false` as default
- Financial advice positioning
- Real-money prediction markets
- Commercial API without BUSL commercial license
