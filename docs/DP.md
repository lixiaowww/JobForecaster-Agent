# Design Proposal (DP) — forecaster-agent

**Version:** 0.9 (Personalized Job Radar & Search Quality)  
**Last updated:** 2026-06-23

Architectural design implementing [PRD.md](./PRD.md) under Harness Engineering standards.

---

## 1. Layout & import strategy

The project uses a **flat root layout** (not `src/` yet). All modules live at repository root. Imports follow one rule:

```python
try:
    from schemas import Prediction      # script / pytest entry
except ImportError:
    from .schemas import Prediction     # optional package import
```

**Never** add `/home/sean` to `sys.path` (symlink collision with duplicate SQLAlchemy metadata). Use `paths.PROJECT_ROOT` instead.

```
forecaster-agent/
├── config.yaml
├── paths.py                 # PROJECT_ROOT constant
├── run.py                   # CLI entry
├── loop.py                  # orchestrator
├── forecast.py              # LLM seam + prediction/judge
├── evolution.py             # case library, PCA/GMM, OOD
├── crowd.py                 # crowd gate
├── job_radar.py             # hybrid RAG
├── registry.py              # SQLite registry
├── schemas.py               # SQLModel entities + engine
├── services/
│   └── read_model.py        # read-only API seam (MCP/REST target)
├── dashboard.py             # Streamlit UI
├── tests/                   # offline harness (HR-1)
├── data/
│   ├── forecaster.db
│   └── jobs_kb.json
└── docs/
    ├── PRD.md
    └── DP.md
```

---

## 2. Orchestrator data flow (v0.5)

```
ingest.gather_signals()
        │
        ▼
evolution.build_prior(scenario from config)
        │ EvolutionPrior.to_prompt_context()
        ▼
forecast.generate_predictions(signals, track, evolution_prior=...)
        │
        ▼
registry.add_many()  ── dedup by fingerprint
        │
        ▼
publish.publish_or_queue(require_review)
```

### Loop pseudocode

```python
def run_cycle(cfg):
    reg = Registry()
    resolve_due(reg, cfg["model"])
    signals = ingest.gather_signals(...)
    prior_ctx = evolution.build_prior(
        current_scenario=cfg["evolution"].get("scenario") or CURRENT_AI_SCENARIO,
        n_bootstrap=cfg["evolution"]["n_bootstrap"],
    ).to_prompt_context()
    preds = forecast.generate_predictions(
        signals, reg.track_record_summary(),
        evolution_prior=prior_ctx, ...)
    new = reg.add_many(preds)
    publish.publish_or_queue(..., require_review=cfg["require_review"])
```

**Not yet in loop:** Discord/Telegram bots — REST API only for Phase 2.

---

## 3. Harness interfaces

### 3.1 Embedder (`crowd.py`)

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- **Production:** Voyage / OpenAI / sentence-transformers
- **Harness:** `HashingEmbedder` (deterministic MD5 bag-of-tokens)

### 3.2 SoundnessJudge (`crowd.py`)

- **Production:** `LLMSoundnessJudge`
- **Harness:** `HeuristicSoundnessJudge`

### 3.3 LLM (`forecast.py`)

Single seam:

```python
def call_llm(system: str, user: str, *, max_tokens: int, model: str | None) -> str: ...
```

Priority: `GROQ_API_KEY` → `ANTHROPIC_API_KEY` → `RuntimeError`.

Future: `MockLLMClient` behind same signature for fully offline `run.py once --mock`.

---

## 4. Persistence

### 4.1 SQLite (`schemas.py`)

```python
DATABASE_URL = "sqlite:///data/forecaster.db"
```

| Table | Purpose |
|-------|---------|
| `prediction` | Core forecasts |
| `contribution` | Crowd submissions (Phase 2) |
| `predictionbet` | Virtual prediction market |
| `jobfeedback` | Career survey + 6-month follow-up (`JobFeedback`; Phase 8 adds `experience_level`) |

`registry_path` in old configs is **deprecated**; use `database_path` for documentation only.

### 4.2 Static publish outputs

| Backend | Output |
|---------|--------|
| `FilePublisher` | `site/index.html`, `site/feed.json` |
| `WebhookPublisher` | Slack/Discord JSON |
| `GitPublisher` | commit + push Pages repo |

Review gate writes to `pending/*.md` + sidecar `.json`.

---

## 5. Services layer (read model)

`services/read_model.py` is the **only** module future MCP/REST servers should call for reads:

| Function | Backing |
|----------|---------|
| `get_scoreboard()` | `Registry.scoreboard()` |
| `get_ood_assessment(scenario)` | `evolution.build_prior()` |
| `search_jobs(query, industry, scenario)` | `job_radar.*` |
| `list_open_predictions()` | `Registry.open_predictions()` |

**Rule:** No Streamlit imports in `services/`. No LLM calls in read model.

---

## 6. Phase 3 — MCP tools (implemented)

| MCP Tool | Handler | Maps to |
|----------|---------|---------|
| `get_calibration_scoreboard` | `handle_get_calibration_scoreboard` | `services.get_scoreboard()` |
| `get_ood_assessment` | `handle_get_ood_assessment` | `evolution.build_prior()` |
| `search_jobs` | `handle_search_jobs` | `job_radar.*` |
| `list_open_predictions` | `handle_list_open_predictions` | `Registry.open_predictions()` |

Entry point: `mcp_server.py` (stdio). Configuration: `docs/MCP.md`.

Handlers live in `services/mcp_handlers.py` — testable without MCP runtime (HR-1).

### Phase 3b — REST (implemented)

| REST endpoint | Handler |
|---------------|---------|
| `GET /v1/scoreboard` | `handle_get_calibration_scoreboard` |
| `GET/POST /v1/ood` | `handle_get_ood_assessment` |
| `GET/POST /v1/jobs/search` | `handle_search_jobs` |
| `GET /v1/predictions/open` | `handle_list_open_predictions` |

Entry point: `api_server.py`. Configuration: `docs/API.md`, `config.yaml` → `api`.

Auth: `FORECASTER_API_KEY` env (optional). Rate limit: `api.rate_limit_per_minute`.

Write endpoints (`POST /contributions`, `POST /forecast`) require Phase 2 + BUSL review.

---

## 7. Job Radar — search vs recommendation (HR-12)

Job Radar exposes **two independent scoring pipelines**. They must not be merged in UI or API responses.

### 7.1 Search retrieval (query → occupation anchor)

**Purpose:** find which KB occupation best matches a free-text query (user's current role, industry keyword, etc.).

Location: `job_radar._score_job_match()`, `_apply_search_scores()`, `find_best_match()`

```
combined = w_emb · cosine(q, job_text) + w_lex · lexical_overlap(q, job_text)
         × multi_word_penalty          (if ≥2 query tokens and too few hits)
         + industry_only_boost         (optional, industry-only queries)
```

Current code defaults (move to `config.yaml` in Phase 8, HR-3):

| Constant | Value | Meaning |
|----------|-------|---------|
| `w_emb` / `w_lex` | 0.45 / 0.55 | Embedder is `HashingEmbedder` in tests — **not** comparable to OpenAI cosine ~0.7 |
| `_SIMILARITY_THRESHOLD` | 0.42 | Below → no confident KB match; LLM KB expansion path |
| `_STRONG_MATCH_THRESHOLD` | 0.55 | Above → strong search hit banner (Phase 8: tier labels 无匹配/弱/强) |

Multi-word penalty: queries with ≥2 tokens require hits on at least `max(2, ⌈n/2⌉)` tokens or score × 0.45.

**Not a transition recommendation.** A high `combined_similarity` only means text overlap with an occupation profile.

### 7.2 Scenario impact (structural + semantic hybrid)

Unchanged — ranks occupations under an AI diffusion scenario:

$$\text{hybrid}_j = \alpha \cdot \text{impact}_j + \beta \cdot \text{sim}(q, j)$$

$$\text{impact}_j = \text{base\_demand\_trend}_j + \sum_i s_i \cdot w_{j,i}$$

Config: `job_radar.alpha`, `job_radar.beta` (HR-3).

Used for timeline / impact views, not for "should I switch to this role?".

### 7.3 Transition recommendation (`compute_transition_paths`)

**Purpose:** given an **anchor occupation** (selected from search or dropdown), rank target roles by career-switch feasibility.

Default weights (`_TRANSITION_WEIGHTS`, override via `config.yaml` → `job_radar.transition.*`):

| Component | Weight | Signal |
|-----------|--------|--------|
| `skill` | 0.40 | 1 − normalised Euclidean distance on 8-dim skill vectors |
| `overlap` | 0.15 | Jaccard on `required_skills` |
| `risk` | 0.25 | `displacement_risk_current − displacement_risk_target` (≥ 0) |
| `demand` | 0.20 | Normalised scenario `impact_score` of target |

Filters: exclude self; exclude `category == at_risk` targets.

Phase 8 personalization (planned): session profile `{experience_level, max_retrain_months}` adjusts weights and filters candidates whose `retrain_months` exceed the cap; juniors up-weight low skill-gap targets.

**UI flow (target):**

```
User query ──► find_best_match() ──► anchor role
                      │
                      ▼
         compute_transition_paths(anchor, all_jobs, scenario)
                      │
                      ▼
              transition cards (top_k)
```

Search result lists (browse mode) should re-rank by `transition_score` **after** anchor is fixed — not by `combined_similarity` alone.

### 7.4 Field feedback crowd (`JobFeedback`) — HR-13

Separate from prediction crowd (`contribution` table + `services/crowd_service.py`).

| Field | Today | Phase 8 |
|-------|-------|---------|
| `job_title` | ✅ KB dropdown → canonical English title | unchanged |
| `industry`, `status`, `confidence`, `transition_target` | ✅ | unchanged |
| `experience_level` | ❌ | ✅ `junior` \| `mid` \| `senior` (or years-in-role bucket) |

Aggregation: `get_empirical_metrics()` → `compute_field_calibration()` in `services/job_market.py`.

Today: group by `job_title` only; `min_responses=5`, shrinkage, `max_delta=0.15`.

Phase 8: prefer `(title, experience_level)` cell when n≥5; else fall back to title-only pool.

Survey UI: `ui/tabs/radar.py` form — map localized labels back to canonical titles (existing pattern).

**Prediction crowd does not collect title/tenure** unless a future expert-weighting feature is scoped separately.

## 8. Test harness

```
tests/
├── test_crowd.py       # gate decisions with behavioural assertions
├── test_evolution.py   # case library, OOD, PCA determinism
├── test_registry.py    # dedup, Brier, due(), scoreboard
├── test_mcp_handlers.py
└── test_api.py         # REST /v1 via TestClient
```

Run: `python -m pytest tests/ -v` — **no network, no API key**.

CI: `.github/workflows/ci.yml` — Python 3.11 + 3.12 matrix.

---

## 9. Known technical debt

| Item | Priority | Status |
|------|----------|--------|
| `dashboard.py` monolith (~1150 LOC) | P1 | ✅ 104-LOC orchestrator + `ui/tabs/*` |
| Discord/Telegram crowd bots | P2 | ✅ `bots/` |
| No `MockLLMClient` for offline `run.py once` | P2 | open |
| `src/` package layout + Poetry lock | P3 | open |
| Alembic migrations | P3 | open |
| SQLite engine global singleton, poor test isolation | P3 | ✅ `make_engine()` + `Registry(engine=…)` + `isolated_registry` fixture |
| Search thresholds hard-coded in `job_radar.py` | P0 | ✅ Phase 8 → `config.yaml` (HR-3) |
| Search UI conflated with transition ranking | P1 | ✅ Phase 8 (HR-12) |
| `JobFeedback` missing experience level | P1 | ✅ Phase 8 (HR-13) |
| No session user profile for retrain cap | P2 | ✅ Phase 8 |

---

## 10. v0.6 Design additions (Integrity & Learning Loop)

### 10.1 Citation sanitiser (HR-9)

Location: `forecast._sanitize_sources(sources: list[str]) -> list[str]`

Rules applied at `_parse_json` time before a `Prediction` is persisted:

| Check | Action |
|-------|--------|
| Not a string or empty | drop |
| Doesn't start with `http://` or `https://` | drop |
| Domain is `example.com`, `example.org`, or `placeholder` | drop |
| arXiv URL whose YYMM is in the future | drop (hallucinated) |
| All other URLs | keep as-is (no live HEAD check, stays offline-safe) |

Tests: `tests/test_forecast_quality.py::test_sanitize_sources`

### 10.2 Horizon normalisation (HR-consistent formatting)

Location: `forecast._normalize_horizon(h: str) -> str`

| Input | Output | Rule |
|-------|--------|------|
| `"2027"` | `"2027-Q4"` | bare year → year-end quarter |
| `"2027-H1"` | `"2027-Q2"` | half-year → closing quarter |
| `"2027-H2"` | `"2027-Q4"` | half-year → closing quarter |
| `"2027-Q3"` | `"2027-Q3"` | already canonical, pass through |

Applied in `_parse_json` alongside `_sanitize_sources`.

Tests: `tests/test_forecast_quality.py::test_normalize_horizon`

### 10.3 Resolved-state durability (HR-10)

`run.py export` serialises the full `Prediction` via `model_dump_json()`, which
includes `status`, `outcome`, `brier`, `resolved_at`. On reload,
`Prediction.model_validate_json(line)` restores the resolved state. `_coerce`
in `dashboard_seed.py` back-fills missing `brier` / `resolved_at` only when the
status already indicates resolution, so it is idempotent.

Invariant test: `tests/test_dashboard_seed.py::test_ensure_demo_registry_loads_seed_plus_live`
already asserts both seed and live statements are present after a round-trip.

### 10.4 Groq rate-limit degradation (P2-A)

`forecast.call_llm` wraps the Groq call in a retry block:

```
try:
    return _call_once(system, user, max_tokens, model)
except RateLimitError:
    time.sleep(60)
    return _call_once(system, user, max_tokens, model)
except Exception as exc:
    raise RuntimeError(f"LLM call failed: {exc}") from exc
```

- One retry with 60-second back-off avoids wasted runs on transient 429.
- Still raises after one retry so CI never hangs forever.
- `RateLimitError` import: `from groq import RateLimitError` (guarded with
  `ImportError` fallback to keep the harness offline-safe).

### 10.5 User feedback visibility (P2-B)

`ui/tabs/radar.py` shows a `st.info` badge with count of calibrated jobs when
`_field_recs` (from `compute_field_calibration`) is non-empty:

```
ℹ️  3 occupations calibrated from real user feedback (N=47 responses)
```

This closes the perception gap: users know their survey answers matter.

---

## 12. v0.8 Design additions (Live Track Record Credibility)

### 12.1 Origin classification (HR-11)

Location: `services/track_record.py`

| Function | Purpose |
|----------|---------|
| `seed_prediction_ids(seed_path)` | Load fingerprint set from `predictions_seed.json` |
| `prediction_origin(p, seed_ids)` | Returns `"seed"` if `p.id` ∈ seed_ids else `"live"` |
| `partition_by_origin(preds, seed_ids)` | Split into `(seed_preds, live_preds)` |
| `scoreboard_subset(preds)` | Same shape as `Registry.scoreboard()` for a filtered list |
| `upcoming_resolutions(preds, *, limit=10)` | Open/due preds sorted by `resolution_date` asc |

**Rule:** seed IDs are computed once per dashboard render from the committed seed file;
live predictions are everything else in the registry (including cron-generated rows).

### 12.2 Live-only export

`run.py export` filters with `partition_by_origin` before writing JSONL.
Seed data never enters `predictions_live.jsonl` — it remains in `predictions_seed.json`.

### 12.3 Export verification (CI guard)

`run.py verify-export`:

1. Load live predictions from DB (`partition_by_origin`)
2. Load `predictions_live.jsonl`
3. For each live id, assert matching `status`, `outcome`, `brier` in JSONL
4. Exit code 1 on any mismatch (prevents silent resolve/export regression)

Called in `.github/workflows/daily-pages.yml` immediately after `export`.

### 12.4 Track Record UI layout

```
┌─ Curated benchmark (seed) ─────────────────┐
│  resolved N | mean Brier X | table         │
└────────────────────────────────────────────┘
┌─ Live LLM predictions ─────────────────────┐
│  open N | resolved N | mean Brier Y        │
│  ▶ Upcoming resolutions (live only)        │
│  resolved table (live only)                │
└────────────────────────────────────────────┘
```

CSV download includes `origin` column on every row.

---

## 13. v0.9 Design additions (Personalized Job Radar — implemented)

### 13.1 Harness invariants

| ID | Enforcement location |
|----|---------------------|
| **HR-12** | `ui/tabs/radar.py` — search banner uses `combined_similarity`; transition expander uses `compute_transition_paths` only; tests assert no cross-ranking |
| **HR-13** | `schemas.JobFeedback.experience_level`; survey + `get_empirical_metrics()` stratification |
| **HR-3** | New `config.yaml` keys under `job_radar.search` and `job_radar.personalization` |

### 13.2 Config schema (to add)

```yaml
job_radar:
  alpha: 0.6
  beta: 0.4
  search:
    embed_weight: 0.45
    lex_weight: 0.55
    multi_word_penalty: 0.45
    tier_no_match: 0.42      # was _SIMILARITY_THRESHOLD
    tier_weak: 0.55          # was _STRONG_MATCH_THRESHOLD
    tier_strong: 0.65        # Phase 8 audit target
  transition:
    skill: 0.40
    overlap: 0.15
    risk: 0.25
    demand: 0.20
  personalization:
    junior_retrain_cap_months: 6
    mid_retrain_cap_months: 12
    senior_retrain_cap_months: 24
```

### 13.3 Experience level → transition weights (sketch)

Pure function in `job_radar.py` (HR-2 testable):

```python
def personalization_weights(
    base: dict,
    *,
    experience_level: str,
    max_retrain_months: int | None = None,
) -> dict:
    ...
```

- **Junior:** increase `overlap` weight, filter targets with `retrain_months > cap`
- **Senior:** increase `demand` + `risk` weights slightly; allow higher retrain cap
- Defaults when profile unset: current `_TRANSITION_WEIGHTS`

### 13.4 Test plan (offline, HR-1)

| Test | Asserts |
|------|---------|
| `test_score_job_match_multi_word_penalty` | ✅ exists |
| `test_find_best_match_finance_not_ai_trading` | finance query ≠ unrelated AI role (regression) |
| `test_transition_paths_respect_retrain_cap` | Phase 8 — filtered when profile set |
| `test_empirical_metrics_stratified_by_experience` | Phase 8 — `(title, level)` grouping |
| `test_search_tiers_from_config` | Phase 8 — thresholds read from config stub |

### 13.5 i18n keys (Phase 8)

Add to `ui/i18n.py`: `radar_fb_experience`, `radar_match_tier_none`, `radar_match_tier_weak`, `radar_match_tier_strong`, `radar_profile_experience`, `radar_profile_retrain_cap`.

---

## 14. v0.10 Design additions (Job Query Calibration Agent)

### 14.1 Module layout

```
services/job_query_agent/
├── discover.py    # core_hot, query_seed.json, JobFeedback titles
├── evaluate.py    # tier + P0 regression classification (HR-2 pure)
├── propose.py     # CalibrationProposal → pending/job_calibration/
├── traces.py      # JSONL append-only
└── audit.py       # orchestrates cycle; raises on P0 failure
```

### 14.2 Audit flow

```
discover_queries(cfg)
    → for each query: find_best_match + search_match_tier
    → evaluate_query → append_trace
    → optional queue_proposal (once subcommand)
    → fail if p0_regression or weak_core (configurable)
```

### 14.3 Proposal types

| type | pending example | apply (P1) |
|------|-----------------|------------|
| `alias_patch` | add `search_aliases` | patch `jobs_kb.json` |
| `kb_profile_new` | unknown hot query | human review + KB append |
| `title_alias_map` | normalize map entry | `config.yaml` or `job_radar` map |

### 14.4 CLI

```bash
python run.py query-agent audit   # CI: exit 1 on P0 regression
python run.py query-agent once    # audit + queue proposals
```

### 14.5 Config (`config.yaml`)

See `job_query_agent` block: `discover.*`, `evaluate.fail_on_weak_core`, `review.pending_dir`, `traces_path`.

---

## 11. Security & compliance defaults

- `require_review: true` — never change default in repo
- Disclaimer in every published report (`publish.DISCLAIMER`)
- OOD warning must appear in forecast prompt when `is_ood`
- BUSL-1.1 — commercial API deployment needs license
