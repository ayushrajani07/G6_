# Pipeline Metrics PromQL Cheat Sheet & Dashboard Suggestions

This document captures Prometheus / Grafana usage patterns for the newly added pipeline metrics.

## 1. New Metrics (Summary)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_pipeline_cycle_success | Gauge | (none) | 1 if last cycle had zero phase errors else 0 |
| g6_pipeline_cycles_total | Counter | (none) | Total pipeline cycles executed (summary produced) |
| g6_pipeline_cycles_success_total | Counter | (none) | Successful cycles (no phase errors) |
| g6_pipeline_cycle_error_ratio | Gauge | (none) | phases_error / phases_total for last cycle |
| g6_pipeline_cycle_success_rate_window | Gauge | (none) | Rolling success rate over last N cycles (env deque) |
| g6_pipeline_cycle_error_rate_window | Gauge | (none) | Rolling error rate over last N cycles |
| g6_pipeline_phase_duration_seconds (histogram family) | Histogram | phase, final_outcome | Per-phase execution wall time (seconds) |
| g6_pipeline_trends_success_rate | Gauge | (none) | Long-horizon success rate from trends aggregation |
| g6_pipeline_trends_cycles | Gauge | (none) | Number of cycles represented in trends file |

Associated existing counters you may combine:
- g6_pipeline_phase_attempts_total
- g6_pipeline_phase_retries_total
- g6_pipeline_phase_outcomes_total
- g6_pipeline_phase_duration_ms_total
- g6_pipeline_phase_runs_total
- g6_pipeline_phase_error_records_total

---
## 2. Core Health & Throughput
Instant success rate (counter-derived):
```
(
  increase(g6_pipeline_cycles_success_total[5m])
/
  increase(g6_pipeline_cycles_total[5m])
)
```
Cycle throughput (cycles/sec; *60 for per-minute):
```
rate(g6_pipeline_cycles_total[5m])
```
Rolling window gauge (already computed):
```
g6_pipeline_cycle_success_rate_window
```
Current phase error ratio (last cycle):
```
g6_pipeline_cycle_error_ratio
```
Rolling error rate gauge:
```
g6_pipeline_cycle_error_rate_window
```
Trend vs rolling drift:
```
(g6_pipeline_trends_success_rate - g6_pipeline_cycle_success_rate_window)
```

---
## 3. Error Diagnostics
Per-phase outcome distribution (5m):
```
sum by (phase, final_outcome) (
  increase(g6_pipeline_phase_outcomes_total[5m])
)
```
Phase error rate:
```
sum by (phase) (increase(g6_pipeline_phase_outcomes_total{final_outcome!="ok"}[5m]))
/
sum by (phase) (increase(g6_pipeline_phase_outcomes_total[5m]))
```
Retry incidence rate:
```
sum(increase(g6_pipeline_phase_retries_total[5m]))
/
sum(increase(g6_pipeline_phase_attempts_total[5m]))
```
Structured error classification (if enabled):
```
sum by (classification) (increase(g6_pipeline_phase_error_records_total[5m]))
```

---
## 4. Latency (Histogram)
Bucket rate aggregate (per phase):
```
phase_latency_bucket =
  sum by (phase, le) (
    rate(g6_pipeline_phase_duration_seconds_bucket[5m])
  )
```
P95 latency per phase:
```
histogram_quantile(0.95, phase_latency_bucket)
```
Global P95:
```
histogram_quantile(
  0.95,
  sum by (le) (rate(g6_pipeline_phase_duration_seconds_bucket[5m]))
)
```
Compare success vs error latency:
```
histogram_quantile(
  0.90,
  sum by (phase, le) (rate(g6_pipeline_phase_duration_seconds_bucket{final_outcome="ok"}[5m]))
)
```
vs
```
histogram_quantile(
  0.90,
  sum by (phase, le) (rate(g6_pipeline_phase_duration_seconds_bucket{final_outcome!="ok"}[5m]))
)
```
Mean per phase (seconds):
```
sum by (phase) (rate(g6_pipeline_phase_duration_seconds_sum[5m]))
/
sum by (phase) (rate(g6_pipeline_phase_duration_seconds_count[5m]))
```
Cross-check with ms counter:
```
(
  sum by (phase) (increase(g6_pipeline_phase_duration_ms_total[5m])) / 1000
)
/
sum by (phase) (increase(g6_pipeline_phase_runs_total[5m]))
```

---
## 5. Ratios & SLO Views
30m success rate:
```
pipeline_success_rate_30m =
  increase(g6_pipeline_cycles_success_total[30m])
/
  increase(g6_pipeline_cycles_total[30m])
```
Error budget burn (SLO 99%):
```
current_error_fraction_5m = (
  increase(g6_pipeline_cycles_total[5m]) - increase(g6_pipeline_cycles_success_total[5m])
) / increase(g6_pipeline_cycles_total[5m])

burn_rate_5m = current_error_fraction_5m / 0.01
```
Latency regression ratio (P95 5m vs 1h):
```
histogram_quantile(0.95, sum by (phase, le) (rate(g6_pipeline_phase_duration_seconds_bucket[5m])))
/
histogram_quantile(0.95, sum by (phase, le) (rate(g6_pipeline_phase_duration_seconds_bucket[1h]))) > 1.5
```

---
## 6. Consistency / Drift Checks
Rolling vs trend success drift:
```
abs(g6_pipeline_trends_success_rate - g6_pipeline_cycle_success_rate_window)
```
Warmup guard:
```
g6_pipeline_trends_cycles < 20
```
Fallback if rolling window gauge absent:
```
coalesce(
  g6_pipeline_cycle_success_rate_window,
  increase(g6_pipeline_cycles_success_total[15m]) / increase(g6_pipeline_cycles_total[15m])
)
```
Complement check:
```
(1 - g6_pipeline_cycle_success_rate_window) - g6_pipeline_cycle_error_rate_window
```

---
## 7. Suggested Recording Rules
```
record: pipeline:cycles:rate1m
expr: rate(g6_pipeline_cycles_total[1m])

record: pipeline:success_rate:5m
expr: increase(g6_pipeline_cycles_success_total[5m]) / increase(g6_pipeline_cycles_total[5m])

record: pipeline:phase:latency_p95
expr: |
  histogram_quantile(
    0.95,
    sum by (phase, le) (rate(g6_pipeline_phase_duration_seconds_bucket[5m]))
  )

record: pipeline:phase:error_rate
expr: |
  sum by (phase) (increase(g6_pipeline_phase_outcomes_total{final_outcome!="ok"}[5m]))
  /
  sum by (phase) (increase(g6_pipeline_phase_outcomes_total[5m]))

record: pipeline:retry_rate
expr: |
  sum(increase(g6_pipeline_phase_retries_total[5m]))
  /
  sum(increase(g6_pipeline_phase_attempts_total[5m]))
```

---
## 8. Alert Suggestions
| Alert | Expression | For | Purpose |
|-------|------------|-----|---------|
| Sustained success drop | pipeline:success_rate:5m < 0.98 | 10m | Early warning |
| Fast burn (SLO=99%) | (1 - pipeline:success_rate:5m)/0.01 > 5 | 5m | Rapid error consumption |
| Phase latency regression | pipeline:phase:latency_p95 > 1.5 * on(phase) pipeline:phase:latency_p95 offset 1h | 10m | Perf regression |
| Retry spike | pipeline:retry_rate > 0.10 | 15m | Transient instability |
| Error ratio spike | avg_over_time(g6_pipeline_cycle_error_ratio[5m]) > 0.05 | 10m | Rising phase failures |
| Rolling vs trend divergence | abs(g6_pipeline_trends_success_rate - g6_pipeline_cycle_success_rate_window) > 0.05 | 20m | Regime shift |

Tune thresholds to empirical baselines.

---
## 9. Grafana Layout (Proposed)
1. Overview Row: success rate (rolling + counter), trend success rate, cycle throughput, retry rate.
2. Cycle Health: success & error lines, last error ratio single-value.
3. Phase Performance: P95 heatmap, phase table (P95/P50/mean), latency regression comparison.
4. Errors & Retries: stacked non-ok outcomes, phase error rate table, retries per phase bar.
5. Rolling vs Trend: dual success rates, drift gauge, trends sample size gauge.
6. Latency Regression Watch: selected critical phases P95 over time with offset overlay.
7. SLO/Burn: multi-window burn rates and remaining error budget projection.
8. Drilldown: raw histogram buckets & last N cycle summaries (external if needed).

---
## 10. Validation Cross-Checks
Gauge vs counter success rate:
```
(
  increase(g6_pipeline_cycles_success_total[15m]) / increase(g6_pipeline_cycles_total[15m])
) - avg_over_time(g6_pipeline_cycle_success_rate_window[15m])
```
Should be ~0.

Histogram vs ms counter mean difference:
```
(
  sum(rate(g6_pipeline_phase_duration_seconds_sum[5m])) / sum(rate(g6_pipeline_phase_duration_seconds_count[5m]))
) - (
  (sum(increase(g6_pipeline_phase_duration_ms_total[5m])) / 1000) / sum(increase(g6_pipeline_phase_runs_total[5m]))
)
```
Near zero; drift implies an observe or accounting issue.

---
## 11. Triage Flow
1. Success rate dips → check retry_rate. If high: transient upstream instability.
2. If retries low: inspect phase_outcomes for fatal/abort spikes.
3. Latency P95 rising first: look for impending timeouts or saturation.
4. Trend success stable but rolling declining: investigate recent deploys or data quality.
5. Single-phase latency spike: isolate provider or code path.

---
## 12. Quick cURL Query Example
```
curl -s "http://prometheus:9090/api/v1/query?query=increase(g6_pipeline_cycles_success_total[5m])%20/%20increase(g6_pipeline_cycles_total[5m])" | jq
```

---
## 13. Future Enhancements
- Dynamic pre-registration histogram buckets (env parsed earlier)
- Retry rate gauges (phases_with_retries / total)
- Success streak gauge
- Retry distribution histogram
- Phase-level moving error ratio gauges

---
*End of cheat sheet.*
