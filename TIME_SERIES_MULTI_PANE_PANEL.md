# Multi-Pane Time Series Explorer Dashboard

Date: 2025-10-05
Status: Phase 1 complete (single + multi-select implemented) – Prometheus + Grafana native templating (no custom webapp layer yet).

## Goal
Provide an operator-friendly dashboard that allows rapid ad-hoc inspection of any governed metric with multiple synchronized panes (raw / rate / window comparison / ratio) leveraging existing Prometheus data (historical) plus near-real time scrapes.

## Scope (Phase 1)
* Dashboard plan `multi_pane_explorer` with a template variable `$metric` (multi-select enabled) enumerating governed metrics (static list for determinism; capped at 150 names).
* Four base panels referencing `$metric` and marked with `repeat=metric` so Grafana duplicates them per selected metric:
  1. Raw Value (or sum by labels for counters/gauges)
  2. 5m Rate (if counter; direct value if gauge/hist base)
  3. Short vs Long Window p95 (histograms) or 1m vs 5m rate (counters) comparison
  4. 5m / 30m Ratio panel (latency p95 ratio for histograms, rate ratio for counters)
* Deterministic IDs + existing metadata enrichment.
* Works purely through PromQL without custom back-end.

## Non-Goals (Phase 1)
* Custom multi-pane reflow UI beyond Grafana standard grid.
* SSE/WebSocket push integration (future: integrate with internal streaming bus if adopted).
* Histogram-aware dynamic substitution of p95 panels (deferred).

## Future Enhancements
| Phase | Enhancement | Notes |
|-------|------------|-------|
| 2 | Multi-select & dynamic panel duplication | IMPLEMENTED (repeat panels per selected metric).
| 2 | Histogram-aware p95 window & ratio panels | IMPLEMENTED (generic templates; show data when recording rules exist).
| 2 | Conditional histogram panel repetition | IMPLEMENTED via separate `metric_hist` multi-select variable.
| 3 | Overlay toggle (short-window live approximation) | IMPLEMENTED (`overlay` variable adds 30s rate target when 'on').
| 3 | Quantile configurability (p50/p90/p95/p99) | IMPLEMENTED (`q` variable drives histogram recording rule selection).
| 4 | Quantile summary table panel | IMPLEMENTED (`histogram_summary` table with 5m, 30m, ratio, delta targets + thresholds). Ratio panel later collapsed into summary (Phase 4b).
| 4b | Delta column & symmetric thresholds | IMPLEMENTED (configurable symmetric bands).
| 4c | Compact variant (`multi_pane_explorer_compact`) | IMPLEMENTED (reduced heights, no cumulative panel, 5 panels total).
| 2 | Optional percentile overlay for gauges (if recording rules added) | Requires extended rules synthesis.
| 3 | Live streaming overlay (SSE) | Overlays last N points from bus on top of Prometheus query lines.
| 3 | Panel-level anomaly bands | Use recording rule baseline vs current deviation.
| 4 | Embedded inventory diff quick view | Query inventory export & highlight rename churn for selected metric.
| 4 | Alert context side panel | Link active/firing alerts referencing selected metric.

## PromQL Strategy
* Counter rate (5m): `sum(rate($metric[5m]))`
* Counter rate (1m): `sum(rate($metric[1m]))`
* Window ratio (1m/5m): `sum(rate($metric[1m])) / clamp_min(sum(rate($metric[5m])), 1)`
* Histogram p95 (5m): `histogram_quantile(0.95, sum by (le) (rate(${metric}_bucket[5m])))`
* Histogram p95 (30m): same with `[30m]` window.
* Latency ratio p95: `(<p95_5m_expr>) / clamp_min((<p95_30m_expr>), 0.001)`

## Implementation Notes
Generator hook will detect special slug `multi_pane_explorer` and inject:
* Grafana templating variable `metric` (query based) – simplest: `label_values(up)` placeholder replaced dynamically? For deterministic spec we may render a static JSON array from spec metrics.
* Panels referencing `$metric` in expressions. Since semantic signature includes title + expr(s), drift only when we change structure.

## Risks
* Large metric list -> dropdown performance: mitigate by static list (no expensive regex) and consider filtering groups.
* Histograms naming consistency (`_bucket` suffix) assumed; fallback gracefully if missing.
* Some metrics may not have 1m signal (low update frequency) – ratio panel may show sparse data; acceptable.

## Exit Criteria (Phase 1)
* Dashboard JSON generated with four panels and template variable.
* Works for at least one counter and one histogram (if present) when selecting manually (hist panels degrade gracefully if not histogram).
* No drift outside new dashboard addition.

---
End of document.

## Compact Variant Summary (2025-10-06)

Introduced `multi_pane_explorer_compact` to increase signal density:
* Removed cumulative total panel (often redundant for transient investigative workflows).
* Reduced base timeseries panel heights from 8 → 6.
* Summary and histogram window panels shift upward (y positions recast: summary at y=12, window at y=18).
* Added `g6_meta.compact=true` flag for downstream tooling awareness.

Delta thresholds refactored via `_delta_threshold_steps` helper allowing future tuning. Current default bands:
```
(-∞ .. -20%]  red
(-20% .. -5%] yellow
(-5% .. +5%)  green
[+5% .. +20%) yellow
[+20% .. ∞)   red
```
This symmetric approach mitigates directional bias and highlights both regressions and sudden improvements (which may indicate sampling or instrumentation anomalies).

Future Consideration: Expose threshold config via environment variable or external JSON spec if operators require tuning without regeneration.