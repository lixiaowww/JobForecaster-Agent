# MCP Server — read-only integration

The forecaster-agent MCP server exposes **read-only** tools over stdio. It wraps
`services/read_model.py` and adds disclaimers on every response. There are no write
tools (no forecast generation, no crowd submissions) — consistent with HR-5 and
BUSL commercial-use constraints.

## Tools

| Tool | Purpose |
|------|---------|
| `get_calibration_scoreboard` | Brier score, reliability curve |
| `get_ood_assessment` | Mahalanobis OOD vs historical transitions |
| `search_jobs` | Hybrid RAG job impact search |
| `list_open_predictions` | Open falsifiable predictions |

## Install

```bash
pip install -r requirements.txt
pip install -r requirements-mcp.txt
```

## Run manually

```bash
python mcp_server.py
```

The process speaks MCP over stdin/stdout (stdio transport). Do not pipe other output
to stdout when running under an MCP client.

## Cursor configuration

Add to your Cursor MCP settings (`.cursor/mcp.json` or Settings → MCP):

```json
{
  "mcpServers": {
    "forecaster-agent": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/absolute/path/to/forecaster-agent"
    }
  }
}
```

Use the venv interpreter if dependencies are installed there:

```json
{
  "mcpServers": {
    "forecaster-agent": {
      "command": "/absolute/path/to/forecaster-agent/venv/bin/python",
      "args": ["/absolute/path/to/forecaster-agent/mcp_server.py"]
    }
  }
}
```

## Claude Desktop (example)

```json
{
  "mcpServers": {
    "forecaster-agent": {
      "command": "/absolute/path/to/forecaster-agent/venv/bin/python",
      "args": ["/absolute/path/to/forecaster-agent/mcp_server.py"]
    }
  }
}
```

## Scenario overrides

`get_ood_assessment` and `search_jobs` accept optional `scenario_json` — a JSON
string merging onto `evolution.CURRENT_AI_SCENARIO`:

```json
{
  "augmentation_ratio": 0.85,
  "diffusion_years": 3.0
}
```

## Harness compliance

- **HR-1**: Handlers tested offline in `tests/test_mcp_handlers.py` without MCP runtime
- **HR-5**: No publish/forecast write tools exposed
- **HR-8**: Commercial MCP hosting requires BUSL commercial license

## Tests

```bash
python -m pytest tests/test_mcp_handlers.py -v
```
