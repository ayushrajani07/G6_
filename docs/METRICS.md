# G6 Platform Metrics Reference

Authoritative list of Prometheus metrics exported by the G6 options collection platform.

> Legend: Type abbreviations — C=Counter, G=Gauge, H=Histogram, S=Summary, R=Recording (derived in Prometheus rules).
>
> Naming conventions: All application metrics are prefixed with `g6_`. Counters end in `_total` when monotonic. Timestamps end in `_unixtime` and are seconds since epoch.

---
## 1. Core Cycle & Uptime
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_collection_cycles_total | C | — | Total collection cycles executed |
| g6_collection_duration_seconds | S | — | Per-cycle wall clock duration samples |
| g6_collection_errors_total | C | index, error_type | Cycle errors attributed to an index and categorized |
| g6_collection_cycle_in_progress | G | — | 1 while a cycle is running, else 0 |
| g6_last_success_cycle_unixtime | G | — | Unix timestamp of last fully successful cycle |

## 2. Index & High-Level Option Context
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_index_price | G | index | Latest index price |
| g6_index_atm_strike | G | index | Current at-the-money strike |
| g6_options_collected | G | index, expiry | Option rows collected in the cycle per expiry |
| g6_put_call_ratio | G | index, expiry | Put/Call ratio for expiry set |

## 3. Per-Option Detail (High Cardinality)
These gauges explode in cardinality; emission may be curtailed under memory pressure.
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_option_price | G | index, expiry, strike, type | Last observed option price |
| g6_option_volume | G | index, expiry, strike, type | Traded volume (latest snapshot) |
| g6_option_oi | G | index, expiry, strike, type | Open interest |
| g6_option_iv | G | index, expiry, strike, type | Implied volatility |
| g6_option_delta | G | index, expiry, strike, type | Option delta |
| g6_option_theta | G | index, expiry, strike, type | Option theta |
| g6_option_gamma | G | index, expiry, strike, type | Option gamma |
| g6_option_vega | G | index, expiry, strike, type | Option vega |
| g6_option_rho | G | index, expiry, strike, type | Option rho |

## 4. IV Estimation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_iv_estimation_success_total | C | index, expiry | Successful IV solves |
| g6_iv_estimation_failure_total | C | index, expiry | Failed/aborted IV solves |
| g6_iv_estimation_avg_iterations | G | index, expiry | Rolling avg solver iterations this cycle |

## 5. Performance & Throughput
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_uptime_seconds | G | — | Process uptime (seconds) |
| g6_collection_cycle_time_seconds | G | — | Avg cycle time (EMA/sliding) |
| g6_processing_time_per_option_seconds | G | — | Avg per-option processing time last cycle |
| g6_api_response_time_ms | G | — | Rolling mean upstream API response time (ms) |
| g6_api_response_latency_ms | H | — | Distribution of upstream API latencies (ms) |
| g6_options_processed_total | C | — | Cumulative option records processed |
| g6_options_processed_per_minute | G | — | Rolling throughput (options/min) |
| g6_cycles_per_hour | G | — | Rolling observed cycles/hour |
| g6_api_success_rate_percent | G | — | Rolling API success percentage |
| g6_collection_success_rate_percent | G | — | Rolling collection cycle success percentage |
| g6_data_quality_score_percent | G | — | Composite data quality score (0–100) |

## 6. Resource Utilization
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_usage_mb | G | — | Resident memory usage (MB) |
| g6_cpu_usage_percent | G | — | Process CPU utilization (%) |
| g6_disk_io_operations_total | C | — | Disk I/O operations cumulative |
| g6_network_bytes_transferred_total | C | — | Network bytes transferred cumulative |

## 7. Cache / Batch / Error Breakdown
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_cache_hit_rate_percent | G | — | Cache hit rate (%) |
| g6_cache_items | G | — | Items in cache |
| g6_cache_memory_mb | G | — | Estimated cache memory (MB) |
| g6_cache_evictions_total | C | — | Cache evictions cumulative |
| g6_batch_efficiency_percent | G | — | Actual vs target batch size (%) |
| g6_avg_batch_size | G | — | Rolling average batch size |
| g6_batch_processing_time_seconds | G | — | Rolling average batch processing time |
| g6_total_errors_total | C | — | All errors cumulative |
| g6_api_errors_total | C | — | API-related errors |
| g6_network_errors_total | C | — | Network-related errors |
| g6_data_errors_total | C | — | Data validation errors |
| g6_error_rate_per_hour | G | — | Computed error rate per hour |
| g6_metric_stall_events_total | C | metric | Stall detection events by metric |

## 8. Storage & Output Pipeline
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_csv_files_created_total | C | — | CSV files created |
| g6_csv_records_written_total | C | — | CSV records written |
| g6_csv_write_errors_total | C | — | CSV write errors |
| g6_csv_disk_usage_mb | G | — | Disk use attributed to CSV outputs (MB) |
| g6_csv_cardinality_unique_strikes | G | index, expiry | Unique strikes in last write cycle |
| g6_csv_cardinality_suppressed | G | index, expiry | 1 if suppression active |
| g6_csv_cardinality_events_total | C | index, expiry, event | Suppression events by type |
| g6_csv_overview_writes_total | C | index | Overview snapshot rows written |
| g6_csv_overview_aggregate_writes_total | C | index | Aggregated overview writes |
| g6_influxdb_points_written_total | C | — | InfluxDB points written |
| g6_influxdb_write_success_rate_percent | G | — | Influx write success % |
| g6_influxdb_connection_status | G | — | InfluxDB connection health (1/0) |
| g6_influxdb_query_time_ms | G | — | Representative query latency (ms) |
| g6_backup_files_created_total | C | — | Backup files created |
| g6_last_backup_unixtime | G | — | Unix time of last backup |
| g6_backup_size_mb | G | — | Size of last backup (MB) |

## 9. Memory Pressure & Adaptive Degradation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_pressure_level | G | — | Pressure level 0=normal..3=critical |
| g6_memory_pressure_actions_total | C | action, tier | Mitigation actions executed |
| g6_memory_pressure_seconds_in_level | G | — | Seconds spent in current level |
| g6_memory_pressure_downgrade_pending | G | — | 1 if downgrade hysteresis pending |
| g6_memory_depth_scale | G | — | Current strike depth scaling factor |
| g6_memory_per_option_metrics_enabled | G | — | 1 if per-option metrics enabled |
| g6_memory_greeks_enabled | G | — | 1 if Greeks/IV computation enabled |

## 10. Index-Specific Aggregates
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_index_options_processed | G | index | Options processed last cycle (index scope) |
| g6_index_options_processed_total | C | index | Cumulative options processed per index |
| g6_index_avg_processing_time_seconds | G | index | Avg per-option time (last cycle) |
| g6_index_success_rate_percent | G | index | Per-index success percentage |
| g6_index_last_collection_unixtime | G | index | Last successful collection timestamp |
| g6_index_current_atm_strike | G | index | Current ATM strike (stable label set) |
| g6_index_current_volatility | G | index | Representative volatility (ATM IV proxy) |
| g6_index_attempts_total | C | index | Total collection attempts (never resets) |
| g6_index_failures_total | C | index, error_type | Failures by error type per index |
| g6_index_cycle_attempts | G | index | Attempts in most recent cycle |
| g6_index_cycle_success_percent | G | index | Success % in most recent cycle |

## 11. ATM Batch Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_atm_batch_time_seconds | G | index | Wall time to collect ATM option batch |
| g6_atm_avg_option_time_seconds | G | index | Avg per-option time inside ATM batch |

## 12. Health Check (On-Demand)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_health_check_status | G | component, index | Health check status (1=ok/0=fail) |
| g6_health_check_duration_seconds | G | component, index | Health check execution duration |

## 13. Recording / Derived Rules (Prometheus Side)
These are created by `prometheus_rules.yml`, not directly in code.
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_pressure_is_level | R | job | Copy / selector of pressure level |
| g6_memory_pressure_transition | R | job | Positive delta when level increases |
| g6_memory_pressure_downgrade | R | job | Positive delta when level decreases |
| g6_memory_pressure_time_in_level | R | job | Alias for seconds in current level |
| g6_memory_pressure_actions_5m | R | action, tier | 5m sum of mitigation actions |
| g6_memory_pressure_upgrade_rate_per_min | R | — | Upgrades/min over 10m window |
| g6_memory_pressure_downgrade_rate_per_min | R | — | Downgrades/min over 10m window |
| g6_memory_depth_scale_current | R | job | Convenience copy for panels/alerts |
| g6_memory_greeks_enabled_flag | R | job | Flag copy for alert expression consistency |
| g6_memory_per_option_metrics_enabled_flag | R | job | Per-option metrics flag copy |

---
## Cardinality & Operational Notes
- High-cardinality sources: per-option gauges (strike, type) and per-expiry metrics. Consider sampling or disabling via memory pressure controls when `g6_memory_pressure_level >= 2`.
- Counters carry `_total` suffix per Prometheus best practices.
- Timestamp gauges (`*_unixtime`) enable derivations like elapsed time since last success via recording rules.
- For alerting on “staleness”, prefer PromQL like: `time() - g6_last_success_cycle_unixtime > 300`.

## Potential Additions (Not Yet Implemented)
| Candidate | Rationale |
|-----------|-----------|
| g6_seconds_since_last_success (recording) | Faster dashboard read of cycle freshness |
| g6_api_error_rate_per_min (recording) | Smoothed API error velocity |

## Change Log
- 2025-09: Added `g6_last_success_cycle_unixtime`; refactored docs; removed legacy dashboard parser metrics.

---
Generated on: 2025-09-15
