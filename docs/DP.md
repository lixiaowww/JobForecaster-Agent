# Design Proposal (DP) — forecaster-agent

**Version:** 0.11 (Self-Evolving Transition Recommendations)  
**Last updated:** 2026-06-24

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
├── job_radar.py             # hybrid RAG + search retrieval + transition paths
├── registry.py              # SQLite registry
├── schemas.py               # SQLModel entities + engine
├── services/
│   ├── read_model.py        # read-only API seam (MCP/REST target)
│   ├── job_query_agent/     # Phase 9: retrieval QA loop
│   │   ├── discover.py
│   │   ├── evaluate.py
│   │   ├── propose.py
│   │   ├── simulate.py
│   │   ├── apply.py
│   │   ├── loop.py
│   │   ├── traces.py
│   │   └── audit.py
│   └── transition_evaluator/  # Phase 10: LLM-as-judge self-evolution
│       ├── __init__.py
│       ├── cache.py           # persistent data/transition_eval_cache.json
│       └── evaluate.py        # evaluate_pair + run_evaluation_pass + _promote_to_kb
├── dashboard.py             # Streamlit UI
├── tests/                   # offline harness (HR-1), 190 tests
├── data/
│   ├── forecaster.db
│   ├── jobs_kb.json
│   ├── query_seed.json               # Phase 9 seed queries (115+)
│   └── transition_eval_cache.json    # Phase 10 cached LLM scores
├── pending/
│   └── job_calibration/     # Phase 9 human-review proposals
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

### 3.1 Embedder (`crowd.py` + `job_radar.py`)

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

**Crowd gate (`crowd.py`):**

- **Production:** Voyage / OpenAI / sentence-transformers
- **Harness:** `HashingEmbedder` (deterministic MD5 bag-of-tokens)

**Job Radar search (`job_radar.resolve_embedder`):**

| `job_radar.search.embedder` | Class | Use |
|-----------------------------|-------|-----|
| `sentence_transformers` (default in `config.yaml`) | `SentenceEmbedder` | HF Space / local dashboard — `paraphrase-multilingual-MiniLM-L12-v2` |
| `hashing` (default in `config.ci.yaml`) | `RadarHashingEmbedder` | CI / pytest (HR-1 offline, no model download) |

Semantic path embeds **`_job_embed_title(job)`** (title + `title_zh` + `search_aliases` only).
Lexical path still uses the full **`_job_embed_text(job)`** document (description, skills, industry).

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
combined = w_emb · cosine(q, job_title_vec) + w_lex · lexical_overlap(q, job_full_text)
         × multi_word_penalty          (if ≥2 query tokens and too few hits)
         + industry_only_boost         (optional, industry-only queries)
```

Where `job_title_vec` comes from `SentenceEmbedder(_job_embed_title)` in production, or
`RadarHashingEmbedder(_job_embed_text)` when `embedder: hashing`.

Current defaults live in `config.yaml` → `job_radar.search.*` (HR-3):

| Key | Default | Meaning |
|-----|---------|---------|
| `embedder` | `sentence_transformers` | `hashing` in `config.ci.yaml` for offline CI |
| `embed_weight` / `lex_weight` | 0.45 / 0.55 | Blend semantic cosine + lexical overlap |
| `tier_no_match` | 0.42 | Below → no confident KB match; LLM KB expansion path |
| `tier_weak` | 0.55 | Weak tier ceiling; also `query-agent` `min_sim_after` default |
| `tier_strong` | 0.65 | Strong search hit banner |
| `title_aliases` | `{}` + code `_QUERY_TITLE_ALIASES` | `normalize_search_query()` merges file + built-in map |

Multi-word penalty: queries with ≥2 tokens require hits on at least `max(2, ⌈n/2⌉)` tokens or score × `multi_word_penalty` (0.45).

**Lexical tokens:** `_SEARCH_TOKEN` matches ASCII alphanumerics and CJK runs (`[\u4e00-\u9fff]{2,}`).
`_query_tokens()` keeps tokens **≥ 2 characters** (preserves `ml`, `hr`, `qa`, `gp`; drops single-char ASCII only).

**Bilingual semantic:** `paraphrase-multilingual-MiniLM-L12-v2` embeds query and title documents in a shared space — Chinese queries like `护士` / `人工智能工程师` match without per-query manual aliases.

**Hot-role guardrail:** `CORE_HOT_ROLE_QUERIES` — CI + query-agent audit assert each pair hits `expected_id` with `sim ≥ tier_weak`.

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

Phase 8 personalization (implemented): session profile `{experience_level, max_retrain_months}` in `ui/sidebar.py` adjusts weights via `personalization_weights()` and filters candidates whose `retrain_months` exceed the cap; juniors up-weight low skill-gap targets.

**UI flow (implemented):**

```
User query ──► find_best_match() ──► anchor role
                      │
                      ▼
         compute_transition_paths(anchor, all_jobs, scenario)
                      │
                      ▼
              transition cards (top_k)
```

Search result lists (browse mode) re-rank by `transition_score` **after** anchor is fixed — not by `combined_similarity` alone.

**Anchored-search at-risk suppression (HR-12 UX, v0.10):**

When `search_query` resolves to a strong anchor (`anchor_job` set), `ui/tabs/radar.py` clears
`at_risk_list` — weak text scores must not show unrelated at-risk occupations (regression:
`software engineer` → Logistics Dispatcher at sim≈0.17). User sees
`radar_matrix_at_risk_anchor_skip` caption and transition paths from the anchor instead.

Test: `tests/test_radar_render.py::test_anchored_search_hides_unrelated_at_risk`

### 7.4 Field feedback crowd (`JobFeedback`) — HR-13

Separate from prediction crowd (`contribution` table + `services/crowd_service.py`).

| Field | Phase 8 |
|-------|---------|
| `job_title` | ✅ KB dropdown → canonical English title |
| `industry`, `status`, `confidence`, `transition_target` | ✅ |
| `experience_level` | ✅ `junior` \| `mid` \| `senior` |

Aggregation: `get_empirical_metrics()` → `compute_field_calibration()` in `services/job_market.py`.

Today: prefer `(title, experience_level)` cell when n≥`min_stratified_responses`; else fall back to title-only pool.

Survey UI: `ui/tabs/radar.py` form — map localized labels back to canonical titles (existing pattern).

**Prediction crowd does not collect title/tenure** unless a future expert-weighting feature is scoped separately.

## 8. Test harness

```
tests/
├── test_crowd.py           # gate decisions with behavioural assertions
├── test_evolution.py       # case library, OOD, PCA determinism
├── test_registry.py        # dedup, Brier, due(), scoreboard
├── test_job_radar.py       # search tiers, transition paths, CORE hot roles
├── test_job_query_agent.py # Phase 9 audit / simulate / apply / loop
├── test_radar_render.py    # Streamlit smoke + anchored at-risk regression
├── test_mcp_handlers.py
└── test_api.py             # REST /v1 via TestClient
```

Run: `python -m pytest tests/ -v` — **no network, no API key**.

CI: `.github/workflows/ci.yml` — Python 3.11 + 3.12 matrix; post-pytest `query-agent audit`.
Daily: `.github/workflows/daily-pages.yml` — forecast cycle + `query-agent run` + KB/config commit.

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
| Hot-role search gaps caught only by user reports | P0 | ✅ Phase 9 query-agent |
| No automated alias calibration loop | P1 | ✅ `query-agent run` + daily cron |
| Anchored search shows unrelated at-risk roles | P1 | ✅ HR-12 UX fix + render test |

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

### 13.2 Config schema (implemented)

```yaml
job_radar:
  alpha: 0.6
  beta: 0.4
  search:
    embedder: sentence_transformers   # hashing in config.ci.yaml (HR-1)
    embed_weight: 0.45
    lex_weight: 0.55
    multi_word_penalty: 0.45
    industry_only_boost: 0.08
    tier_no_match: 0.42
    tier_weak: 0.55
    tier_strong: 0.65
    title_aliases: {}          # merged with _QUERY_TITLE_ALIASES in code
  transition:
    skill: 0.40
    overlap: 0.15
    risk: 0.25
    demand: 0.20
  personalization:
    junior_retrain_cap_months: 6
    mid_retrain_cap_months: 12
    senior_retrain_cap_months: 24
    min_stratified_responses: 5
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

Add to `ui/i18n.py`: `radar_fb_experience`, `radar_match_tier_*`, `radar_profile_*`, `radar_matrix_at_risk_anchor_skip`.

---

## 14. v0.10 Design additions (Job Query Calibration Agent — implemented)

### 14.1 Module layout

```
services/job_query_agent/
├── discover.py    # core_hot, query_seed.json, JobFeedback titles
├── evaluate.py    # tier + P0 regression classification (HR-2 pure)
├── propose.py     # CalibrationProposal → pending/job_calibration/
├── search_log.py  # record + aggregate Radar/HF search JSONL (P2)
├── simulate.py    # dry-run alias/title_alias/kb_profile_new before apply
├── apply.py       # patch KB/config; kb_profile_new via LLM cache; run_apply_pending
├── loop.py        # multi-round discover → auto-apply → re-check
├── traces.py      # JSONL append-only (gitignored path)
└── audit.py       # single-pass audit; raises on P0 failure
```

### 14.2 Evaluation verdicts

`evaluate_query(discovered, jobs)` → `QueryVerdict`:

| `status` | Condition | Agent action |
|----------|-----------|--------------|
| `ok` | Match tier acceptable | trace only |
| `p0_regression` | CORE query: `best_id ≠ expected_id` | **CI fail** |
| `weak_core` | CORE query: correct id but `sim < tier_weak` | propose `alias_patch`; auto-apply if sim improves |
| `kb_gap` | Non-core: `sim < tier_no_match` | propose `kb_profile_new` → **always queue** |
| `weak_match` | Non-core: weak tier | propose `alias_patch` to `best_id` |

### 14.3 Proposal types

| type | payload | persist target | auto-apply |
|------|---------|----------------|------------|
| `alias_patch` | `add_aliases: [query]` | `jobs_kb.json` → `search_aliases` | ✅ gated |
| `title_alias` | `canonical: <KB title>` | `config.yaml` → `job_radar.search.title_aliases` | ✅ gated |
| `kb_profile_new` | `query`, `nearest_id` | `generate_job_profile_via_llm` → `jobs_kb.json` | ✅ gated (`min_search_log_occurrences`) or `query-agent apply` |

### 14.4 Closed-loop flow (`loop.run_calibration_cycle`)

```
for round in 1..max_rounds:
    jobs = load_knowledge_base()
    for item in discover_queries(cfg):
        verdict = evaluate_query(item, jobs)
        append_trace(...)
        if verdict.ok: continue
        proposal = propose_from_verdict(verdict)
        sim_after = simulate(proposal)
        if can_auto_apply(sim_before, sim_after, expected_id):
            apply_proposal()          # writes KB or config
        else:
            queue_proposal(pending/)  # skipped when --dry-run
    break if no auto_applies this round
return final audit summary (no raise; caller may exit 1 on P0)
```

`can_auto_apply` rules (`apply.py`):

- `auto_apply.enabled` and `proposal.type` ∈ `auto_apply.types`
- `sim_after ≥ min_sim_after` (default = `tier_weak`)
- CORE: `best_id_after == expected_id`; `target_id == expected_id`
- `alias_patch`: `sim_after > sim_before`

### 14.5 Audit flow (CI — read-only)

```
discover_queries(cfg)
    → for each query: find_best_match + search_match_tier
    → evaluate_query → append_trace
    → optional queue_proposal (once subcommand only)
    → raise AssertionError if p0_regression or weak_core
```

### 14.6 CLI

```bash
python run.py query-agent audit              # CI: exit 1 on P0 / weak-core
python run.py query-agent once               # audit + queue proposals (no auto-apply)
python run.py query-agent run                # closed loop: simulate + auto-apply safe fixes
python run.py query-agent run --dry-run
python run.py query-agent apply              # apply all pending/job_calibration/*.json
python run.py query-agent ingest-logs path.jsonl   # merge HF export into search log
python run.py query-agent transition-eval [N]      # Phase 10: LLM-evaluate up to N pairs
```

| Workflow | Step |
|----------|------|
| `.github/workflows/ci.yml` | `pytest` → `query-agent audit` |
| `.github/workflows/daily-pages.yml` | `query-agent run` with `GROQ_API_KEY` → commit `jobs_kb.json` / `config.yaml` / search log |

### 14.7 Config (`config.yaml`)

```yaml
job_query_agent:
  enabled: true
  traces_path: data/query_agent_traces.jsonl   # .gitignore
  discover:
    include_core: true
    include_seed: true
    seed_path: data/query_seed.json
    include_feedback_titles: true
    feedback_min_responses: 1
    max_queries_per_run: 200
  evaluate:
    fail_on_weak_core: true
  review:
    require_review: true
    pending_dir: pending/job_calibration
  auto_apply:
    enabled: true
    types: [alias_patch, title_alias]
    min_sim_after: 0.55
    max_rounds: 3
```

`run.py load_config()` sets `cfg["_config_path"]` so `apply.py` can write title aliases back to the loaded config file.

### 14.8 Test plan (offline, HR-1)

| Test | Asserts |
|------|---------|
| `test_run_audit_passes_on_real_kb` | CORE guard green on committed KB |
| `test_run_audit_fails_on_regression` | P0 poisons CI |
| `test_simulate_alias_patch_improves_match` | simulate monotonic improvement |
| `test_can_auto_apply_requires_improvement` | gate blocks no-op patches |
| `test_run_calibration_cycle_dry_run` | loop completes without writes |
| `test_anchored_search_hides_unrelated_at_risk` | HR-12 UX regression |
| `test_discover_from_search_log_weighted` | P2 frequency-weighted discovery |
| `test_run_apply_pending_kb_profile` | P3 pending → KB append |

### 14.9 Search log ingest (P2)

**Record:** `ui/tabs/radar.py` calls `record_search_log()` on every non-empty search (tier, `best_id`, `sim`).

**Storage:** `data/radar_search_log.jsonl` (append-only JSONL; committed by daily cron when present).

**Discover:** `discover_from_search_log()` — queries with `occurrences ≥ search_log_min_occurrences`, sorted by weight (frequency).

**HF export:** copy Space log file → `python run.py query-agent ingest-logs export.jsonl` merges into the repo log for the next `query-agent run`.

---

## 15. v0.10b Semantic job search (implemented)

### 15.1 Dual embedder config (HR-1)

| File | `job_radar.search.embedder` | Runtime |
|------|----------------------------|---------|
| `config.yaml` | `sentence_transformers` | HF Space, local dashboard |
| `config.ci.yaml` | `hashing` | GitHub Actions pytest + `query-agent audit` |

`job_radar.resolve_embedder(search_cfg)` returns `SentenceEmbedder` or `RadarHashingEmbedder`.

### 15.2 Title-only semantic vectors

```python
def _job_embed_title(job) -> str:
    # title + title_zh + search_aliases ONLY

def _job_embed_text(job) -> str:
    # full document for lexical overlap (description, skills, industry, …)
```

Rationale: embedding the full description diluted role-name similarity (e.g. unrelated jobs sharing “AI”, “data”, “management” vocabulary).

### 15.3 Representative calibration lifts (prod embedder)

| Query | Before (hashing / diluted) | After (MiniLM title-only) |
|-------|---------------------------|---------------------------|
| `software developer` | ~0.60 | **0.845** |
| `lawyer` | ~0.00 | **0.944** |
| `护士` | ~0.00 | **0.869** |
| `人工智能工程师` | — | **0.956** |

### 15.4 Lexical abbreviation fix

`_query_tokens()` filters to `len(token) >= 2`, preserving `ml`, `hr`, `qa`, `gp` for overlap scoring.

### 15.5 Deployment

- `requirements.txt`: `sentence-transformers>=3.0`
- `Dockerfile`: pre-download `paraphrase-multilingual-MiniLM-L12-v2`
- Release notes: [RELEASE_v0.10.md](./RELEASE_v0.10.md)

---

## 16. Phase 10 — Self-Evolving Transition Recommendations (v0.11, implemented)

### 16.1 Problem with prior transition scoring

Three compounding defects caused poor career-path recommendations:

| Defect | Root cause | Symptom |
|--------|------------|---------|
| Dead overlap signal | `_skill_jaccard` always returned 0 (BLS skill vectors ≠ actual skill text) | 15% weight completely ignored |
| Demand/risk dominance | `risk_reduction + demand_norm` pushed all at-risk roles toward highest-demand targets | Accountant → AI Engineer, regardless of industry |
| Missing LLM validation | Curated `transition_targets` existed for ~50 roles; new roles had empty targets | No guidance for new KB entries |

### 16.2 Scoring formula (v0.11)

```python
skill_sem   = _skill_semantic_sim(current_job, tgt)    # [0, 1]
domain_prox = _domain_proximity(current_job, tgt)       # 0.0 / 0.5 / 1.0
overlap_signal = 0.65 * skill_sem + 0.35 * domain_prox

score = (
    w["skill"]  * proximity          # 40%: economic skill sensitivity
  + w["overlap"]* overlap_signal     # 15%: real skill + domain adjacency
  + w["risk"]   * risk_reduction     # 25%: displacement risk improvement
  + w["demand"] * demand_norm        # 20%: forward demand forecast
)
if llm_conf is not None:
    score *= (0.5 + llm_conf * 0.5)  # LLM confidence gate
```

### 16.3 `_skill_semantic_sim(a, b)`

```python
def _skill_semantic_sim(a: dict, b: dict) -> float:
    # text = ", ".join(required_skills) for each job
    # embed with SentenceEmbedder (lazy-loaded singleton)
    # cosine similarity; cached by sorted (id_a, id_b)
    # returns 0.0 when no embedder (CI path, HR-1)
```

Cache key: `(min(id_a, id_b), max(id_a, id_b))` → float in `_SKILL_SEM_CACHE`.

### 16.4 `_domain_proximity(a, b)`

Adjacency graph (`_ADJACENT_INDUSTRIES`) encodes industry clusters:

```python
_ADJACENT_INDUSTRIES = {
    "Finance": {"Legal", "Government"},
    "Legal":   {"Finance", "Government"},
    "Tech":    {"Media"},
    "Manufacturing": {"Construction", "Logistics"},
    ...
}
# same industry → 1.0; adjacent → 0.5; unrelated → 0.0
```

Finance→Finance transitions are naturally domain-proximate (1.0); Finance→Tech jumps pay a 0.5 penalty even if skill similarity is moderate.

### 16.5 `services/transition_evaluator/` architecture

```
cache.py
  _load(path) / _save(path)
  key(a, b) = "{anchor_id}→{candidate_id}"
  get(aid, cid) / put(aid, cid, feasibility, reasoning)
  missing_pairs(jobs, top_k=5)   # only jobs with empty transition_targets

evaluate.py
  _SYSTEM  — 5-tier feasibility prompt (see §16.6)
  _prompt(anchor, candidate) — injects required_skills + skill gap
  evaluate_pair(anchor, candidate, force=False) → dict | None
  run_evaluation_pass(jobs, max_pairs=40, min_feasibility=0.55) → summary
  _promote_to_kb(anchor_id, cand_id, result, kb_path)
    → appends {target_id, retrain_months, skill_bridge, confidence, _source: "llm_eval"}
    → retrain_months = max(2, round(24 × (1 − feasibility)))
```

### 16.6 LLM judge system prompt (5-tier scale)

```
0.85–1.0  Natural progression — same domain, 0–6 months upskilling
0.60–0.84 Adjacent move — related domain, 6–18 months
0.35–0.59 Deliberate pivot — adjacent industry, 18–36 months
0.10–0.34 Major reskill — different domain, substantial retraining
0.00–0.09 Extreme leap — almost no skill overlap
```

Returns `{"feasibility": float, "reasoning": "max 20 words", "recommended": bool}`.

### 16.7 Integration into calibration loop

```python
# services/job_query_agent/loop.py — after query calibration rounds
if not dry_run and auto_apply.enabled:
    transition_summary = run_evaluation_pass(
        fresh_jobs, kb_path=kb_path,
        max_pairs=cfg.get("transition_eval_max_pairs", 40),
    )
return {..., "transition_eval": transition_summary}
```

The daily CI workflow thus runs:
```
pytest → query-agent audit → (daily cron) query-agent run
  → round 1..N: query calibration
  → post-calibration: transition-eval (fill empty targets)
  → commit jobs_kb.json if any promotions
```

### 16.8 Config

```yaml
job_query_agent:
  auto_apply:
    enabled: true
  transition_eval_max_pairs: 40   # pairs per daily run
```

No new harness invariant required — evaluation uses existing Groq LLM seam (HR-6) and falls back silently when key absent (non-fatal, `skipped` count in summary).

---

## 11. Security & compliance defaults

- `require_review: true` — never change default in repo
- Disclaimer in every published report (`publish.DISCLAIMER`)
- OOD warning must appear in forecast prompt when `is_ood`
- BUSL-1.1 — commercial API deployment needs license
