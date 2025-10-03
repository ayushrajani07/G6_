# G6 Platform Metrics Reference

Authoritative list of Prometheus metrics exported by the G6 options collection platform.

> Legend: Type abbreviations — C=Counter, G=Gauge, H=Histogram, S=Summary, R=Recording (derived in Prometheus rules).
>
> Naming conventions: All application metrics are prefixed with `g6_`. Counters end in `_total` when monotonic. Timestamps end in `_unixtime` and are seconds since epoch.
>
> Modularization Note (2025-10): The metrics system is mid-refactor (Phase 3.x). Public import surface is via `from src.metrics import ...`. Deep imports of `src.metrics.metrics` will remain functional for one release window after completion. This document is agnostic to module boundaries; metric names & semantics are stable unless explicitly marked experimental. Always register new metrics through the facade/group registry to ensure governance tests detect them.

---
## 1. Core Cycle & Uptime
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_collection_cycles_total | C | — | Total collection cycles executed |
| g6_collection_duration_seconds | S | — | Per-cycle wall clock duration samples |
| g6_collection_errors_total | C | index, error_type | Cycle errors attributed to an index and categorized |
| g6_collection_cycle_in_progress | G | — | 1 while a cycle is running, else 0 |
| g6_last_success_cycle_unixtime | G | — | Unix timestamp of last fully successful cycle |
| g6_data_gap_seconds | G | — | Seconds since last successful collection cycle (reset on success) |
| g6_cycle_sla_breach_total | C | — | Count of cycles whose elapsed time exceeded SLA fraction of interval |
| g6_summary_snapshot_build_seconds | H | — | Distribution of snapshot builder (v2) wall times in seconds (FLAG: G6_SUMMARY_AGG_V2) |
| g6_summary_v2_frames_total | C | — | Total v2 summary frame snapshots built (FLAG: G6_SUMMARY_AGG_V2) |
| g6_summary_alerts_dedup_total | C | — | Alerts duplicates skipped during snapshot build (FLAG: G6_SUMMARY_AGG_V2, PH1-04) |
| g6_summary_refresh_skipped_total | C | — | UI refresh operations skipped due to unchanged snapshot signature (FLAGS: G6_SUMMARY_AGG_V2 & G6_SUMMARY_SIG_V2, PH1-05) |

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
| g6_iv_iterations_histogram | H | index, expiry | Distribution of raw per-option solver iteration counts (use for tail behavior / convergence analysis) |

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
| g6_api_errors_total | C | — | API-related errors (legacy aggregate; kept for compatibility) |
| g6_network_errors_total | C | — | Network-related errors (legacy aggregate) |
| g6_data_errors_total | C | — | Data validation errors (legacy aggregate) |
| g6_api_errors_by_provider_total | C | provider, component, error_type | Labeled API errors (preferred) |
| g6_network_errors_by_provider_total | C | provider, component, error_type | Labeled network errors (preferred) |
| g6_data_errors_by_index_total | C | index, component, error_type | Labeled data/validation errors (preferred) |
| g6_error_rate_per_hour | G | — | Computed error rate per hour |
| g6_metric_stall_events_total | C | metric | Stall detection events by metric |

## 8. Storage & Output Pipeline
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_csv_files_created_total | C | — | CSV files created |
| g6_csv_records_written_total | C | — | CSV records written |
| g6_csv_write_errors_total | C | — | CSV write errors |
| g6_csv_disk_usage_mb | G | — | Disk use attributed to CSV outputs (MB) |
<!-- Cardinality suppression metrics removed (feature dropped) -->
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
- High-cardinality sources: per-option gauges (strike, type) and per-expiry metrics. Consider sampling or disabling via memory pressure controls when `g6_memory_pressure_level >= 2`. Cardinality suppression in CSV sink has been removed; all per-strike writes proceed.
- Counters carry `_total` suffix per Prometheus best practices.
- Timestamp gauges (`*_unixtime`) enable derivations like elapsed time since last success via recording rules.
- Labeled error counters are the primary source for drilldowns; the summary processor prefers legacy totals when present (>0) to avoid double counting, otherwise it sums the labeled series.
- For alerting on “staleness”, prefer PromQL like: `time() - g6_last_success_cycle_unixtime > 300`.

## Potential Additions (Not Yet Implemented)
| Candidate | Rationale |
|-----------|-----------|
| g6_seconds_since_last_success (recording) | Faster dashboard read of cycle freshness |
| g6_api_error_rate_per_min (recording) | Smoothed API error velocity |

## Expiry Misclassification & Remediation Metrics (New)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_expiry_misclassification_total | C | index, expiry_code, expected_date, actual_date | Raw anomaly events where a differing expiry_date observed after canonical established. |
| g6_expiry_canonical_date_info | G | index, expiry_code, expiry_date | Info gauge (value=1) marking canonical expiry_date for the (index, expiry_code) key. |
| g6_expiry_quarantined_total | C | index, expiry_code | Rows diverted to quarantine store by policy=quarantine. |
| g6_expiry_rewritten_total | C | index, from_code, to_code | Rows whose expiry_code was rewritten to canonical (policy=rewrite). |
| g6_expiry_rejected_total | C | index, expiry_code | Rows dropped outright (policy=reject). |
| g6_expiry_quarantine_pending | G | date | Count of quarantine rows pending review (in-process tally; resets on restart). |

Operational Flow (active enforcement):
1. Detection: First row defines canonical (labels canonical_date_info). Subsequent mismatch increments misclassification counter.
2. Policy Application: Based on G6_EXPIRY_MISCLASS_POLICY the row is rewritten, quarantined, or rejected; corresponding counter increments.
3. Quarantine Gauge: Updated in real-time upon each quarantine; per-date count (non-persistent) aids dashboards.
4. Rewrite Annotation (if enabled) adds audit columns for downstream CSV consumers; does not alter counter semantics.
5. Summary Event: `expiry_quarantine_summary` emitted at most every G6_EXPIRY_SUMMARY_INTERVAL_SEC (default 60) with cumulative daily counts (rewritten, quarantined, rejected).

Cardinality Considerations: expected_date/actual_date labels intentionally surface granular pairs for forensic review. If high churn introduces explosion risk, a fallback sampled counter (without dates) may be added later.


## Panel Diff & Analytics Metrics (New)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_panel_diff_writes_total | C | type | Diff/full artifact writes (type=diff|full). |
| g6_panel_diff_last_full_unixtime | G | — | Unix timestamp of last full panel snapshot when diffing enabled. |
| g6_panel_diff_bytes_last | G | type | Size (bytes) of last diff/full artifact written. |
| g6_panel_diff_bytes_total | C | type | Cumulative bytes written for panel diff or full artifacts (incremented by raw JSON length). Useful for estimating write savings vs periodic full snapshots. |
| g6_panel_diff_truncated_total | C | reason | Count of diff artifacts truncated due to safety caps (reason currently 'max_keys'). Sudden increases suggest lowering snapshot interval, raising key cap, or investigating pathological churn. |
| g6_panel_diff_emit_seconds | H | — | Latency to compute & persist a diff/full artifact (includes JSON serialization + file write). |
| g6_vol_surface_builds_total | C | index | Vol surface build executions (index currently 'global'). |
| g6_vol_surface_last_build_unixtime | G | index | Timestamp of last volatility surface build. |
| g6_vol_surface_build_seconds | H | — | Build latency distribution for volatility surface aggregation. |
| g6_risk_agg_builds_total | C | — | Risk aggregation snapshot build executions. |
| g6_risk_agg_last_build_unixtime | G | — | Timestamp of last risk aggregation build. |
| g6_risk_agg_build_seconds | H | — | Build latency distribution for risk aggregation. |
| g6_vol_surface_rows | G | index,source | Row counts contributing to latest volatility surface build (source=raw|interp). Currently index="global" until multi-index surfaces implemented. |
| g6_vol_surface_interpolated_fraction | G | index | Fraction of interpolated rows = interp_rows / (raw_rows + interp_rows). Monitors reliance on interpolation vs direct market quotes. |
| g6_risk_agg_rows | G | — | Count of risk aggregation rows (moneyness buckets) produced in latest build. Useful to detect bucket sparsity or configuration regressions. |
| g6_risk_agg_notional_delta | G | — | Aggregate delta notional (signed) across all buckets from latest risk aggregation snapshot. |
| g6_risk_agg_notional_vega | G | — | Aggregate vega notional (signed) across all buckets from latest risk aggregation snapshot. |

Depth & Buckets:
- Panel diff recursion depth configured via G6_PANEL_DIFF_NEST_DEPTH (default 1). Depth>1 increases CPU but keeps artifacts compact relative to full snapshots.
- Moneyness bucket edges configurable via G6_VOL_SURFACE_BUCKETS / G6_RISK_AGG_BUCKETS. Outer buckets auto-extend to +/- infinity.

Operational Guidance:
1. Monitor p95 g6_panel_diff_emit_seconds; sustained regression suggests pathological nested object churn or need for selective section hashing.
2. Use build latency histograms to budget future interpolation (e.g., SABR) overhead—set alert on p99 > 0.5s.
3. Bytes gauge allows estimating write reduction: compare sum(rate(g6_panel_diff_bytes_last{type="diff"}[5m])) vs full snapshot bytes.
 4. Track g6_vol_surface_interpolated_fraction trend; rising fraction may indicate thinning direct quotes (liquidity degradation) or overly aggressive interpolation parameters.
 5. Alert when g6_risk_agg_rows drops unexpectedly (e.g., < expected bucket count) signalling configuration drift or upstream filtering overreach.
 6. Large absolute swings in g6_risk_agg_notional_delta / vega without corresponding option volume changes may flag aggregation or scaling anomalies.


## Change Log
 
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_events_published_total | C | type | Events published (labeled by event `type`, e.g. `panel_full`, `panel_diff`, `heartbeat`). |
| g6_events_backlog_current | G | — | Current in-memory event backlog size. Sustained elevation approaching configured max suggests slow consumers or bursty publishing. |
| g6_events_backlog_highwater | G | — | High-water mark of backlog since process start (resets on restart). Use to tune max backlog capacity. |
| g6_events_consumers | G | — | Active SSE consumer connections. Abrupt drops without shutdown may indicate network partition or client crash. |
| g6_events_generation | G | — | Current panel generation (increments only on `panel_full`). Aids detection of missing baseline refresh when diffs continue. |
| g6_events_dropped_total | C | reason,type | Client-side diff (or event) drops due to integrity validation. `reason` currently `no_baseline` (diff received before any `panel_full`) or `generation_mismatch` (diff generation != client baseline). `type` mirrors event type (typically `panel_diff`). Persistent non-startup drops indicate ordering/race issues. |
| g6_events_full_recovery_total | C | — | Count of client-triggered forced baseline recovery attempts (single automatic reconnect with `force_full=1`). Spikes imply systemic diff rejection requiring remediation. |
| g6_events_need_full_active | G | — | 1 when the summary client is currently in a degraded (need_full) state, else 0. Useful for alerting on sustained integrity loss windows. |
| g6_events_need_full_episodes_total | C | — | Count of distinct need_full episodes (increments on false→true transitions). Helps differentiate chronic flapping from a single prolonged incident. |
 
Integrity & Recovery Flow:
1. Initial subscribe (optionally) with `force_full=1` injects the latest `panel_full` snapshot ahead of backlog replay.
2. Client maintains a baseline generation from the last full; diffs tied to mismatched or absent baseline are rejected and counted in `g6_events_dropped_total`.
3. When degradation detected and `G6_SUMMARY_AUTO_FULL_RECOVERY=on`, the client performs one automatic reconnection with `force_full=1`; success increments `g6_events_full_recovery_total`.
4. UI NEED_FULL badge (gated by `G6_SUMMARY_SHOW_NEED_FULL`) remains visible until a valid full baseline applied.
 
Operational Guidance (Events):
- Alert if `rate(g6_events_dropped_total{reason="generation_mismatch"}[5m]) > 0` for >10m (excluding startup grace) — indicates missing or stale full snapshots.
- Alert if `g6_events_need_full_active == 1` for >5m to surface operator-visible degradation not auto-resolved.
- Watch `g6_events_generation` stagnation (no increment) while `rate(g6_events_published_total{type="panel_diff"}[5m])` remains >0.
- Ensure `g6_events_backlog_current` rarely exceeds 80% of configured max; tune retention or reduce diff frequency otherwise.
- Investigate bursts in `increase(g6_events_full_recovery_total[30m])` — recovery mechanism may be masking root ordering issues.
- Correlate `g6_events_consumers` drops with log/network telemetry to differentiate organic disconnects vs infrastructure faults.
 
Example PromQL Snippets:
```
# Sustained generation mismatch (exclude startup period)
increase(g6_events_dropped_total{reason="generation_mismatch"}[10m]) > 5

# Backlog pressure (replace 1000 with configured max backlog size)
max_over_time(g6_events_backlog_current[5m]) / 1000 > 0.8

# Missing full snapshot in last 15m despite diff flow
(time() - max_over_time(g6_events_generation[15m])) > 900
	and rate(g6_events_published_total{type="panel_diff"}[15m]) > 0

# Recovery spike (possible systemic issue)
increase(g6_events_full_recovery_total[30m]) > 3

# Active degradation window (need_full persisting >5m)
max_over_time(g6_events_need_full_active[5m]) == 1

# High episode churn (flapping)
increase(g6_events_need_full_episodes_total[30m]) > 5
```

Environment Flags:
- `G6_SUMMARY_SHOW_NEED_FULL` — enable NEED_FULL header badge to surface degraded state.
- `G6_SUMMARY_AUTO_FULL_RECOVERY` — enable one-shot automatic forced baseline recovery.

Planned Extensions:
- `g6_events_need_full_episodes_total` (distinct degraded episodes) to complement raw drop counts.
- Diff end-to-end latency histogram (publish→apply) via client ack instrumentation.
- Dedicated gauge `g6_events_last_full_unixtime` for simpler freshness tests (alternative to generation delta).

New Metrics (2025-09):
| Name | Type | Labels | Description |
|------|------|--------|-------------|
| g6_events_last_full_unixtime | G | – | Unix timestamp of last `panel_full` event published to SSE stream |
| g6_panel_event_latency_seconds | H | type | End-to-end latency (seconds) from server publish to client apply (panel_full / panel_diff) |
| g6_events_emitted_total | C | type | Events admitted into backlog post-coalescing (panel_diff/panel_full/etc). May be lower than published_total due to replacements. |
| g6_events_coalesced_total | C | type | Count of events that replaced a prior event with the same coalesce_key (lost backlog entries). Rising fast vs emitted indicates heavy churn amenable to diff throttling. |
| g6_events_backlog_capacity | G | – | Configured max backlog size (static). Use with backlog_current for utilization percentage. |
| g6_events_last_id | G | – | Last assigned event id (monotonic). Allows external lag calculations when paired with consumer’s last applied id. |
| g6_events_forced_full_total | C | reason | Forced baseline emissions by snapshot guard (reasons: missing_baseline, gap_exceeded, generation_mismatch). Persistent growth highlights upstream ordering gaps or suppressed full cadence. |
| g6_events_sse_connection_duration_seconds | H | – | Distribution of SSE connection lifetimes (seconds). Short spikes + high churn suggest client instability or load balancer idling. |

Snapshot Guard Environment:
- `G6_EVENTS_SNAPSHOT_GAP_MAX` (default 500): Max allowed id gap between last `panel_full` and latest event before guard forces a new baseline.
- `G6_EVENTS_FORCE_FULL_RETRY_SECONDS` (default 30): Cooldown per reason to avoid spamming forced fulls.

Operational Patterns:
1. Alert if `increase(g6_events_forced_full_total[30m]) > 0` together with `rate(g6_events_published_total{type="panel_full"}[30m]) == 0` — forced recoveries substituting for organic full cadence.
2. High `rate(g6_events_coalesced_total[5m]) / rate(g6_events_emitted_total[5m]) > 0.7` implies aggressive overwrite churn; consider spreading updates or batching.
3. Connection churn: `sum(rate(g6_events_sse_connection_duration_seconds_count[5m]))` vs stable consumer count; large delta points to flapping clients.
4. Backlog utilization rule example:
```
g6:events_backlog_utilization = g6_events_backlog_current / ignoring() g6_events_backlog_capacity
```
Set alert when `max_over_time(g6:events_backlog_utilization[10m]) > 0.8`.

`/events/stats` Endpoint (JSON) now includes:
```
{
	"latest_id": <int>,
	"oldest_id": <int>,
	"backlog": <int>,
	"highwater": <int>,
	"types": {"panel_full": <count>, ...},
	"coalesced": {"panel_full": <count>, ...},
	"consumers": <int>,
	"max_events": <int>,
	"generation": <int>,
	"forced_full_last": {"gap_exceeded": <unix_ts>, ...}
}
```
Use this for lightweight health dashboards without scraping Prometheus (e.g., local dev). `forced_full_last` timestamps help correlate guard activity with upstream lag.

Latency Guidance:
- p95 >250ms sustained suggests network or client-side processing overhead.
- Spikes isolated to full snapshots are typically acceptable (larger payloads); diff latency should remain low and stable.
- Recording rule example (add to prometheus_rules.yml if needed):
```
g6:panel_event_latency_p95_5m = histogram_quantile(0.95, sum(rate(g6_panel_event_latency_seconds_bucket[5m])) by (le))
```

- 2025-09: Added `g6_last_success_cycle_unixtime`; refactored docs; removed legacy dashboard parser metrics.

### Aggregated Health Score (Recording Rule)

The composite metric `g6:aggregated_health_score` (range 0–1) summarizes multi-dimensional platform health into a single weighted score suitable for wallboard display and coarse alerting.

Component Weights:
| Component | Metric / Expression | Weight | Rationale |
|-----------|---------------------|--------|-----------|
| Errors inverse | `1 - clamp_max(sum(rate(g6_total_errors_total[5m])) / 5, 1)` | 0.25 | Penalize sustained elevated error rate (cap after 5 errors/s) |
| API success | `clamp_max(g6_api_success_rate_percent/100,1)` | 0.25 | External dependency / upstream stability |
| Collection success | `clamp_max(g6_collection_success_rate_percent/100,1)` | 0.20 | Internal ingestion quality |
| Backlog headroom | `1 - clamp_max(g6_events_backlog_current / clamp_min(g6_events_backlog_highwater,1),1)` | 0.15 | Protects against latent diff rejection & latency risk |
| Need-full absence | `1 - clamp_max(g6_events_need_full_active,1)` | 0.15 | Ensures clients not in degraded (baseline-missing) state |

Final Expression:
```
(
	(1 - clamp_max(sum(rate(g6_total_errors_total[5m])) / 5, 1)) * 0.25 +
	(clamp_max(g6_api_success_rate_percent / 100, 1)) * 0.25 +
	(clamp_max(g6_collection_success_rate_percent / 100, 1)) * 0.20 +
	(1 - clamp_max(g6_events_backlog_current / clamp_min(g6_events_backlog_highwater,1), 1)) * 0.15 +
	(1 - clamp_max(g6_events_need_full_active, 1)) * 0.15
)
```

Alerting (see `prometheus_rules.yml`):
- Warning: `< 0.85` for 10m (`G6HealthScoreDegraded`)
- Critical: `< 0.70` for 5m (`G6HealthScoreCritical`)

Guidance:
- Use for high-level NOC display; always drill into component dashboards for root cause.
- Short-lived dips (e.g. forced baseline recovery) may not trigger alerts due to hold durations.
- Adjust weights only with accompanying documentation update; maintain sum to 1.0.

### Prometheus Rule Suggestions (Panel Diff & Analytics New Metrics)
These are not yet in `prometheus_rules.yml` but recommended for operational visibility:

Recording Rules:
```
# Rolling 5m diff vs full bytes ratio (requires occasional full snapshots)
g6_panel_diff_bytes_5m = sum(rate(g6_panel_diff_bytes_total{type="diff"}[5m]))
g6_panel_full_bytes_5m = sum(rate(g6_panel_diff_bytes_total{type="full"}[5m]))
g6_panel_diff_write_savings_ratio = 1 - (g6_panel_diff_bytes_5m / clamp_min(g6_panel_full_bytes_5m,1))

# Truncation rate
g6_panel_diff_truncation_rate_5m = sum(rate(g6_panel_diff_truncated_total[5m]))
```

Alert Examples:
```
# High truncation events (may indicate too low key cap or runaway churn)
ALERT PanelDiffTruncationSpike
	IF sum(rate(g6_panel_diff_truncated_total[5m])) > 5
	FOR 10m
	LABELS { severity="warning" }
	ANNOTATIONS { summary="Panel diff truncations elevated", description="Investigate structural churn or raise G6_PANEL_DIFF_MAX_KEYS" }

# Low write savings (benefit eroded) – observe for sustained degradation
ALERT PanelDiffLowSavings
	IF g6_panel_diff_write_savings_ratio < 0.25
	FOR 30m
	LABELS { severity="info" }
	ANNOTATIONS { summary="Panel diff write savings low", description="Diffs providing <25% savings vs full snapshots; consider adjusting interval/depth" }
```

Operational Guidance:
- Truncation spikes: inspect recent diff artifacts for large nested structures or increase `G6_PANEL_DIFF_MAX_KEYS` cautiously.
- Persistently low savings ratio: either panel object churn is high (diff nearly as large as full) or full interval too frequent.
- Absence of full bytes over long windows may make savings ratio misleading; ensure non-zero full interval.

---
Generated on: 2025-09-21

---
## Adaptive Analytics Alerts Panel (New)

The `adaptive_alerts` panel (JSON written by `status_to_panels` via `panels.factory`) surfaces a compact, aggregated view of adaptive analytics alert activity so operators can quickly assess emerging risk / degradation signals without parsing raw status history.

Panel File: `data/panels/adaptive_alerts.json`

Structure:
```
{
  "total": <int>,                # Total alert objects considered (capped to last 50 in status)
  "by_type": {                   # Counts by alert type key
	  "interpolation_high": <int>,
	  "risk_delta_drift": <int>,
	  "bucket_util_low": <int>,
	  ... (future types)
  },
  "recent": [                    # Tail (up to 10) of most recent alerts (type + truncated message)
	  {"type": "interpolation_high", "message": "interpolated fraction 0.68 > 0.60 for 5..."},
	  {"type": "risk_delta_drift", "message": "risk delta drift +32.1% over 5 builds..."}
  ],
  "last": {                      # Most recent alert (same shape as a recent element)
	  "type": "bucket_util_low", "message": "bucket utilization 0.62 < 0.70 for 5..."
  }
}
```

Source Fields: Derived from `runtime_status.json` key `adaptive_alerts` (list of alert dicts with at least `type` and `message`). The factory applies:
- Safety cap: Only the final 50 status entries are scanned to bound processing.
- Sanitization: Messages >300 chars truncated with ellipsis for panel payload.
- Recent Tail: Final 10 (after truncation) preserved in chronological order.

Current Alert Types & Triggers:
- `interpolation_high`: Interpolated fraction exceeded `G6_INTERP_FRACTION_ALERT_THRESHOLD` for `G6_INTERP_FRACTION_ALERT_STREAK` consecutive volatility surface builds.
- `risk_delta_drift`: Absolute percent change in aggregated risk delta notional over rolling window `G6_RISK_DELTA_DRIFT_WINDOW` >= `G6_RISK_DELTA_DRIFT_PCT` with stable row counts (± `G6_RISK_DELTA_STABLE_ROW_TOLERANCE`).
- `bucket_util_low`: Risk bucket utilization (< populated buckets / total) below `G6_RISK_BUCKET_UTIL_MIN` for `G6_RISK_BUCKET_UTIL_STREAK` consecutive snapshots.

Operational Usage:
1. Dashboard Badge: Display `total` and highlight non-zero critical types (e.g., red if `risk_delta_drift` >0 in last N minutes).
2. Triage Flow: Drill into `recent` messages to correlate with spikes in interpolation fraction (`g6_vol_surface_interpolated_fraction`), risk delta gauges, or bucket utilization metric (`g6_risk_agg_bucket_utilization`).
3. Alert Routing: Optional Prometheus rules can watch underlying counters (e.g., `g6_adaptive_interpolation_alerts_total`) while the panel provides human-readable context.

PromQL Companion Examples:
```
# Last 10m new interpolation alerts
increase(g6_adaptive_interpolation_alerts_total[10m]) > 0

# Sustained risk delta drift activity (direction-agnostic)
sum(increase(g6_adaptive_risk_delta_drift_alerts_total[15m])) > 2

# Bucket utilization low streak currently active
g6_adaptive_bucket_util_streak >= G6_RISK_BUCKET_UTIL_STREAK
```

Failure / Absence Handling:
- If no alerts present, the panel may be omitted; consumers should treat missing file or empty JSON as "no active adaptive alerts".
- Backward compatibility: Adding new alert types only increases `by_type` keys; existing dashboards should iterate dynamically.

Severity (Phase 1 & 2):
- When `G6_ADAPTIVE_ALERT_SEVERITY` is enabled (default on) alerts are enriched with `severity` (info|warn|critical) using rules documented in `docs/design/adaptive_alerts_severity.md` (panel-only; no new Prometheus metric families added).
- Panel adds `severity_counts`, `by_type_severity` (per-type counts + last / active severity), and when decay/resolution (Phase 2) is active may also include:
	- `resolved_total`: count of decay-driven transitions from warn/critical back to info in the recent capped window.
	- `severity_meta`: object containing `rules` (effective warn/critical thresholds per type), `decay_cycles`, and `min_streak` for operator transparency.
- Summary view badge variants:
	- Active: `Adaptive alerts: <total> [C:x W:y]` (optionally with `R:n` if resolutions occurred)
	- Stable (no active warn/critical): `Adaptive alerts: <total> R:n (stable)`
- Environment overrides: thresholds & min streak via `G6_ADAPTIVE_ALERT_SEVERITY_RULES` (JSON) and `G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK`.
- Decay Lifecycle (Phase 2): if `G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES>0`, each alert type passively downgrades one level after N idle cycles (multi-step if large idle gap); a downgrade reaching info from an elevated state emits a one-time `resolved` flag and increments `resolved_total`.

Future Extensions (Roadmap):
- Add `first_seen` timestamp per type (oldest alert in current capped window) for dwell time tracking.
- Color mapping externalization & optional severity→controller feedback loop.
- Panel diff integration for low-churn incremental updates (omit unchanged `recent`).

---

## 14. Parallel Collection (Per-Index Execution)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_parallel_index_workers | G | — | Current number of worker threads allocated for parallel index collection (set once per cycle). |
| g6_parallel_index_failures_total | C | index | Failed parallel index collection attempts (exceptions other than explicit timeout). |
| g6_parallel_index_elapsed_seconds | H | — | Distribution of successful per-index collection wall times under parallel mode. |
| g6_parallel_index_timeouts_total | C | index | Per-index soft timeouts (task exceeded configured G6_PARALLEL_INDEX_TIMEOUT_SEC). |
| g6_parallel_index_retry_total | C | index | Number of retry attempts executed (serial) after an initial parallel failure/timeout. |
| g6_parallel_cycle_budget_skips_total | C | — | Count of indices skipped because the overall cycle budget fraction (G6_PARALLEL_CYCLE_BUDGET_FRACTION) was exhausted before submission or completion. |

Operational Notes:
- Per-index timeout is “soft”: a hung task may still block if underlying work does not return; future refinement may introduce cancellation.
- Retries occur serially after the parallel phase, bounded by remaining budget and `G6_PARALLEL_INDEX_RETRY`.
- Budget skips help differentiate true failures from omitted work due to time budgeting.

---
## (Merged Appendix) Detailed Metrics Dictionary Legacy Sections
The former `metrics_dict.md` has been merged here for a single source of truth. Content below preserves its structured tables (sections 1–17) for comprehensive reference. Duplicated metrics already described above are intentionally repeated for completeness.

### A1. Core Cycle & Phase Metrics
| Metric | Type | Labels | Description | Source |
|--------|------|--------|-------------|--------|
| g6_collection_duration_seconds | S | – | Time spent collecting data (per cycle summary). | metrics.MetricsRegistry | 
| g6_phase_duration_seconds | S | phase | Duration of specific cycle phases. | metrics.MetricsRegistry |
| g6_phase_failures_total | C | phase | Failures within a named phase. | metrics.MetricsRegistry |
| g6_collection_cycles_total | C | – | Total collection cycles executed. | metrics.MetricsRegistry |
| g6_collection_errors_total | C | index,error_type | Collection errors aggregated by index & error classification. | metrics.MetricsRegistry |
| g6_collection_cycle_in_progress | G | – | 1 while a collection cycle is active, else 0. | metrics.markers |
| g6_last_success_cycle_unixtime | G | – | Unix timestamp of last fully successful cycle. | metrics.markers |

### A2. Index & Market Snapshot
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

### A3. Option-Level Metrics
| Metric | Type | Labels | Description | Cardinality |
|--------|------|--------|-------------|-------------|
| g6_option_price | G | index,expiry,strike,type | Option price (last/representative). | High |
| g6_option_volume | G | index,expiry,strike,type | Traded volume. | High |
| g6_option_oi | G | index,expiry,strike,type | Open interest. | High |
| g6_option_iv | G | index,expiry,strike,type | Implied volatility estimate. | High |
| g6_option_delta | G | index,expiry,strike,type | Greek delta. | High |
| g6_option_theta | G | index,expiry,strike,type | Greek theta. | High |
| g6_option_gamma | G | index,expiry,strike,type | Greek gamma. | High |
| g6_option_vega | G | index,expiry,strike,type | Greek vega. | High |
| g6_option_rho | G | index,expiry,strike,type | Greek rho. | High |

### A4. Field Coverage / Data Quality (Per Expiry)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_missing_option_fields_total | C | index,expiry,field | Count of missing option fields (volume/oi/avg_price). |
| g6_option_field_coverage_ratio_percent | G | index,expiry | Percent coverage of core option fields. |
| g6_synthetic_quotes_used_total | C | index,expiry | Synthetic quote insertions (fallback). |
| g6_zero_option_rows_total | C | index,expiry | Rows where CE+PE metrics are both zero. |
| g6_instrument_coverage_percent | G | index,expiry | Percent of requested strikes that produced at least one instrument. |
| g6_index_data_quality_score_percent | G | index | Aggregated per-index DQ score (0-100). |
| g6_index_dq_issues_total | C | index | Total data quality issues observed (cumulative). |

### A5. IV / Greeks Estimation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_iv_estimation_success_total | C | index,expiry | Successful IV computations. |
| g6_iv_estimation_failure_total | C | index,expiry | Failed IV computations. |
| g6_iv_estimation_avg_iterations | G | index,expiry | Rolling average iterations of IV solver. |
| g6_greeks_success_total | C | index,expiry | Successful per-option Greek computations. |
| g6_greeks_fail_total | C | index,expiry | Failed per-option Greek computations. |
| g6_greeks_batch_fail_total | C | index,expiry | Batch-level Greek computation failures. |

### A6. Performance / Throughput
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

### A7. Resource & System Utilization
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_usage_mb | G | – | Resident memory footprint. |
| g6_cpu_usage_percent | G | – | Process CPU utilization %. |
| g6_disk_io_operations_total | C | – | Disk I/O operations (read+write increments). |
| g6_network_bytes_transferred_total | C | – | Network bytes (sent+recv increments). |

### A8. Cache / Error / Batch Metrics
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

### A9. Storage & Panels
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
| g6_build_info | G | version,git_commit,config_hash | Build metadata gauge (always 1). |

### A10. Overlay Quality
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_overlay_quality_last_run_issues | G | index | Issues detected in last overlay run (per index). |
| g6_overlay_quality_last_report_unixtime | G | – | Timestamp of last overlay quality report write. |
| g6_overlay_quality_last_run_total_issues | G | – | Total overlay quality issues last run. |
| g6_overlay_quality_last_run_critical | G | index | Critical overlay issues last run. |

### A11. Sampling / Cardinality Control
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_metric_sampling_events_total | C | category,decision,reason | Records sampling/gating decisions for per-option emission. |
| g6_metric_sampling_rate_limit_per_sec | G | category | Configured per-second rate limit for sampling category. |

### A12. Memory Pressure / Adaptive Degradation
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_memory_pressure_level | G | – | Memory pressure tier (0-3). |
| g6_memory_pressure_actions_total | C | action,tier | Mitigation actions taken under memory pressure. |
| g6_memory_pressure_seconds_in_level | G | – | Seconds in current memory pressure level. |
| g6_memory_pressure_downgrade_pending | G | – | 1 if downgrade pending. |
| g6_memory_depth_scale | G | – | Current strike depth scaling factor (0-1). |
| g6_memory_per_option_metrics_enabled | G | – | 1 if per-option metrics currently enabled. |
| g6_memory_greeks_enabled | G | – | 1 if Greek/IV computation enabled. |
| g6_tracemalloc_total_kb | G | – | Total allocated size from tracemalloc (KiB). |
| g6_tracemalloc_topn_kb | G | – | Aggregated top-N allocation group size (KiB). |

### A13. ATM Batch Metrics
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_atm_batch_time_seconds | G | index | Elapsed wall time of ATM batch collection. |
| g6_atm_avg_option_time_seconds | G | index | Avg per-option processing time within ATM batch. |

### A14. Circuit Breaker Metrics (Exporter)
| Metric | Type | Labels | Description | Notes |
|--------|------|--------|-------------|-------|
| g6_circuit_state_simple | G | name | Circuit state (0=closed,1=half,2=open). | Legacy label |
| g6_circuit_current_timeout_seconds | G | name | Current reset timeout. | Legacy label |
| g6_circuit_state | G | component | Circuit state (standardized). | Preferred |
| g6_circuit_timeout_seconds | G | component | Current reset timeout (standardized). | Preferred |

### A15. Planned / Roadmap Metrics (Not Yet Implemented)
| Metric (Planned) | Type | Labels | Purpose |
|------------------|------|--------|---------|
| g6_strike_depth_scale_factor | G | index | Adaptive strike depth scaling factor. |
| g6_cardinality_guard_trips_total | C | reason | Times guard auto-disabled per-option metrics. |
| g6_component_health | G | component | Health state (0/1/2). |
| g6_provider_failover_total | C | from,to | Provider failover transitions. |
| g6_config_deprecated_keys_total | C | key | Deprecated config key occurrences. |

Additional planned metrics (new scaffolding stubs):
| g6_panel_diff_writes_total | C | type(diff|full) | Count of panel diff vs full snapshot artifacts written while diffing enabled. |
| g6_panel_diff_last_full_unixtime | G | – | Timestamp of last full snapshot emission under diff regime. |
| g6_panel_diff_bytes_last | G | type(diff|full) | Size in bytes of last diff or full panel artifact written. |
| g6_vol_surface_builds_total | C | index | Volatility surface build executions (stub placeholder). |
| g6_vol_surface_last_build_unixtime | G | index | Last completed volatility surface build timestamp (stub). |
| g6_risk_agg_builds_total | C | – | Risk aggregation snapshot builds (stub placeholder). |
| g6_risk_agg_last_build_unixtime | G | – | Last risk aggregation snapshot build timestamp (stub). |

#### Analytics Depth (Vol Surface & Risk Aggregation) – Implemented
These metrics expose coverage (row counts), interpolation reliance, and structural health (bucket utilization) for advanced analytics components.

| Metric | Type | Labels | Description | Notes |
|--------|------|--------|-------------|-------|
| g6_vol_surface_rows | Gauge | index,source | Row counts contributing to volatility surface build (`source` in {raw,interp}). | Raw = observed quotes; interp = synthetic fills. |
| g6_vol_surface_interpolated_fraction | Gauge | index | Interpolated fraction = interp_rows / (raw_rows + interp_rows). | >0.6 sustained: investigate liquidity/feed. |
| g6_vol_surface_rows_expiry | Gauge | index,expiry,source | Per-expiry row counts by source. | Gated via `G6_VOL_SURFACE_PER_EXPIRY=1`. |
| g6_vol_surface_interpolated_fraction_expiry | Gauge | index,expiry | Per-expiry interpolated fraction. | Same gating flag. |
| g6_risk_agg_rows | Gauge | – | Option rows aggregated in latest risk snapshot. | Drop may precede noisy notionals. |
| g6_risk_agg_notional_delta | Gauge | – | Aggregate delta notional (signed). | Contract multiplier assumed upstream. |
| g6_risk_agg_notional_vega | Gauge | – | Aggregate vega notional. | 0 if greeks disabled. |
| g6_risk_agg_bucket_utilization | Gauge | – | Fraction (0-1) of configured risk buckets populated. | <0.7 sustained: bucket config vs liquidity review. |

Environment Flag:
* `G6_VOL_SURFACE_PER_EXPIRY` (default off) – enables per-expiry surface metrics adding up to 3 series per (index,expiry).

Operational Guidance:
1. Alert on `g6_vol_surface_interpolated_fraction` > 0.6 for 5 consecutive builds.
2. Compare per-expiry fractions; isolate anomalies where a single expiry diverges.
3. Track `g6_risk_agg_bucket_utilization` with `g6_risk_agg_rows`; falling utilization without row loss implies overly granular bucket edges.
4. Large `g6_risk_agg_notional_delta` moves with stable rows likely genuine; with preceding row collapse may be artifact.
5. PromQL examples:
	- Global raw vs interp: `sum by (source) (g6_vol_surface_rows)`
	- Per-expiry raw rows: `sum by (expiry) (g6_vol_surface_rows_expiry{source="raw"})`
	- Bucket utilization alert: `avg_over_time(g6_risk_agg_bucket_utilization[10m]) < 0.7`

Implemented formerly planned metrics (now active):
- g6_cycle_time_seconds
- g6_cycle_sla_breach_total
- g6_data_gap_seconds
- g6_missing_cycles_total
- g6_csv_junk_rows_skipped_total (aggregate junk suppression)
- g6_csv_junk_rows_threshold_skipped_total (subset: threshold-based)
- g6_csv_junk_rows_stale_skipped_total (subset: stale repetition)

### Expiry Misclassification Instrumentation (New)
The following metrics support detection of semantic junk where multiple differing expiry_date values appear under the same derived expiry_code (e.g., this_week) indicating an upstream classification fault.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_expiry_canonical_date_info | G | index, expiry_code, expiry_date | Canonical mapping (=1) established on first observation per (index,expiry_code). One sample per key. |
| g6_expiry_misclassification_total | C | index, expiry_code, expected_date, actual_date | Count of rows whose expiry_date deviated from canonical established earlier in process lifetime. |

Operational Notes:
1. Detection occurs in CsvSink just prior to row write.
2. If `G6_EXPIRY_MISCLASS_SKIP=1` mismatching rows are not persisted (containment). Otherwise they are written for forensic review.
3. `G6_EXPIRY_MISCLASS_DEBUG=1` adds warning log lines prefixed with `EXPIRY_MISCLASS`.
4. Gauge allows PromQL joins to identify which canonical date is authoritative; counter quantifies scope & direction of divergence.
5. High cardinality risk is low: expiry_code naming already partitions time horizons; only misclassified anomalies add additional label pairs.

Related env vars: `G6_EXPIRY_MISCLASS_DETECT`, `G6_EXPIRY_MISCLASS_DEBUG`, `G6_EXPIRY_MISCLASS_SKIP` (see env_dict.md section 5).

Per-Leg Junk Threshold Enhancement:
Two new env toggles (`G6_CSV_JUNK_MIN_LEG_OI`, `G6_CSV_JUNK_MIN_LEG_VOL`) refine junk filtering to catch asymmetric low-quality rows even when combined totals pass. No new metrics; skipped rows still increment existing junk counters.

g6_csv_junk_rows_skipped_total details: Counts all CSV option rows dropped by junk filtering (env vars: `G6_CSV_JUNK_MIN_TOTAL_OI`, `G6_CSV_JUNK_MIN_TOTAL_VOL`, `G6_CSV_JUNK_ENABLE`, `G6_CSV_JUNK_STALE_THRESHOLD`).

g6_csv_junk_rows_threshold_skipped_total details: Rows skipped because total OI / volume below configured thresholds (excludes stale category). Always increments the aggregate counter as well.

g6_csv_junk_rows_stale_skipped_total details: Rows skipped because consecutive identical price signature count exceeded `G6_CSV_JUNK_STALE_THRESHOLD` for that (index, expiry_code, strike_offset). Each stale skip also increments the aggregate counter.

Aggregation relationship: For any (index,expiry) pair at time T:

	g6_csv_junk_rows_skipped_total = g6_csv_junk_rows_threshold_skipped_total + g6_csv_junk_rows_stale_skipped_total

This invariant holds because only one category can classify a row (stale classification only evaluated when threshold check passes). Tests validate this by asserting aggregate == category count when only one category present.

g6_missing_cycles_total details: Increments when the elapsed wall time between the start of successive cycles exceeds `factor * interval`, where `interval` is from `G6_CYCLE_INTERVAL` (default 60s) and `factor` is configurable via `G6_MISSING_CYCLE_FACTOR` (default 2.0, clamped to a minimum of 1.1). This stricter default (previous experimental value was 1.5x) reduces false positives under jitter or brief GC pauses while still capturing true skipped cycles (e.g., scheduler stalls, long blocking operations). Set `G6_MISSING_CYCLE_FACTOR` higher (e.g., 3.0) to be more conservative or slightly lower (not recommended below 1.5) for more aggressive detection in stable environments.

g6_cycle_sla_breach_total details: Counts cycles whose wall-clock elapsed time exceeds the SLA budget:

	SLA Budget = G6_CYCLE_INTERVAL * G6_CYCLE_SLA_FRACTION

Defaults: `G6_CYCLE_INTERVAL=60`, `G6_CYCLE_SLA_FRACTION=0.85` → budget 51 seconds.
Use cases:
- Track performance degradation over time (increasing breach rate may indicate provider slowdown or internal contention).
- Drive adaptive scaling (reduce strike depth after N consecutive breaches) — wiring already present for strike scaling heuristics.
Tuning:
- Lower fraction (e.g., 0.75) for stricter latency targets in low-jitter environments.
- Raise fraction (e.g., 0.9) when upstream providers exhibit occasional spikes but overall cycle deadlines remain acceptable.
Operational Guidance: Investigate when breach rate >5% sustained; examine `g6_parallel_index_elapsed_seconds` histogram and provider latency metrics to isolate root cause.

### A16. High Cardinality Advisory
Per-option metrics (price, volume, OI, IV, Greeks) can create large time-series sets: (indices * expiries * strikes * 2 option types). Use cardinality management environment variables:
- `G6_METRICS_CARD_ENABLED=1`
- `G6_METRICS_CARD_ATM_WINDOW` limit window around ATM
- `G6_METRICS_CARD_RATE_LIMIT_PER_SEC` aggregate emission cap
- `G6_METRICS_CARD_CHANGE_THRESHOLD` suppress small deltas
Sampling decisions are auditable via `g6_metric_sampling_events_total`.

### A17. Naming Conventions (Duplicate Summary)
Prefix `g6_` is reserved. Suffix `_total` used for counters. Percent metrics include `_percent` (0-100). Latencies `_ms` vs `_seconds` encode units. Histograms specify unit explicitly.

### Adaptive Controller (New)
The adaptive controller orchestrates dynamic detail mode transitions (full=0, band=1, agg=2) based on multi-signal pressure (SLA breach streak, cardinality guard activation, memory tier).

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_adaptive_controller_actions_total | Counter | reason,action | Counts controller decisions. `action` in {demote,promote}. `reason` reflects triggering condition (e.g., sla_breach_streak, cardinality_guard, memory_pressure, healthy_recovery_N). |
| g6_option_detail_mode | Gauge | index | Current active detail mode per index (0 full, 1 band, 2 agg). Updated every cycle when adaptive controller enabled. |
| g6_vol_surface_quality_score | Gauge | index | Heuristic volatility surface quality score (0-1 or 0-100 depending on configuration). Higher is better. Placeholder until full heuristic implemented. |
| g6_vol_surface_interp_seconds | H |  | Interpolation phase latency (seconds) within a surface build. Helps isolate time spent filling gaps vs raw aggregation. |
| g6_vol_surface_model_build_seconds | H |  | (Scaffold) Model (e.g., SABR or alternative) build latency. Not populated until modeling plugin introduced. |
| g6_compressed_files_total | Counter |  | Lifecycle compression operations performed (files compressed). |
| g6_quarantine_scan_seconds | H |  | Latency scanning quarantine/retention directories. Buckets tuned for sub-ms to multi-second scans. |

Semantics:
1. Demotion triggers: sustained SLA breach streak, cardinality guard active, high memory tier.
2. Promotion triggers: sufficient consecutive healthy cycles without pressure, memory tier 0, guard inactive.
3. Chained promotions: If multiple recovery windows accumulated, promotions may skip intermediate modes (reason annotated as healthy_recovery_N).

Operational Guidance:
* Investigate chronic demotes with `reason=cardinality_guard` — may need broader ATM window or strike reduction earlier.
* High frequency `memory_pressure` demotions indicate tuning required for retention/compression or memory leak review.
* Absence of promotions over extended windows suggests persistent pressure — correlate with `g6_cycle_sla_breach_total` and memory tiers.

Planned Extensions:
* Add `g6_adaptive_detail_mode_transitions_total{from,to}` (fine-grained) if churn analysis required.
* Introduce `g6_adaptive_pressure_score` gauge (aggregated weighted signal strength) for external dashboards.



### Adaptive Analytics Follow-Up Guards (New)
Early anomaly signaling derived from analytics outputs (vol surface & risk aggregation) before severe performance degradation.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_followups_interp_guard | Counter | index | Interpolation fraction sustained above threshold for configured consecutive builds. |
| g6_followups_risk_drift | Counter | index,sign | Significant directional drift in delta notional over stable window (sign=up|down). |
| g6_followups_bucket_coverage | Counter | index | Bucket coverage below threshold for required consecutive builds. |
| g6_followups_last_state | Gauge | index,type | Last observed guard state (type=interp → fraction, risk → drift pct, bucket → utilization fraction). |

Environment Flags: `G6_FOLLOWUPS_*` (see `env_dict.md` section 19c).

Heuristics & Notes:
1. Interpolation Guard resets streak after trigger to avoid alert storms.
2. Risk drift requires option count stability (range/mean <5%) and sufficient liquidity (>= minimum options).
3. Bucket coverage guard uses utilization = populated / theoretical; theoretical approximated via unique labels present.
4. Gauge values facilitate dashboards showing current state vs configured thresholds.

PromQL Examples:
```
increase(g6_followups_interp_guard[10m]) > 0
increase(g6_followups_risk_drift[15m]) > 1
g6_followups_last_state{type="interp"} > 0.6
g6_followups_last_state{type="bucket"} < 0.7
```

Planned Follow-Ups:
- Integrate triggers with adaptive controller detail mode demotions.
- Add alert suppression/hysteresis metrics if flapping observed in production.
- Optional event log entries for each trigger (currently counters only).



