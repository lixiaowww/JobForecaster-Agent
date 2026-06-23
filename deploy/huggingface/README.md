---
title: JobForecaster Agent
emoji: 🔮
colorFrom: blue
colorTo: purple
sdk: streamlit
app_file: app.py
pinned: false
license: other
short_description: AI × economy forecasting — Job Radar & calibration dashboard
---

# JobForecaster Agent — Interactive Dashboard

Streamlit UI for **Job Forecast Radar**, evolution benchmarks, and calibration scoreboard.

> Static daily reports live on [GitHub Pages](https://lixiaowww.github.io/JobForecaster-Agent/).
> This Space is the **interactive** frontend.

## Tabs

- **Job Forecast Radar** — hybrid RAG job search, BLS verification badges
- **Forecast Accuracy** — Brier scoreboard & calibration curve
- **Historical Benchmarks** — evolution case library
- **Plausibility Guard** — OOD / Mahalanobis signal

## Secrets (optional)

| Secret | Purpose |
|--------|---------|
| `GROQ_API_KEY` | LLM for unknown job title expansion (free tier) |

Without `GROQ_API_KEY`, Radar works fully; only AI-generated job profiles are disabled.

## Disclaimer

Speculative forecasts — not financial or career advice. BUSL-1.1.
