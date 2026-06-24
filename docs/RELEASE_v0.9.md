# Release v0.9 — Personalized Job Radar & Search Quality

**Tag:** `v0.9` · **Date:** 2026-06-24 · **Commit:** `49d7eb8`

Phase 8 release: fixes the conflation of **text search** and **career transition recommendations** on the Job Impact Radar, and adds user-specific personalization via experience level and retrain tolerance.

**Phases 1–8 complete.** Harness invariants HR-1 through HR-13 enforced. **170 offline tests passing.**

---

## Highlights

### Search quality (HR-3 / HR-12)

- **Retrieval ≠ recommendation** — search ranks by `combined_similarity` (embedding + lexical blend); transition paths rank by `transition_score` only
- Search thresholds moved to `config.yaml` → `job_radar.search.*` (no more hard-coded constants)
- User-facing match tiers: **无匹配 / 弱 / 强** (tier_no_match 0.42, tier_strong 0.65)
- Search sets an **anchor role**; opportunity list re-sorted by transition fit from that anchor
- Regression fix retained: multi-word queries like "finance process improvement" no longer surface unrelated AI trading roles

### Personalization (HR-13)

- **Sidebar career profile** (session): experience level (junior / mid / senior) + max retrain months
- `compute_transition_paths()` adjusts weights by seniority and filters targets exceeding retrain cap
- Field survey collects **`experience_level`** alongside canonical job title
- `get_empirical_metrics()` stratifies by `(title, experience_level)` when n≥5 responses per cell; falls back to title-only

### Config additions

```yaml
job_radar:
  search:      # embed/lex weights, tier thresholds
  transition:  # skill / overlap / risk / demand weights
  personalization:  # retrain caps per level, min_stratified_responses
```

### Schema

- `JobFeedback.experience_level` (default `mid`) with SQLite idempotent migration

---

## Deploy surfaces

| Surface | Notes |
|---------|-------|
| Hugging Face Space | Streamlit dashboard (synced from `main`) |
| GitHub Pages | Daily forecast static site |

---

## Post-v0.9 (time-dependent)

- Live resolved count → mean Brier target (n≥30, < 0.20)
- Field-feedback calibration from real HF Space survey responses (stratified by experience)
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
python -m pytest tests/ -q          # 170 tests, no API key
```

**License:** BUSL-1.1
