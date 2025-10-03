# Metrics Usage Guide

This guide standardizes how code in this repo should READ metrics to avoid duplication and drift.

Goals:
- Single source of truth for reading metrics: MetricsAdapter (backed by MetricsProcessor)
- Keep producers (counters/gauges registration/emission) in `src/metrics/metrics.py`
- Provide normalized shapes for consumers via `UnifiedDataSource.get_metrics_data()`

## Read metrics (preferred)

- High-level, structured view for apps/scripts:
  - Use `from src.utils.metrics_adapter import get_metrics_adapter`
  - `ma = get_metrics_adapter()`
  - `pm = ma.get_platform_metrics()` for a typed view (performance, indices, storage, etc.)

- Normalized dict view inside UI/data-access:
  - Use `from src.data_access.unified_source import data_source`
  - `d = data_source.get_metrics_data()`
  - Keys: `indices` (Dict[str, Any]), `resources` (`cpu`, `memory_mb`), `cycle` (basic fields)

## Do NOT

- Do not parse Prometheus text directly in new code.
- Do not import `get_metrics_singleton()` for reads in new consumer code.
- Do not call `<metrics_url>/json` directly; go through adapter or UnifiedDataSource.

## Migration checklist

1) Replace direct imports of `src.metrics.metrics` in readers with:
   `from src.utils.metrics_adapter import get_metrics_adapter`

2) If you need a simple JSON-like structure, prefer `UnifiedDataSource.get_metrics_data()`.

3) Keep writes/registration in the metrics module as-is (emitting counters/gauges).

## Environment

- `G6_METRICS_URL` controls where the adapter fetches Prometheus metrics from (default: `http://127.0.0.1:9108/metrics`).
- `G6_DISABLE_METRICS_SOURCE=1` disables metrics reads in UnifiedDataSource (safe for tests).

## Troubleshooting

- If Prometheus is down, adapter returns None/empty structures (no exceptions).
- UnifiedDataSource caches for a short TTL and returns empty dicts on failure to keep UIs resilient.
