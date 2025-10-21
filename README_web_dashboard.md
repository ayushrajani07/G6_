## Archived: Web Dashboard (FastAPI) Stub

The standalone FastAPI web dashboard has been deprecated and its documentation merged into the unified `README.md` (Observability & Panels sections).

Replacement surfaces:
1. Summary dashboard (`python -m scripts.summary.app`)
2. Panels JSON artifacts + optional lightweight consumers
3. Grafana dashboards (see `grafana/`)

If you require the historical implementation details (endpoints, SSE diff mode, adaptive alerts UI) inspect git history:
```
Legacy web dashboard README content merged into core `README.md` under dashboard sections.
File retained briefly as tombstone; will be removed once external references updated.

For any historical diff review:
	git log -- README_web_dashboard.md
```

Deprecation timeline: Archived 2025-10-01 (Release R). Planned removal after R+1.

Status: [D] Deprecated – superseded by panels JSON + summary + Grafana.

Please update external links to point to the canonical README.

Note (2025-10-15): A lightweight FastAPI app is still shipped for JSON endpoints used by Grafana Infinity. The baseline launcher starts it on http://127.0.0.1:9500, providing `/api/overlay` (weekday masters) and `/api/live_csv` (today's CSV time series: tp, avg_tp). See the generated dashboard “G6 Overlays – Live from CSV (Infinity)”.
