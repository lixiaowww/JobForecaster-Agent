# Zero-cost deployment

Run a **public forecast demo** with no paid server and no paid LLM — using GitHub Actions +
GitHub Pages. Optional: [Groq](https://console.groq.com) free tier for higher-quality cycles.

---

## Architecture

```
GitHub Actions (daily, free tier)
  ├─ restore data/forecaster.db (cache)
  ├─ python run.py once --config config.ci.yaml [--mock | Groq]
  ├─ write site/index.html + feed.json
  └─ deploy-pages → GitHub Pages (free)

Local config.yaml keeps require_review: true — only config.ci.yaml auto-publishes.
```

| Layer | Cost | Role |
|-------|------|------|
| GitHub Actions | Free (monthly minutes) | Daily forecast cycle |
| GitHub Pages | Free | Public static report |
| Groq API | Free tier (optional secret) | LLM when `GROQ_API_KEY` is set |
| Mock LLM | $0 | Fallback when no secret (`--mock`) |
| arXiv / RSS / BLS seed | $0 | Ingest + Job Radar empirical layer |

**Not recommended on zero-cost deploy:** `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, public REST API,
24/7 Streamlit on Render free tier (cold starts, ephemeral disk).

---

## One-time setup

### 1. Enable GitHub Pages

1. Repo → **Settings** → **Pages**
2. **Build and deployment** → Source: **GitHub Actions**

### 2. (Optional) Groq free tier

1. Create key at [console.groq.com](https://console.groq.com)
2. Repo → **Settings** → **Secrets and variables** → **Actions**
3. New secret: `GROQ_API_KEY`

Without this secret, the workflow uses `--mock` (deterministic stub, still publishes).

### 3. Trigger first deploy

- **Actions** → **Daily forecast and GitHub Pages** → **Run workflow**

Or wait for the daily cron (`06:00 UTC`).

Your site URL: `https://<user>.github.io/<repo>/` (or custom domain).

---

## Config profiles

| File | `require_review` | Use |
|------|------------------|-----|
| `config.yaml` | `true` (default) | Local dev, human approve via `run.py approve` |
| `config.ci.yaml` | `false` | **CI only** — writes directly to `site/` |

Never flip `require_review` to `false` in `config.yaml` unless you fully trust the loop.

```bash
# Local dry-run of CI profile
python run.py once --config config.ci.yaml --mock
open site/index.html
```

---

## Environment variables

Copy `.env.example` → `.env` for local use:

```bash
cp .env.example .env
```

| Variable | Zero-cost deploy |
|----------|------------------|
| `GROQ_API_KEY` | Optional; set as GitHub secret for CI |
| `FORECASTER_MOCK_LLM=1` | Local fallback without key |
| `FORECASTER_CONFIG` | e.g. `config.ci.yaml` |
| `ANTHROPIC_API_KEY` | Skip on public demo |
| `TAVILY_API_KEY` / `FRED_API_KEY` | Skip on public demo |

---

## SQLite persistence in CI

The workflow caches `data/forecaster.db` between runs so Brier scores and open predictions
accumulate. Cache is best-effort; GitHub may evict it after ~7 days of inactivity.

---

## Optional: Streamlit demo (Hugging Face Spaces)

For interactive Job Radar (not the daily loop):

1. Create a [Hugging Face Space](https://huggingface.co/new-space) (Streamlit)
2. Point at this repo; set `GROQ_API_KEY` in Space secrets
3. Start command: `streamlit run dashboard.py`
4. Keep LLM KB expansion rare (rate-limit in UI or disable) to stay within free tier

---

## License note (BUSL-1.1)

Free public demo + donation is fine. **Commercial** hosting of the REST/MCP API as a paid product
requires a separate commercial license (see README).

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Pages shows 404 | Enable Pages source = GitHub Actions; run workflow once |
| Empty scoreboard | Normal on first run; cache builds over days |
| Workflow uses mock | Add `GROQ_API_KEY` secret or accept stub output |
| `pending/` fills locally | Expected with `require_review: true`; run `python run.py approve` |
