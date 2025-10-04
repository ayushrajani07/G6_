# G6 Observability Dashboards

This document maps high-level platform concerns to the Grafana dashboards now included in the repository and the primary Prometheus metrics each visualizes.

> Scope: Raw per-option price / greeks metrics are intentionally excluded to avoid cardinality & visual noise. Focus is on operational, aggregation and adaptive analytics.

## Dashboard Catalog

| Dashboard | File | Purpose | Primary Audience |
|-----------|------|---------|------------------|
| Core Overview | `grafana/dashboards/g6_core_overview.json` | Executive & runtime summary: freshness, cycles, success %, latency, error rate, resource footprint | Eng / On-call |
| Health Status | `grafana/dashboards/g6_health_status.json` | Health check pass/fail + check latency + freshness snapshot | SRE / On-call |
| Index Health | `grafana/dashboards/g6_index_health.json` | Per-index throughput, success, timing and ATM context | Quant / Eng |
| Memory Adaptation | `grafana/dashboards/g6_memory_adaptation.json` | Adaptive memory pressure levels, actions, feature toggles | Eng / Perf |
| Storage Pipeline | `grafana/dashboards/g6_storage_pipeline.json` | CSV write throughput, Influx health, backups | Eng / Data Ops |
| Error Breakdown | `grafana/dashboards/g6_error_breakdown.json` | Categorized error rates and success correlations | Eng / On-call |
| Cache & Batch Efficiency | `grafana/dashboards/g6_cache_batch_efficiency.json` | Cache performance & batch processing efficiency & latency | Eng / Perf |

## Metric → Dashboard Mapping (Selected)

| Metric / Family | Dashboard(s) | Notes |
|-----------------|--------------|-------|
| `g6_collection_cycles_total`, duration summary buckets | Core Overview | 6h increase + derived avg durations |
| `g6_collection_success_rate_percent` | Core Overview | Success % over current window |
| `g6_last_success_cycle_unixtime` | Core Overview, Health Status | Core shows age; Health for freshness panel |
| `g6_api_response_latency_ms_bucket` (histogram) | Core Overview | p95 via histogram_quantile |
| `g6_total_errors_total`, `g6_collection_errors_total` | Core Overview (summary), Error Breakdown (detailed) | Summary vs categorized views |
| `g6_api_errors_total`, `g6_network_errors_total`, `g6_data_errors_total` | Error Breakdown | Legacy base totals (kept for compatibility) |
| `g6_api_errors_by_provider_total{provider,component,error_type}` | Error Breakdown | Labeled API errors (preferred for drilldown) |
| `g6_network_errors_by_provider_total{provider,component,error_type}` | Error Breakdown | Labeled network errors (preferred for drilldown) |
| `g6_data_errors_by_index_total{index,component,error_type}` | Error Breakdown, Index Health | Labeled data/validation errors |
| `g6_index_options_processed` / `_total` | Index Health | Per-index last cycle vs cumulative |
| `g6_index_success_rate_percent` | Index Health | Rolling or computed success metric |
| `g6_index_avg_processing_time_seconds` | Index Health | Per-index processing efficiency |
| `g6_atm_batch_time_seconds`, `g6_atm_avg_option_time_seconds` | Index Health | ATM specific timing |
| `g6_index_current_atm_strike`, `g6_index_current_volatility` | Index Health | Context analytics |
| `g6_memory_pressure_level`, related depth & feature flags | Memory Adaptation | Central adaptive control set |
| `g6_memory_pressure_actions_total` | Memory Adaptation | Rate + 1h aggregate |
| `g6_cache_hit_rate_percent`, `g6_cache_items`, `g6_cache_memory_mb` | Cache & Batch Efficiency | Performance / capacity |
| `g6_batch_processing_time_seconds_bucket` | Cache & Batch Efficiency | p50/p95 latency |
| `g6_batches_total` | Cache & Batch Efficiency | Batch throughput |
| — | — | — |
| — | — | — |
| `g6_csv_records_written_total`, overview write counters | Storage Pipeline | Write throughput |
| `g6_influxdb_*` family | Storage Pipeline | DB health & latency |
| `g6_backup_*` family | Storage Pipeline | Backup age & size |
| `g6_health_check_status`, `g6_health_check_duration_seconds_bucket` | Health Status | Per-check outcomes & latency |
| Runtime infra: `g6_cpu_usage_percent`, `g6_memory_usage_mb`, `g6_network_bytes_transferred_total` | Core Overview | Lightweight infra overlay |

## Navigation Model

- Start at Core Overview for health triage. Drill into:
  - Errors → Error Breakdown
  - Memory warnings → Memory Adaptation
  - Throughput irregularities per index → Index Health
  - Storage stalls → Storage Pipeline
  - Cache miss spikes or batch latency → Cache & Batch Efficiency
  - Persistent check failures → Health Status

## Deprecations

Removed legacy dashboards: `g6_observability.json`, `g6_storage_minimal.json` (superseded by structured thematic boards).

## SSE & Panels Additions (New Dashboards)

Additional focused dashboards introduced in the observability hardening phase:

| UID | File | Purpose | Key Metrics |
|-----|------|---------|-------------|
| g6-perf-001 | `grafana/dashboards/g6_perf_latency.json` | SSE publisher build & emit latency, event size & queue pressure | `g6_sse_pub_diff_build_seconds_*`, `g6_sse_pub_emit_latency_seconds_*`, `g6_sse_http_event_size_bytes_*`, `g6_sse_http_event_queue_latency_seconds_*` |
| g6-sec-001  | `grafana/dashboards/g6_sse_security.json` | Auth / ACL / rate limit & security drops | `g6_sse_http_auth_fail_total`, `g6_sse_http_forbidden_ip_total`, `g6_sse_http_forbidden_ua_total`, `g6_sse_http_rate_limited_total`, `g6_sse_http_security_events_dropped_total` |
| g6-panels-001 | `grafana/dashboards/g6_panels_integrity.json` | Panels integrity + diff vs full efficiency & need_full episodes | `g6_panels_integrity_ok`, `g6_panels_integrity_fail_total`, `g6_sse_http_events_sent_total{event_type=...}`, `g6_sse_need_full_total` |
> NOTE: The unified data quality dashboard now uses `g6_panels_integrity_failures_total` (plural) and `g6_panel_diff_writes_total{type=diff|full}` instead of the older `g6_panels_integrity_fail_total` and SSE event_type based queries. Update this table and legacy dashboard JSON (`g6_panels_integrity.json`) when deprecating the old metric names to avoid confusion.

Guidance:
1. Use Performance board when evaluating latency regressions flagged by readiness performance budgets.
2. Use Security board during incident response for suspicious connection churn or auth failures.
3. Use Panels board to confirm diff dominance after deploys and to correlate integrity failures with need_full recoveries.

Recommended Alert Seeds (extend existing ruleset):
| Condition | Expression (example) | Window |
|-----------|----------------------|--------|
| High diff build latency | `histogram_quantile(0.95, sum(rate(g6_sse_pub_diff_build_seconds_bucket[10m])) by (le)) > 0.012` | 10m |
| Elevated security drops | `sum(rate(g6_sse_http_security_events_dropped_total[5m])) > 1` | 5m |
| Diff ratio below target | `(sum(rate(g6_sse_http_events_sent_total{event_type="panel_diff"}[15m])) / sum(rate(g6_sse_http_events_sent_total{event_type=~"panel_diff|full_snapshot"}[15m]))) < 0.85` | 15m |
| Need full spike | `sum(rate(g6_sse_need_full_total[5m])) > 0` | 5m |

Import & provisioning follow the same pattern (shared `DS_PROM` variable). Increment the dashboard `version` field when adding panels.

## Suggested Recording Rules
(Implemented separately — see `prometheus/recording_rules.yml` once added.)

| Record | Expression | Justification |
|--------|------------|---------------|
| `g6:cycle_duration_avg_15m` | `rate(g6_collection_duration_seconds_sum[15m]) / rate(g6_collection_duration_seconds_count[15m])` | Reuse across dashboards |
| `g6:cycle_duration_avg_1h` | `rate(g6_collection_duration_seconds_sum[1h]) / rate(g6_collection_duration_seconds_count[1h])` | Consistency |
| `g6:api_latency_p95_5m` | `histogram_quantile(0.95, sum by (le) (rate(g6_api_response_latency_ms_bucket[5m])))` | Removes repeated long expression |
| `g6:error_rate_total_5m` | `rate(g6_total_errors_total[5m])` | Shared summary panel |
| `g6:api_error_rate_5m` | `sum by (provider,component,error_type) (rate(g6_api_errors_by_provider_total[5m]))` | API error velocity by dimension |
| `g6:network_error_rate_5m` | `sum by (provider,component,error_type) (rate(g6_network_errors_by_provider_total[5m]))` | Network error velocity by dimension |
| `g6:data_error_rate_5m` | `sum by (index,component,error_type) (rate(g6_data_errors_by_index_total[5m]))` | Data error velocity by index |

## Labeled Error Metrics and Aggregation

- New labeled counters provide consistent drilldown while preserving legacy totals:
  - g6_api_errors_by_provider_total{provider,component,error_type}
  - g6_network_errors_by_provider_total{provider,component,error_type}
  - g6_data_errors_by_index_total{index,component,error_type}
- Panels should prefer labeled series for breakdowns; base totals remain for quick summaries and backward compatibility.
- Aggregation rule used by the built-in summary processor: use base totals if present (>0), otherwise sum all labeled series for the category.
| `g6:options_per_min` | `g6_options_processed_per_minute` | Alias for clarity |
| `g6:cycles_per_hour` | `g6_cycles_per_hour` | Alias for clarity |
| `g6:freshness_minutes` | `(time() - g6_last_success_cycle_unixtime)/60` | Standard freshness gauge |

## Future Ideas
- Add service-level SLO overlay panels (burn rate for error budget) using multi-window, multi-burn queries.
- Introduce alert annotation streams for key error spikes.
- Add feature toggle change annotations (memory adaptation transitions).

---
Last updated: 2025-09-21
