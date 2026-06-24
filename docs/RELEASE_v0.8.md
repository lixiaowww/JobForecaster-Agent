# Release v0.8 — MVP: Live Track Record Credibility

**Tag:** `v0.8` · **Date:** 2026-06-24 · **Commit:** `2b52bc4`

First public **MVP release** of JobForecast Agent — an autonomous AI × economy forecasting system with falsifiable predictions, honest Brier scoring, and a self-correcting learning loop.

**Phases 1–7 complete.** Harness invariants HR-1 through HR-11 enforced. **162 offline tests passing.**

---

## Highlights

### Core loop
- Daily LLM forecasting via Groq (mock fallback for CI)
- Automatic resolution + Brier scoring when predictions mature
- ROOT_CAUSE / CONTRAST_PAIR learning from past misses
- `predictions_live.jsonl` accumulated and committed by daily cron

### Track Record (HR-11)
- **Curated benchmark** (seed) and **Live LLM** predictions shown separately
- Independent Brier scores per origin
- Upcoming live resolutions timeline
- CSV download with `origin` column (`seed` | `live`)
- `run.py verify-export` CI guard — DB live state must match committed JSONL

### Job Impact Radar
- 65 occupation profiles, hybrid RAG search
- Real-time skill-vector transition paths
- LLM profile cache to reduce token usage
- Field-feedback calibration (when ≥5 real survey responses exist)

### Integrity (v0.6)
- **HR-9**: Citation sanitiser — strips hallucinated arXiv IDs and placeholder domains
- **HR-10**: Resolved-state durability — `warmup` + rolling Actions cache
- Groq 429 rate-limit retry with structured errors

### Trust & UX (v0.7)
- 19 historical transition cases (incl. China, India, Japan, South Korea)
- UX audit fixes: `st.tabs`, welcome banner, plain-language tab names
- Brier score inline explainer

### Engineering
- Dashboard decomposed into `ui/tabs/*` + `services/` layer
- `Registry(path=…)` true DB isolation for tests
- MCP + REST read APIs

---

## Deploy surfaces

| Surface | Notes |
|---------|-------|
| Hugging Face Space | Streamlit dashboard (synced from `main`) |
| GitHub Pages | Daily forecast static site |

---

## Post-MVP (time-dependent)

- Live resolved count → mean Brier target (n≥30, < 0.20)
- Field-feedback calibration from real HF Space survey responses
- First live predictions resolving on their `resolution_date`

---

## Quick start

```bash
pip install -r requirements-dashboard.txt
streamlit run dashboard.py
```

```bash
python run.py once --mock          # offline cycle
python run.py score                # calibration scoreboard
python -m pytest tests/ -q          # 162 tests, no API key
```

**License:** BUSL-1.1
