# forecaster-agent

An autonomous AI × economy forecasting loop — grounded in economic theory,
self-calibrating via Brier scoring, and designed to be honest about the limits
of historical extrapolation.

[![CI](https://github.com/your-org/forecaster-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/forecaster-agent/actions)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-BUSL--1.1-green)
![Tests](https://img.shields.io/badge/tests-59%20offline-brightgreen)

---

## What it is

A system that **loops**: ingest AI-tech and economic signals → generate falsifiable
predictions grounded in economic theory → score past predictions against reality →
feed that track record back into the next forecast.

What makes it a *loop* rather than a one-shot prompt is the closed feedback: every
prediction is dated and falsifiable, every resolution is Brier-scored, and that score
calibrates the next cycle.  A forecaster that never grades itself is an opinion generator.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         One cycle                                   │
│                                                                     │
│  RESOLVE ──► SCORE      INGEST signals                             │
│  (judge due  (Brier)      (arXiv·RSS·Tavily·FRED)                  │
│  predictions)   │               │                                   │
│                 │    track      │   signals                         │
│                 └──► record ──► EVOLUTION PRIOR ──► FORECAST          │
│                                    │         (PCA/GMM/OOD)            │
│                                    │                                │
│                              CROWD GATE ◄── human contributions    │
│                            (entropy×soundness                       │
│                             sparse selection)                       │
│                                    │                                │
│                                DEDUP ──► REGISTRY (SQLite DB)      │
│                                    │                                │
│                               PUBLISH ──► site · webhook · git     │
│                           (review gate)                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Three subsystems

**Forecaster loop** (`loop.py`, `forecast.py`, `registry.py`, `publish.py`)
The core cycle. Resolves due predictions; ingests signals; builds an evolution
prior; generates falsifiable forecasts; dedups into SQLite; publishes behind a
human review gate by default.

**Crowd gate** (`crowd.py`) — *library complete; loop integration Phase 2*
Turns many overlapping human contributions into a *sparse* set of high-information
signals.  Two conjunctive gates: soundness (valid argument + verifiable evidence)
AND novelty (JS-divergence + semantic distance from existing views).  Only
admissions that pass both gates can move the aggregate forecast.  Contributor skill
is earned from realised Brier — not assumed.

**Job evolution agent** (`evolution.py`)
Extracts drivers and patterns from 15 citable historical technology-driven
occupational transitions.  Runs PCA + Bayesian GMM clustering on 8 causal-proxy
variables (augmentation ratio, demand elasticity, O-ring leverage, skill distance,
diffusion speed, absorbing sector, productivity capture, task-frontier openness).
Emits an `EvolutionPrior` — including a Mahalanobis-distance OOD signal that tells
the forecaster when it is extrapolating outside all historical precedent.

---

## Theoretical foundations

The forecasting prompt and evolution agent are grounded in:

| Theory | Author | What it governs here |
|---|---|---|
| Augmentation vs automation | Autor et al. | primary variable in case library; framing of all predictions |
| Creative destruction | Schumpeter | why new job *categories* are hard to name ex-ante |
| Jevons' paradox / induced demand | Jevons | demand_elasticity variable |
| Baumol's cost disease | Baumol | absorbing_sector variable; "human premium" job category |
| O-ring theory | Kremer | oring_leverage; value of human step rises as others automate |
| Polanyi's paradox | Polanyi | tacit knowledge as limit on automation |
| Wisdom of crowds | Surowiecki / Tetlock | crowd gate design (diversity + independence + weighting) |
| Diversity prediction theorem | Page | why correlated errors ≠ wisdom |

---

## Setup

```bash
git clone https://github.com/your-org/forecaster-agent
cd forecaster-agent
pip install -r requirements.txt
pip install -r requirements-dashboard.txt   # only for Streamlit dashboard
cp .env.example .env          # GROQ_API_KEY (free) or ANTHROPIC_API_KEY
```

**Run the offline test suite first (no API key needed):**
```bash
python -m pytest tests/       # 59 tests, ~16s, zero network
```

Then run a single cycle:
```bash
python run.py once
python run.py once --mock   # deterministic LLM stub (no API key)
```

---

## CLI

```bash
python run.py once       # one full cycle
python run.py loop       # run forever at config.yaml interval
python run.py resolve    # grade + score due predictions only
python run.py score      # print calibration scoreboard
python run.py approve    # publish queued pending/ items (review gate)
```

### MCP (read-only, optional)

Expose calibration, OOD, job search, and open predictions to Cursor or Claude Desktop:

```bash
pip install -r requirements-mcp.txt
python mcp_server.py    # stdio — configure in your MCP client
```

See [docs/MCP.md](docs/MCP.md) for Cursor / Claude Desktop configuration.

### REST API (read-only, optional)

```bash
pip install -r requirements-api.txt
python api_server.py    # http://127.0.0.1:8765 — OpenAPI at /docs
```

See [docs/API.md](docs/API.md) for endpoints, auth, and examples.

### Zero-cost deploy (GitHub Pages)

Daily forecast + static site on **free** GitHub Actions + Pages. Optional Groq free tier.

```bash
python run.py once --config config.ci.yaml --mock   # local preview of CI output
```

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for setup (Pages, `GROQ_API_KEY` secret, `config.ci.yaml`).

---

## Configuration (`config.yaml`)

```yaml
model: claude-sonnet-4-6
database_path: data/forecaster.db
interval_seconds: 86400     # 24h; or use cron (more robust)
max_signals: 40
max_predictions: 6

evolution:
  n_bootstrap: 50           # lower in tests

require_review: true         # KEEP THIS TRUE until your scoreboard earns trust
```

---

## Publishing guardrail

`require_review: true` is the default.  Predictions queue in `./pending/`
and a human runs `python run.py approve` before anything goes public.

**Please read this before disabling it.**  Auto-publishing speculative economic
forecasts at scale carries reputational and legal risk.  An LLM that generates
plausible-sounding wrong predictions is worse than silence if it publishes them
automatically.  The gate is the difference between a tool and a liability.  Disable
it only when your Brier history gives you reason to trust the system.

---

## Files

```
schemas.py            Prediction + Signal models, Brier scoring, dedup fingerprint
registry.py           SQLite store, due-detection, calibration scoreboard, track record
ingest.py             pluggable signal sources (arXiv, RSS, Tavily, FRED)
forecast.py           LLM reasoning: generate predictions + judge past ones
crowd.py              Crowd gate: entropy × soundness gate + sparse selection
evolution.py          Job evolution agent: case library, PCA/GMM, OOD detector
publish.py            Render md/html/json + file/webhook/git backends + review gate
run.py                CLI: once | loop | resolve | score | approve
loop.py               Orchestrator: resolve → ingest → evolution → forecast → publish
dashboard.py          Streamlit 4-tab visual analytics dashboard
job_radar.py          Hybrid RAG retrieval engine + LLM KB expansion
ui/                        Streamlit tabs + sidebar (dashboard split)
services/read_model.py       Read-only seam (MCP + REST)
services/crowd_service.py    Crowd submit + gate (Phase 2)
services/dashboard_data.py     Dashboard data via services layer
bots/                      Telegram + Discord crowd bots
docs/BOTS.md               Bot setup
paths.py              PROJECT_ROOT (import bootstrap)
forecast_system.md    Forecasting system prompt (economic theory grounding)
tests/                Offline harness: crowd, evolution, registry
docs/PRD.md           Product requirements (Harness invariants)
docs/DP.md            Design proposal
docs/MCP.md           MCP server setup (Cursor / Claude Desktop)
mcp_server.py         Read-only MCP server (stdio, 4 tools)
api_server.py         Read-only REST API (/v1/*, OpenAPI /docs)
docs/API.md           REST setup and endpoint reference
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).  The short version:

- All tests run offline; no API key is ever needed for the test suite.
- Every historical case in the evolution library needs a citable source.
- `require_review: true` must remain the documented default.
- New components earn their place by improving Brier calibration — not by assumption.

We especially need: non-Western historical cases, net-loss transition cases
(to balance the library), and UI/API for crowd contributions.

---

## License

This project is licensed under the **Business Source License 1.1 (BUSL-1.1)**.

- ✅ **Free for**: non-commercial research, education, personal projects, open-source contributions
- ❌ **Requires commercial license for**: SaaS products, paid services, embedding in commercial software
- 🔄 **Converts to Apache 2.0** on 2029-06-23

See [LICENSE](LICENSE) for full terms. For commercial licensing inquiries, open an issue.

---

## Disclaimer

Forecasts produced by this system are speculative outputs of a language model,
calibrated against a small set of historical cases.  They are not financial,
investment, or economic advice.  Confidence values are the model's own estimates.
The OOD signal in the evolution prior is the most important number: when it fires,
historical patterns may not transfer to the current regime.
