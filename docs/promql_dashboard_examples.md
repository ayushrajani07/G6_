# PromQL Dashboard & Alert Examples

_Last updated: 2025-09-27_

This guide provides ready-to-drop PromQL queries for dashboards and alerting around the new analytics depth and risk aggregation metrics.

## 1. Volatility Surface Coverage (Global)

Rows by source (stacked area):
```
sum by (source) (g6_vol_surface_rows{index="global"})
```
Interpolated fraction (panel / single stat):
```
(avg by (index) (g6_vol_surface_interpolated_fraction{index="global"})) * 100
```
Suggested threshold visualization (line at 40%): use dashboard threshold or:
```
(g6_vol_surface_interpolated_fraction{index="global"} > 0.40)
```

## 2. Per-Expiry Coverage (Optional Flag)
Enable with `G6_VOL_SURFACE_PER_EXPIRY=1` (cardinality cost grows with distinct expiries).

Raw vs interpolated per-expiry (top N expiries by total rows):
```
# Total rows per expiry
vol_surface_rows_total = sum by (expiry) (g6_vol_surface_rows_expiry{index="global"})
# Top 5 expiries list (run in explorer) then plug into grafana variable or use regex.

sum by (expiry, source) (g6_vol_surface_rows_expiry{index="global",expiry=~"2025-0[1-3]-.."})
```
Interpolated fraction heatmap (expiry on Y, time on X):
```
g6_vol_surface_interpolated_fraction_expiry{index="global"}
```
Alert for expiry-level interpolation spike > 55% over 5m:
```
max_over_time(g6_vol_surface_interpolated_fraction_expiry{index="global"}[5m]) > 0.55
```
Cardinality watchdog (count active per-expiry series):
```
count(sum by (expiry, source) (g6_vol_surface_rows_expiry{index="global"})) > 120
```

## 3. Risk Aggregation Coverage & Exposures
Total rows aggregated (sanity):
```
sum(g6_risk_agg_rows{index="global"})
```
Delta / vega notionals per bucket (stacked bar):
```
sum by (bucket) (g6_risk_agg_delta_notional{index="global"})
sum by (bucket) (g6_risk_agg_vega_notional{index="global"})
```
Notional imbalance ratio (|vega| / |delta|) guarded against div-by-zero:
```
clamp_max(
  sum(abs(g6_risk_agg_vega_notional{index="global"}))
  /
  clamp_min(sum(abs(g6_risk_agg_delta_notional{index="global"})), 1e-6)
, 1000)
```

## 4. Bucket Utilization Gauge
Percent of defined buckets with at least one option (recent surface build). Metric emits 0..1.
Gauge:
```
(g6_risk_agg_bucket_utilization{index="global"}) * 100
```
Low utilization alert (<50% for 10m):
```
min_over_time(g6_risk_agg_bucket_utilization{index="global"}[10m]) < 0.50
```
Sudden drop (>25% absolute fall in 5m):
```
(
  max_over_time(g6_risk_agg_bucket_utilization{index="global"}[5m])
  -
  min_over_time(g6_risk_agg_bucket_utilization{index="global"}[5m])
) > 0.25
```

## 5. Build Health / Recency
Surface build cadence (counter rate):
```
rate(g6_vol_surface_builds{index="global"}[5m])
```
Build latency p95:
```
histogram_quantile(0.95, sum by (le) (rate(g6_vol_surface_build_seconds_bucket{index="global"}[5m])))
```
Stale build alert (no build in last 6m):
```
(time() - g6_vol_surface_last_build_unixtime{index="global"}) > 360
```

## 6. Interpolation Quality Signals
High sustained interpolation fraction (>60% over 15m):
```
avg_over_time(g6_vol_surface_interpolated_fraction{index="global"}[15m]) > 0.60
```
Per-expiry divergence vs global (+20pp):
```
(g6_vol_surface_interpolated_fraction_expiry{index="global"}
 - on() g6_vol_surface_interpolated_fraction{index="global"}) > 0.20
```

## 7. Suggested Alert Rules (YAML snippets)
Example (Prometheus rule file excerpt):
```yaml
- alert: VolSurfaceStale
  expr: (time() - g6_vol_surface_last_build_unixtime{index="global"}) > 360
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Vol surface stale (>6m)"
    description: "No successful build detected for >6 minutes. Investigate data pipeline or provider latency."

- alert: VolSurfaceHighInterpolation
  expr: avg_over_time(g6_vol_surface_interpolated_fraction{index="global"}[15m]) > 0.60
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High interpolation fraction"
    description: ">60% interpolated rows sustained over 15m. Underlying raw bucket coverage degraded."

- alert: RiskBucketUtilizationLow
  expr: min_over_time(g6_risk_agg_bucket_utilization{index="global"}[10m]) < 0.50
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Risk bucket utilization <50%"
    description: "Coverage collapse across moneyness buckets. Check upstream option feed completeness."
```

## 8. Dashboard Panel Ideas
| Panel | Visualization | PromQL | Notes |
|-------|--------------|--------|-------|
| Surface Rows by Source | Stacked area | `sum by (source) (g6_vol_surface_rows{index="global"})` | Watch raw vs interp balance |
| Interpolated Fraction | Single Stat | `g6_vol_surface_interpolated_fraction{index="global"} * 100` | Threshold at 40/60% |
| Per-Expiry Interp Heatmap | Heatmap | `g6_vol_surface_interpolated_fraction_expiry{index="global"}` | Requires per-expiry flag |
| Bucket Utilization | Gauge | `g6_risk_agg_bucket_utilization{index="global"} * 100` | Aim >70% normal |
| Delta Notional by Bucket | Bar | `sum by (bucket) (g6_risk_agg_delta_notional{index="global"})` | Compare distribution |
| Vega/Delta Imbalance | Single Stat | ratio query above | Investigate skew |
| Surface Build Duration p95 | Stat | histogram_quantile(0.95, ...) | Latency regression detection |

## 9. Cardinality Guidance
- Leave `G6_VOL_SURFACE_PER_EXPIRY` off unless diagnosing expiry-specific coverage issues.
- Consider recording rules downsampling per-expiry series into hourly averages to reduce long-term storage cost.
- Alerting should generally target global metrics; use per-expiry metrics for root cause analysis.

## 10. Quick Copy Reference
```
# Core
sum by (source) (g6_vol_surface_rows{index="global"})
g6_vol_surface_interpolated_fraction{index="global"}
# Risk
sum by (bucket) (g6_risk_agg_delta_notional{index="global"})
# Utilization
(g6_risk_agg_bucket_utilization{index="global"}) * 100
# Staleness
(time() - g6_vol_surface_last_build_unixtime{index="global"})
```

---
Contributions: Add new queries near related metric groupings. Keep expressions concise; prefer functions (`avg_over_time`, `max_over_time`) over manual subquery hacks.
