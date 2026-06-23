# Design Proposal (DP) — forecaster-agent

**Version:** 0.5 (Harness-aligned)  
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

| Item | Priority |
|------|----------|
| `dashboard.py` monolith (~1150 LOC) | P1 |
| Discord/Telegram crowd bots | ✅ `bots/` |
| No `MockLLMClient` for offline `run.py once` | P2 |
| `src/` package layout + Poetry lock | P3 |
| Alembic migrations | P3 |

---

## 10. Security & compliance defaults

- `require_review: true` — never change default in repo
- Disclaimer in every published report (`publish.DISCLAIMER`)
- OOD warning must appear in forecast prompt when `is_ood`
- BUSL-1.1 — commercial API deployment needs license
