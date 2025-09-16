# G6 Web Dashboard (FastAPI)

An alternative to the terminal dashboard providing a browser-based overview of key metrics.

## Features (Phase 1)
- Overview page: core metrics, resource usage, per-index table (options processed, last collection timestamp, success %, PCR by expiry)
- /metrics/json structured snapshot for programmatic access
- /metrics/raw quick debugging view (cached)
- /health endpoint (basic status and staleness)

## Environment Variable
- `G6_METRICS_ENDPOINT` (default: http://localhost:9108/metrics)

## Run
Ensure collectors / metrics server are running (e.g. `python -m src.unified_main --run`). Then:

```powershell
pip install fastapi uvicorn jinja2
uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9300 --reload
```
Open http://localhost:9300

## Next Steps (Planned)
- Per-index detail page with PCR trend
- Small timeseries charts (Plotly) using ring buffer in memory
- Options snapshot endpoint (reads latest CSV per index/expiry)
- WebSocket push for lower latency updates
- Auth (API token) for restricted environments

## Notes
All metrics are derived from the Prometheus exposition you already expose; no direct coupling to in-process objects, making this safe to run externally (even on another host) as long as it can reach the metrics port.
