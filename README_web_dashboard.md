## Archived: Web Dashboard (FastAPI) Stub

The standalone FastAPI web dashboard has been deprecated and its documentation merged into the unified `README.md` (Observability & Panels sections).

Replacement surfaces:
1. Summary dashboard (`scripts/summary_view.py`)
2. Panels JSON artifacts + optional lightweight consumers
3. Grafana dashboards (see `grafana/`)

If you require the historical implementation details (endpoints, SSE diff mode, adaptive alerts UI) inspect git history:
```
git log -- README_web_dashboard.md
```

Deprecation timeline: Archived 2025-10-01 (R). Planned removal after R+1.

Please update external links to point to the canonical README.
