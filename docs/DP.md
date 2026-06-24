# Design Proposal (DP) — forecaster-agent

**Version:** 0.6 (Integrity & Learning Loop)  
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
| `jobfeedback` | Career survey + 6-month follow-up |

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

## 7. Job Radar retrieval

Unchanged from v0.4 — hybrid score:

$$\text{hybrid}_j = \alpha \cdot \text{impact}_j + \beta \cdot \text{sim}(q, j)$$

$$\text{impact}_j = \text{base\_demand\_trend}_j + \sum_i s_i \cdot w_{j,i}$$

Config: `job_radar.alpha`, `job_radar.beta` (HR-3).

---

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
| `dashboard.py` monolith (~1150 LOC) | P1 | open |
| Discord/Telegram crowd bots | P2 | ✅ `bots/` |
| No `MockLLMClient` for offline `run.py once` | P2 | open |
| `src/` package layout + Poetry lock | P3 | open |
| Alembic migrations | P3 | open |
| SQLite engine global singleton, poor test isolation | P3 | open |

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

## 11. Security & compliance defaults

- `require_review: true` — never change default in repo
- Disclaimer in every published report (`publish.DISCLAIMER`)
- OOD warning must appear in forecast prompt when `is_ood`
- BUSL-1.1 — commercial API deployment needs license
