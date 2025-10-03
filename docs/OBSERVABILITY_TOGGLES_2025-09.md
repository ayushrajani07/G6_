# Observability Toggles and Metrics (2025-09)

This document lists recently added observability controls and related metrics.

## Structured JSON console logs

- Enable: `G6_JSON_LOGS=1`
- Details:
  - Emits JSON lines to the console.
  - Uses `orjson` when available, falls back to stdlib `json`.
  - Timestamp is from the log record epoch (`record.created`), avoiding naive datetimes.
- Related env:
  - `G6_VERBOSE_CONSOLE=1` restores full console formatter.
  - Default remains minimal message-only output.

## Data Quality metrics

The collectors validate enriched quote data and compute a simple per-batch score: `valid / total * 100`.

- Global gauge: `g6_data_quality_score_percent`
- Per-index gauge: `g6_index_data_quality_score_percent{index=...}`
- Issues counter: `g6_index_dq_issues_total{index=...}`

Invalid entries are excluded from downstream processing/persistence.

## Memory tracing (tracemalloc)

Optional, disabled by default. Provides lightweight visibility into allocation hotspots.

- Enable: `G6_ENABLE_TRACEMALLOC=1`
- Options:
  - `G6_TRACEMALLOC_TOPN=10` — aggregate top-N allocation groups
  - `G6_TRACEMALLOC_WRITE_SNAPSHOTS=1` — write snapshots as text
  - `G6_TRACEMALLOC_SNAPSHOT_DIR=logs/mem` — snapshot output directory
- Metrics:
  - `g6_tracemalloc_total_kb`
  - `g6_tracemalloc_topn_kb`

Implementation notes:
- Tracer is integrated in the unified collectors; samples are taken between indices and at cycle end.
- When snapshots are enabled, a compact `snapshot_top.txt` is updated with totals and recent top frames.
