# G6 Metrics Dictionary (Deprecated Stub)

This content has been consolidated into the authoritative references:

- `METRICS.md` (human-curated taxonomy and narrative)
- `METRICS_CATALOG.md` (auto-generated spec-driven catalog)

`metrics_dict.md` is retained temporarily for backward compatibility and
external links. No new updates will be applied here.

Removal Criteria:
- Two consecutive releases with no inbound links in code / docs
- CHANGELOG entry announcing final removal

Please update bookmarks to point to `METRICS.md`.

---
## 2. Index & Market Snapshot
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_index_price | G | index | Current index price. |
| g6_index_atm_strike | G | index | Current at-the-money strike. |
| g6_options_collected | G | index,expiry | Number of options collected for expiry in current/last cycle. |
| g6_put_call_ratio | G | index,expiry | Put/Call ratio per expiry. |
| g6_index_options_processed | G | index | Options processed in last cycle (per index). |
| g6_index_options_processed_total | C | index | Cumulative options processed (monotonic). |
| g6_index_avg_processing_time_seconds | G | index | Avg per-option processing time last cycle. |
| g6_index_success_rate_percent | G | index | Success percent (rolling / derived). |
| g6_index_last_collection_unixtime | G | index | Last successful collection timestamp. |
| g6_index_current_atm_strike | G | index | Mirror of ATM strike for stable label set. |
| g6_index_current_volatility | G | index | Representative index volatility (e.g., ATM IV). |
| g6_index_attempts_total | C | index | Cumulative index collection attempts. |
| g6_index_failures_total | C | index,error_type | Cumulative index collection failures by error type. |
| g6_index_cycle_attempts | G | index | Attempts within most recent cycle. |
| g6_index_cycle_success_percent | G | index | Success percent for most recent cycle (per index). |

---
## 3. Option-Level Metrics
| Metric | Type | Labels | Description | Cardinality Considerations |
|--------|------|--------|-------------|----------------------------|
| g6_option_price | G | index,expiry,strike,type | Option price (last/representative). | High (gating candidate). |
| g6_option_volume | G | index,expiry,strike,type | Traded volume. | High |
| g6_option_oi | G | index,expiry,strike,type | Open interest. | High |
| g6_option_iv | G | index,expiry,strike,type | Implied volatility estimate. | High |
| g6_option_delta | G | index,expiry,strike,type | Greek delta. | High |
| g6_option_theta | G | index,expiry,strike,type | Greek theta. | High |
| g6_option_gamma | G | index,expiry,strike,type | Greek gamma. | High |
| g6_option_vega | G | index,expiry,strike,type | Greek vega. | High |
| g6_option_rho | G | index,expiry,strike,type | Greek rho. | High |

---
## 4. Field Coverage / Data Quality (Per Expiry)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_missing_option_fields_total | C | index,expiry,field | Count of missing option fields (volume/oi/avg_price). |
| g6_option_field_coverage_ratio_percent | G | index,expiry | Percent coverage of core option fields. |
| g6_synthetic_quotes_used_total | C | index,expiry | Synthetic quote insertions (fallback). |
| g6_zero_option_rows_total | C | index,expiry | Rows where CE+PE metrics are both zero. |
| g6_instrument_coverage_percent | G | index,expiry | Percent of requested strikes that produced at least one instrument. |
| g6_index_data_quality_score_percent | G | index | Aggregated per-index DQ score (0-100). |
| g6_index_dq_issues_total | C | index | Total data quality issues observed (cumulative). |

---
## 5. IV / Greeks Estimation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_iv_estimation_success_total | C | index,expiry | Successful IV computations. |
| g6_iv_estimation_failure_total | C | index,expiry | Failed IV computations. |
| g6_iv_estimation_avg_iterations | G | index,expiry | Rolling average iterations of IV solver. |
| g6_greeks_success_total | C | index,expiry | Successful per-option Greek computations. |
| g6_greeks_fail_total | C | index,expiry | Failed per-option Greek computations. |
| g6_greeks_batch_fail_total | C | index,expiry | Batch-level Greek computation failures. |

---
## 6. Performance / Throughput
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_uptime_seconds | G | – | Process uptime since start. |
| g6_collection_cycle_time_seconds | G | – | EMA of end-to-end cycle wall time. |
| g6_processing_time_per_option_seconds | G | – | Avg processing time per option (last cycle). |
| g6_api_response_time_ms | G | – | EMA upstream API latency. |
| g6_api_response_latency_ms | H | – | Distribution of raw API latencies (ms). |
| g6_options_processed_total | C | – | Total options processed (cumulative). |
| g6_options_processed_per_minute | G | – | Rolling throughput (per minute). |
| g6_cycles_per_hour | G | – | Observed cycles per hour (derived). |
| g6_api_success_rate_percent | G | – | Upstream API call success %. |
| g6_collection_success_rate_percent | G | – | Cycle success %. |
| g6_data_quality_score_percent | G | – | Composite data quality score. |

---
## 7. Resource & System Utilization
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_usage_mb | G | – | Resident memory footprint. |
| g6_cpu_usage_percent | G | – | Process CPU utilization %. |
| g6_disk_io_operations_total | C | – | Disk I/O operations (read+write increments). |
| g6_network_bytes_transferred_total | C | – | Network bytes (sent+recv increments). |

---
## 8. Cache / Error / Batch Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_cache_hit_rate_percent | G | – | Cache hit rate %. |
| g6_cache_items | G | – | Item count in cache. |
| g6_cache_memory_mb | G | – | Memory usage of cache. |
| g6_cache_evictions_total | C | – | Cache eviction count. |
| g6_batch_efficiency_percent | G | – | Efficiency relative to target batch size. |
| g6_avg_batch_size | G | – | Average batch size. |
| g6_batch_processing_time_seconds | G | – | Rolling average batch processing time. |
| g6_total_errors_total | C | – | Aggregate errors (all categories). |
| g6_api_errors_total | C | – | API related errors (legacy aggregate). |
| g6_network_errors_total | C | – | Network related errors (legacy aggregate). |
| g6_data_errors_total | C | – | Data validation errors (legacy aggregate). |
| g6_error_rate_per_hour | G | – | Derived error rate per hour. |
| g6_api_errors_by_provider_total | C | provider,component,error_type | Labeled API errors. |
| g6_network_errors_by_provider_total | C | provider,component,error_type | Labeled network errors. |
| g6_data_errors_by_index_total | C | index,component,error_type | Labeled data errors. |
| g6_metric_stall_events_total | C | metric | Stall watchdog events for a metric class. |

---
## 9. Storage & Panels
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_csv_files_created_total | C | – | CSV files created. |
| g6_csv_records_written_total | C | – | CSV record lines written. |
| g6_csv_write_errors_total | C | – | CSV write failures. |
| g6_csv_disk_usage_mb | G | – | Disk usage attributable to CSV outputs. |
| g6_csv_cardinality_unique_strikes | G | index,expiry | Unique strikes encountered last write. |
| g6_csv_cardinality_suppressed | G | index,expiry | 1 if cardinality suppression active. |
| g6_csv_cardinality_events_total | C | index,expiry,event | Cardinality suppression event count. |
| g6_csv_overview_writes_total | C | index | Overview snapshot writes. |
| g6_csv_overview_aggregate_writes_total | C | index | Aggregated overview writes. |
| g6_influxdb_points_written_total | C | – | InfluxDB points written. |
| g6_influxdb_write_success_rate_percent | G | – | Influx write success %. |
| g6_influxdb_connection_status | G | – | 1 healthy / 0 down. |
| g6_influxdb_query_time_ms | G | – | Representative query latency. |
| g6_backup_files_created_total | C | – | Backup files created. |
| g6_last_backup_unixtime | G | – | Timestamp of last backup. |
| g6_backup_size_mb | G | – | Size of last backup data (MB). |
| g6_panels_writes_total | C | – | Panel JSON writes. |
| g6_panels_write_errors_total | C | – | Panel JSON write errors. |
| g6_runtime_status_writes_total | C | – | Runtime status JSON writes. |
| g6_runtime_status_write_errors_total | C | – | Runtime status write errors. |
| g6_runtime_status_last_write_unixtime | G | – | Last runtime status write timestamp. |
| g6_build_info | G | version,git_commit,config_hash | Build metadata gauge (always value 1). Auto-registered during bootstrap; override labels via G6_VERSION / G6_GIT_COMMIT. |

---
## 10. Overlay Quality
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_overlay_quality_last_run_issues | G | index | Issues detected in last overlay run (per index). |
| g6_overlay_quality_last_report_unixtime | G | – | Timestamp of last overlay quality report write. |
| g6_overlay_quality_last_run_total_issues | G | – | Total overlay quality issues last run. |
| g6_overlay_quality_last_run_critical | G | index | Critical overlay issues last run. |

---
## 11. Sampling / Cardinality Control
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_metric_sampling_events_total | C | category,decision,reason | Records sampling/gating decisions for per-option emission. |
| g6_metric_sampling_rate_limit_per_sec | G | category | Configured per-second rate limit for sampling category. |

---
## 12. Memory Pressure / Adaptive Degradation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_pressure_level | G | – | Memory pressure tier (0-3). |
| g6_memory_pressure_actions_total | C | action,tier | Mitigation actions taken under memory pressure. |
| g6_memory_pressure_seconds_in_level | G | – | Seconds spent in current memory pressure level. |
| g6_memory_pressure_downgrade_pending | G | – | 1 if downgrade pending. |
| g6_memory_depth_scale | G | – | Current strike depth scaling factor (0-1). |
| g6_memory_per_option_metrics_enabled | G | – | 1 if per-option metrics currently enabled. |
| g6_memory_greeks_enabled | G | – | 1 if Greek/IV computation enabled. |
| g6_tracemalloc_total_kb | G | – | Total allocated size from tracemalloc (KiB). |
| g6_tracemalloc_topn_kb | G | – | Aggregated top-N allocation group size (KiB). |

---
## 13. ATM Batch Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_atm_batch_time_seconds | G | index | Elapsed wall time of ATM batch collection. |
| g6_atm_avg_option_time_seconds | G | index | Avg per-option processing time within ATM batch. |

---
## 14. Circuit Breaker Metrics (Exporter)
| Metric | Type | Labels | Description | Notes |
|--------|------|--------|-------------|-------|
| g6_circuit_state_simple | G | name | Circuit state (0=closed,1=half,2=open). | Legacy label name. |
| g6_circuit_current_timeout_seconds | G | name | Current reset timeout. | Legacy label name. |
| g6_circuit_state | G | component | Circuit state (standardized label). | Preferred going forward. |
| g6_circuit_timeout_seconds | G | component | Current reset timeout (standard label). | Preferred. |

---
## 15. Planned / Roadmap Metrics (Not Implemented Yet)
| Metric (Planned) | Type | Labels | Purpose |
|------------------|------|--------|---------|
| g6_strike_depth_scale_factor | G | index | Adaptive strike depth scaling factor (Section 4.2 roadmap). |
| g6_cycle_time_seconds | H | – | Distribution of end-to-end cycle times. |
| g6_cardinality_guard_trips_total | C | reason | Times the guard auto-disabled per-option metrics. |
| g6_component_health | G | component | Health state (0/1/2). |
| g6_cycle_sla_breach_total | C | index | Cycle exceeded SLA threshold. |
| g6_data_gap_seconds | G | index | Gap since last successful data point. |
| g6_missing_cycles_total | C | index | Integrity checker gaps. |
| g6_provider_failover_total | C | from,to | Provider failover transitions. |
| g6_config_deprecated_keys_total | C | key | Deprecated config key occurrences. |

---
## 16. High Cardinality Advisory
Per-option metrics (price, volume, OI, IV, Greeks) can create large time-series sets: (indices * expiries * strikes * 2 option types). Use cardinality management environment variables:
- `G6_METRICS_CARD_ENABLED=1`
- `G6_METRICS_CARD_ATM_WINDOW` limit window around ATM
- `G6_METRICS_CARD_RATE_LIMIT_PER_SEC` aggregate emission cap
- `G6_METRICS_CARD_CHANGE_THRESHOLD` suppress small deltas
Sampling decisions are auditable via `g6_metric_sampling_events_total`.

---
## 17. Naming Conventions
Prefix `g6_` is reserved. Suffix `_total` used for monotonic counters. Percent metrics include `_percent` (0-100 scale). Latencies with `_ms` are milliseconds; `_seconds` explicitly seconds. Histograms encode base unit in name.

---
_Keep this file updated whenever new metrics are added or deprecated. Cross-link with `docs/future_enhancements.md` change log for historical context._
