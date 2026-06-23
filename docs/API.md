# REST API — read-only integration (Phase 3b)

The REST API exposes the same read-only handlers as the MCP server
(`services/mcp_handlers.py`). OpenAPI documentation is auto-generated at `/docs`.

## Install & run

```bash
pip install -r requirements.txt
pip install -r requirements-api.txt
python api_server.py
# default: http://127.0.0.1:8765
```

Or with uvicorn directly:

```bash
uvicorn api_server:app --host 127.0.0.1 --port 8765
```

## Authentication (optional)

Set `FORECASTER_API_KEY` in the environment to require the `X-API-Key` header on
every request. When unset, the API is open (local development only).

```bash
export FORECASTER_API_KEY=your-secret-here
curl -H "X-API-Key: your-secret-here" http://127.0.0.1:8765/v1/scoreboard
```

Never commit API keys. Prefer environment variables over `config.yaml`.

## Rate limiting

Configured in `config.yaml` → `api.rate_limit_per_minute` (default: 60).
In-memory per-IP sliding window; single-process only.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + auth mode |
| GET | `/v1/scoreboard` | Brier calibration scoreboard |
| GET | `/v1/ood` | OOD assessment (`scenario_json`, `n_bootstrap` query params) |
| POST | `/v1/ood` | OOD with JSON body `{ "scenario": {...}, "n_bootstrap": 50 }` |
| GET | `/v1/jobs/search` | Job hybrid RAG search (query params) |
| POST | `/v1/jobs/search` | Job search with JSON body |
| GET | `/v1/predictions/open` | Open predictions (`limit` query param) |
| GET | `/v1/predictions/{id}/contribute` | **Blind** target for crowd submit (no agent prior) |
| POST | `/v1/predictions/{id}/contributions` | Submit crowd forecast + argument + evidence |
| GET | `/v1/predictions/{id}/crowd` | Crowd aggregate (requires `contributor_id` who has submitted) |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI 3 schema |

## Examples

```bash
# Calibration scoreboard
curl http://127.0.0.1:8765/v1/scoreboard

# OOD (fast bootstrap for dev)
curl "http://127.0.0.1:8765/v1/ood?n_bootstrap=5"

# Job search
curl "http://127.0.0.1:8765/v1/jobs/search?query=risk%20analyst&industry=Finance&limit=5"

# Open predictions
curl "http://127.0.0.1:8765/v1/predictions/open?limit=10"
```

POST scenario override:

```bash
curl -X POST http://127.0.0.1:8765/v1/ood \
  -H "Content-Type: application/json" \
  -d '{"scenario": {"augmentation_ratio": 0.9, "diffusion_years": 3}, "n_bootstrap": 10}'
```

## Scenario variables

Optional overrides merge onto `evolution.CURRENT_AI_SCENARIO`:

- `augmentation_ratio`, `demand_elasticity`, `oring_leverage`, `skill_distance`
- `diffusion_years`, `absorbing_sector`, `productivity_capture`, `task_frontier_open`

## Crowd contributions (Phase 2)

Anti-anchoring flow:

1. `GET /v1/predictions/{id}/contribute` — returns statement + resolution criteria only
2. `POST /v1/predictions/{id}/contributions` — submit; response includes **your** gate decision, not the aggregate
3. `GET /v1/predictions/{id}/crowd?contributor_id=...` — aggregate visible only after you have submitted

```bash
# 1. Blind target (no agent confidence/rationale)
curl http://127.0.0.1:8765/v1/predictions/{id}/contribute

# 2. Submit
curl -X POST http://127.0.0.1:8765/v1/predictions/{id}/contributions \
  -H "Content-Type: application/json" \
  -d '{
    "contributor_id": "alice",
    "probability": 0.35,
    "argument": "Because grid constraints bind however budgets are announced therefore spend lags.",
    "evidence_urls": ["https://example.com/report"]
  }'

# 3. View aggregate (only after submitting as alice)
curl "http://127.0.0.1:8765/v1/predictions/{id}/crowd?contributor_id=alice"
```

One submission per `contributor_id` per prediction. Gate thresholds in `config.yaml` → `crowd`.

---

- **HR-1**: `tests/test_api.py` uses FastAPI TestClient — no live server
- **HR-5**: No write endpoints (no forecast generation, no publish)
- **HR-8**: Commercial API hosting requires BUSL commercial license

## Tests

```bash
python -m pytest tests/test_api.py -v
```

## MCP parity

| REST | MCP tool |
|------|----------|
| `GET /v1/scoreboard` | `get_calibration_scoreboard` |
| `GET/POST /v1/ood` | `get_ood_assessment` |
| `GET/POST /v1/jobs/search` | `search_jobs` |
| `GET /v1/predictions/open` | `list_open_predictions` |

See also [MCP.md](./MCP.md).
