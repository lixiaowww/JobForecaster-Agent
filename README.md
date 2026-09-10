---
title: JobForecaster Agent
emoji: 🔮
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8501
python_version: "3.12"
pinned: false
short_description: Streamlit Job Radar and AI economy forecast dashboard
---

# forecaster-agent

An autonomous AI × economy forecasting loop — grounded in economic theory,
self-calibrating via Brier scoring, and designed to be honest about the limits
of historical extrapolation.

[![CI](https://github.com/your-org/forecaster-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/forecaster-agent/actions)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-BUSL--1.1-green)
![Tests](https://img.shields.io/badge/tests-244%20offline-brightgreen)

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

**Job query agent** (`services/job_query_agent/`)
The self-mutating half: discovers job-search queries the KB answers badly, proposes
alias / config / new-profile patches, gates them, applies the safe ones, records every
write in an append-only provenance ledger, and auto-reverts regressions.  What it
changes is data and config — never its own code.

### Grading the agent's own edits

The query agent's pre-apply gate scores a patch by similarity against the same KB the
patch is about to edit.  For a patch that *adds* the matching alias — or invents the
matching profile outright — that check is very nearly tautological: the agent writes the
answer key and then marks its own paper.  Run long enough, such a loop grows more
self-consistent without growing more correct.

So every auto-applied patch is restated as a `PatchClaim`: a sentence that could turn
out false, a `resolution_date`, an explicit confidence the agent must **stake**, and
resolution criteria naming external evidence only.  When the horizon elapses, the claim
is judged against things the KB cannot influence — post-patch user search behaviour,
human feedback naming the role, BLS occupation data — and scored with the same
`brier_score` the AI-economy forecasts use.  The realised record then feeds back into
the gate: a patch type that has been confidently wrong loses the right to auto-apply.

Three properties hold the design together:

| Property | Why it is there |
|---|---|
| No evidence resolves **ambiguous**, never true | else the agent earns a spotless record by emitting unfalsifiable patches |
| Ambiguous claims still count as **outstanding** | else unfalsifiable patches are not merely unpunished — they are free.  Too many uncorroborated claims suspends auto-apply on their own |
| The gate **fails open** | a bug in the scoring path may only ever make the agent more conservative, never wedge the cycle |

Claims live in their own table.  The machinery is shared (`Status`, `brier_score`, the
calibration buckets); the ledgers are not — the public track record must stay an
AI-economy track record, not be diluted by the agent's internal housekeeping.

Evidence is scoped to what it can actually settle.  A BLS SOC code proves the
*occupation* is real; it says nothing about whether a given query *means* that
occupation.  So it can carry a `kb_profile_new` verdict — where "does this role exist
at all" is precisely the claim — and is recorded as context only for `alias_patch` /
`title_alias`, whose claim is about the mapping.  Otherwise any alias pointing at a
BLS-stamped row would be trivially true.

### Where the external ground truth comes from

`query-agent bls-backfill` stamps `soc_code` / `bls_employment` onto KB rows, which is
what turns `bls_presence` from a permanently-skipped signal into a working one.
**65 of 92 rows are anchored**; the rest are genuinely new AI-era roles with no SOC
code, and stay unanchored on purpose.

Three passes, in strict precedence order, every one an exact match:

| Pass | Source of truth | Rows |
|---|---|---|
| `title` | KB title equals a BLS occupation title | 20 |
| `citation` | the SOC code the row's own `sources` cite, validated against the official catalog | 42 |
| `source_title` | the occupation *name* spelled out in `sources`, when the cited code is stale | 3 |

The rules that make those passes trustworthy, each one costing recall on purpose:

* **Never `search_aliases`, never agent-written `sources`.** Both are fields this system
  writes. Reading an anchor out of them lets the agent mint the citation that buys its
  own row external ground truth — which is then used to grade the agent's own patches.
  Generated rows are marked `origin: "agent"` at the KB choke point and cross-checked
  against the provenance ledger. Measured on this KB, the alias path alone gave 8 wrong
  stamps out of 28, including `13-2051 Financial Analyst → Credit Analyst` (13-2041).
* **Validated against the full 831-occupation OES catalog**, so a typo or an invented
  code cannot become ground truth. Stale SOC 2010 citations correctly fail here and are
  recovered by name instead — `29-1067 Radiologists` → `29-1224`.
* **Injective, with title outranking citation.** A row claimed by two codes, or a code
  claiming two rows, is dropped rather than guessed — that is what keeps `23-1011
  Lawyers` off "AI Legal Forensics Specialist". An exact title match wins such a contest
  instead of annulling it, so the plain "Lawyer" row keeps the anchor it earned.
* **No fuzzy similarity, and no catch-all codes.** Similarity was evaluated and
  rejected: at 0.70 it put IT Manager and Operations Manager on the HR Manager row and
  Systems Analyst on Credit Analyst, while scoring an exact Receptionist match at 0.064.
  Residual buckets like "Computer Occupations, All Other" assert almost nothing and are
  refused.

Where two independent passes both reached a verdict on the current KB, they agreed 4
times out of 4 and disagreed zero times.

A bad anchor is worse than no anchor: it does not merely fail to catch drift, it
certifies it.  `run_coverage_enrichment` also stamps the SOC code it already knows onto
each row it generates — previously discarded, which left every generated row
permanently unverifiable.

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
python -m pytest tests/       # 244 tests, ~26s, zero network
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

# Phase 9 — job search calibration agent
python run.py query-agent audit              # CI: exit 1 on P0 regression or weak-core
python run.py query-agent once               # audit + queue proposals to pending/
python run.py query-agent run                # discover → simulate → auto-apply safe fixes
python run.py query-agent apply              # merge human-approved pending/*.json
python run.py query-agent ingest-logs f.jsonl  # merge HF/Radar search log export

# Phase 10 — transition self-evolution
python run.py query-agent transition-eval [N]  # LLM-evaluate up to N uncached pairs

# Phase 11 — Brier-scored claims over the agent's own patches
python run.py query-agent claims score       # calibration record, per patch type
python run.py query-agent claims resolve     # judge due claims vs external evidence
python run.py query-agent claims resolve --dry-run
python run.py query-agent claims list [N]    # last N staked claims
python run.py query-agent bls-backfill       # stamp SOC ground truth onto KB rows
python run.py query-agent bls-backfill --dry-run
python run.py query-agent bls-backfill --refresh   # pull the annual OES flat file
python run.py query-agent bls-backfill --no-citations   # title matches only
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

### Interactive dashboard (Hugging Face Spaces)

> HF 已弃用原生 Streamlit SDK（2025-04）→ 创建 Space 时选 **Docker**，仓库内已含 `Dockerfile`。

```bash
streamlit run app.py          # local
docker build -t jobforecaster . && docker run -p 8501:8501 jobforecaster  # optional
```

See **[docs/HUGGINGFACE.md](docs/HUGGINGFACE.md)** — add `HF_TOKEN` (Hugging Face Write) to **GitHub Secrets** for auto-sync.

---

## Configuration (`config.yaml`)

LLM routing is automatic in `forecast.call_llm()`:

1. **`GROQ_API_KEY` set** → Groq (`llama-3.3-70b-versatile`), free tier recommended  
2. **`ANTHROPIC_API_KEY` set** → uses `model` below (Claude)  
3. **Neither** → error (or `mock_llm` / `--mock` for offline)

```yaml
model: claude-sonnet-4-6   # Anthropic only; Groq ignores claude-* ids
database_path: data/forecaster.db
interval_seconds: 86400     # 24h; or use cron (more robust)
max_signals: 40
max_predictions: 6

evolution:
  n_bootstrap: 50           # lower in tests

require_review: true         # KEEP THIS TRUE until your scoreboard earns trust
```

**Where to set `GROQ_API_KEY`:** GitHub repo → **Settings → Secrets** (daily Pages workflow); Hugging Face Space → **Settings → Repository secrets** (Radar LLM expansion). The `model` field in this file does not enable Groq — the env var does.

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
run.py                CLI: once | loop | resolve | score | approve | query-agent *
loop.py               Orchestrator: resolve → ingest → evolution → forecast → publish
dashboard.py          Streamlit 4-tab visual analytics dashboard
job_radar.py          Hybrid RAG retrieval + semantic embeddings + transition scoring
ui/                        Streamlit tabs + sidebar (dashboard split)
services/read_model.py             Read-only seam (MCP + REST)
services/crowd_service.py          Crowd submit + gate (Phase 2)
services/dashboard_data.py         Dashboard data via services layer
services/job_query_agent/          Phase 9: retrieval QA loop (audit, calibrate, apply)
services/transition_evaluator/     Phase 10: LLM-as-judge self-evolving transition KB
data/jobs_kb.json                  ~80 occupation profiles (curated + LLM-generated)
data/query_seed.json               115+ calibration seed queries (EN + zh)
data/transition_eval_cache.json    Cached LLM transition feasibility scores
bots/                      Telegram + Discord crowd bots
docs/BOTS.md               Bot setup
paths.py              PROJECT_ROOT (import bootstrap)
forecast_system.md    Forecasting system prompt (economic theory grounding)
tests/                Offline harness: 190 tests, zero network (HR-1)
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
