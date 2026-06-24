# Release v0.10 — Query Calibration Agent & Semantic Job Search

**Tag:** `v0.10` · **Date:** 2026-06-24 · **Head commit:** `f6ef135`

Phase 9 release plus a **search-layer upgrade**: multilingual semantic embeddings for production, continuous retrieval QA, KB expansion to ~80 roles, and offline-safe CI via dual embedder config.

**Phases 1–9 complete.** Harness invariants HR-1 through HR-13 enforced. **190 offline tests passing** (CI uses `embedder: hashing`; production/HF uses `sentence_transformers`).

---

## Highlights

### Semantic search upgrade (production)

| Change | Effect |
|--------|--------|
| **`SentenceEmbedder`** (`paraphrase-multilingual-MiniLM-L12-v2`) | Title-only semantic vectors via `_job_embed_title()` — **title + `title_zh` + `search_aliases` only** (no description dilution) |
| **Representative score lifts** | `software developer` → Software Engineer: **0.60 → 0.845**; `lawyer` → Lawyer: **0.00 → 0.944** |
| **2-char token filter fix** | Lexical overlap keeps domain abbreviations: `ml`, `hr`, `qa`, `gp` (drops only single-char ASCII) |
| **Chinese queries (no manual alias)** | `护士` **0.869**, `人工智能工程师` **0.956** — multilingual MiniLM + CJK tokenisation |
| **KB alias corrections** | `医生` → `hc_general_practitioner`; `financial analyst` → `fin_credit_analyst`; radiologist title de-noised |
| **CI stays offline (HR-1)** | `config.ci.yaml` → `embedder: hashing`; `config.yaml` / HF Docker → `embedder: sentence_transformers` |

```yaml
# config.yaml (production / HF Space)
job_radar:
  search:
    embedder: sentence_transformers   # paraphrase-multilingual-MiniLM-L12-v2

# config.ci.yaml (GitHub Actions pytest + query-agent audit)
job_radar:
  search:
    embedder: hashing               # RadarHashingEmbedder — no model download
```

`resolve_embedder(search_cfg)` selects the backend; `SentenceEmbedder` lazy-loads with an MD5 embedding cache. Dockerfile pre-downloads the model for HF cold start.

### Query Calibration Agent (Phase 9)

- `services/job_query_agent/` — discover → evaluate → simulate → apply → audit/loop
- CLI: `query-agent audit | once | run | apply | ingest-logs`
- **115 seed/CORE queries**, **0 P0 regressions**, **0 weak_core** after KB expansion
- Daily cron: `query-agent run` + `GROQ_API_KEY` for gated `kb_profile_new`; commits KB/config/search log
- CI: `query-agent audit` after pytest

### KB & hot-role coverage

- KB expanded to **~80 occupation profiles** (from 65)
- `CORE_HOT_ROLE_QUERIES` + `search_aliases` for product manager, software developer, 程序员, etc.
- Seed corrections: e.g. `ml engineer` → `tech_ai_infra_eng`, `ai compliance officer` → `legal_compliance_officer`

### Radar UX (HR-12, interim)

- Search anchor + transition paths separated from text retrieval
- Anchored search suppresses **unrelated** at-risk cards ranked by weak text scores (e.g. engineer → Logistics Dispatcher)
- **Known product debt:** hiding the entire at-risk column on anchor undermines credibility for transforming roles (e.g. Software Engineer); next iteration should show **anchor role exposure** while filtering noise

---

## Architecture (search stack)

```
Query
  → normalize_search_query() + title_aliases
  → embed: SentenceEmbedder(_job_embed_title)  [prod]  |  RadarHashingEmbedder [CI]
  → lex:  token overlap on full _job_embed_text() document
  → combined_similarity = w_emb·cosine + w_lex·overlap × penalties
  → tier_no_match / tier_weak / tier_strong (config.yaml)
```

Transition recommendations remain **`transition_score` only** (HR-12).

---

## Deploy surfaces

| Surface | Embedder | Notes |
|---------|----------|-------|
| Hugging Face Space | `sentence_transformers` | Docker pre-bakes MiniLM weights |
| GitHub Actions CI | `hashing` | HR-1 offline; no `sentence-transformers` required in pytest |
| Daily cron | `config.yaml` + Groq | Forecast + `query-agent run` |

---

## Quick start

```bash
pip install -r requirements-dashboard.txt   # includes sentence-transformers>=3.0
streamlit run dashboard.py
```

```bash
python run.py query-agent audit             # CI gate (hashing embedder via config.ci.yaml if set)
FORECASTER_CONFIG=config.yaml python run.py query-agent audit   # prod embedder profile
python -m pytest tests/ -q                  # 190 tests, no API key
```

---

## Commits (v0.9 → v0.10)

| Commit | Summary |
|--------|---------|
| `0686984` | Query calibration agent, hot-role KB, radar search UX |
| `a15ba45` | Query-agent closed loop; anchored at-risk suppression |
| `398add9` | KB → ~80 roles; 115 queries, zero P0 |
| `f6ef135` | **Semantic search** — MiniLM title-only + lexical fixes + KB aliases |

**License:** BUSL-1.1
