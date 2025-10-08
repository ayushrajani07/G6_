# G6 Metrics Catalog

Auto-generated from declarative specification (`spec.py`). Do not edit manually.

Generated: (runtime)

## Group Gating Environment Variables

- **adaptive_controller**: G6_ENABLE_METRIC_GROUPS, G6_ADAPTIVE_CONTROLLER
- **analytics_risk_agg**: G6_ENABLE_METRIC_GROUPS, G6_RISK_AGG
- **analytics_vol_surface**: G6_ENABLE_METRIC_GROUPS, G6_VOL_SURFACE, G6_VOL_SURFACE_PER_EXPIRY
- **cache**: (none)
- **greeks**: G6_ENABLE_METRIC_GROUPS
- **panels_integrity**: G6_ENABLE_METRIC_GROUPS
- **sse_ingest**: G6_ENABLE_METRIC_GROUPS, G6_SSE_INGEST

Attr | Prom Name | Type | Group | Labels | Cardinality | Example Query | Description | Conditional
--- | --- | --- | --- | --- | --- | --- | --- | ---
adaptive_controller_actions | g6_adaptive_controller_actions_total | Counter | adaptive_controller | reason,action | moderate | rate(g6_adaptive_controller_actions_total[5m]) | Adaptive controller actions taken | Y
adaptive_interpolation_alerts | g6_adaptive_interpolation_alerts_total | Counter | adaptive_controller | index,reason | moderate | rate(g6_adaptive_interpolation_alerts_total[5m]) | Interpolation fraction high streak alerts | Y
adaptive_interpolation_streak | g6_adaptive_interpolation_streak | Gauge | adaptive_controller | index | low-moderate | avg by (index) (g6_adaptive_interpolation_streak) | Current consecutive builds above interpolation fraction threshold | Y
option_detail_mode | g6_option_detail_mode | Gauge | adaptive_controller | index | low-moderate | avg by (index) (g6_option_detail_mode) | Current option detail mode (0=full,1=medium,2=low) | Y
risk_agg_bucket_utilization | g6_risk_agg_bucket_utilization | Gauge | analytics_risk_agg |  | low | avg(g6_risk_agg_bucket_utilization) | Risk aggregation bucket utilization fraction (0-1) | Y
risk_agg_notional_delta | g6_risk_agg_notional_delta | Gauge | analytics_risk_agg |  | low | avg(g6_risk_agg_notional_delta) | Aggregate delta notional for last risk aggregation | Y
risk_agg_notional_vega | g6_risk_agg_notional_vega | Gauge | analytics_risk_agg |  | low | avg(g6_risk_agg_notional_vega) | Aggregate vega notional for last risk aggregation | Y
risk_agg_rows | g6_risk_agg_rows | Gauge | analytics_risk_agg |  | low | avg(g6_risk_agg_rows) | Rows in last risk aggregation build | Y
vol_surface_interp_seconds | g6_vol_surface_interp_seconds | Histogram | analytics_vol_surface |  | low | rate(g6_vol_surface_interp_seconds_bucket[5m]) | Interpolation timing distribution | Y
vol_surface_interpolated_fraction | g6_vol_surface_interpolated_fraction | Gauge | analytics_vol_surface | index | low-moderate | avg by (index) (g6_vol_surface_interpolated_fraction) | Fraction of interpolated rows in surface | Y
vol_surface_quality_score | g6_vol_surface_quality_score | Gauge | analytics_vol_surface | index | low-moderate | avg by (index) (g6_vol_surface_quality_score) | Vol surface quality score (0-100) | Y
vol_surface_rows | g6_vol_surface_rows | Gauge | analytics_vol_surface | index,source | moderate | avg by (index) (g6_vol_surface_rows) | Vol surface row count by source | Y
vol_surface_rows_expiry | g6_vol_surface_rows_expiry | Gauge | analytics_vol_surface | index,expiry,source | high | avg by (index) (g6_vol_surface_rows_expiry) | Vol surface per-expiry row count by source | Y
adaptive_backlog_ratio | g6_adaptive_backlog_ratio | Gauge | cache |  | low | avg(g6_adaptive_backlog_ratio) | Current backlog ratio sample used by adaptive controller (0-1) | Y
adaptive_transitions_total | g6_adaptive_transitions_total | Counter | cache |  | low | rate(g6_adaptive_transitions_total[5m]) | Adaptive controller transitions (reason) | Y
quote_cache_hit_ratio | g6_quote_cache_hit_ratio | Gauge | cache |  | low | avg(g6_quote_cache_hit_ratio) | Quote cache hit ratio (0-1) | Y
quote_cache_hits | g6_quote_cache_hits_total | Counter | cache |  | low | rate(g6_quote_cache_hits_total[5m]) | Quote cache hits | Y
quote_cache_misses | g6_quote_cache_misses_total | Counter | cache |  | low | rate(g6_quote_cache_misses_total[5m]) | Quote cache misses | Y
quote_cache_size | g6_quote_cache_size | Gauge | cache |  | low | avg(g6_quote_cache_size) | Quote cache current size | Y
root_cache_evictions | g6_root_cache_evictions | Counter | cache |  | low | rate(g6_root_cache_evictions[5m]) | Root symbol cache evictions | Y
root_cache_hit_ratio | g6_root_cache_hit_ratio | Gauge | cache |  | low | avg(g6_root_cache_hit_ratio) | Root symbol cache hit ratio (0-1) | N
root_cache_hits | g6_root_cache_hits | Counter | cache |  | low | rate(g6_root_cache_hits[5m]) | Root symbol cache hits | Y
root_cache_misses | g6_root_cache_misses | Counter | cache |  | low | rate(g6_root_cache_misses[5m]) | Root symbol cache misses | Y
root_cache_size | g6_root_cache_size | Gauge | cache |  | low | avg(g6_root_cache_size) | Current root symbol cache size | Y
serial_cache_evictions | g6_serial_cache_evictions_total | Counter | cache |  | low | rate(g6_serial_cache_evictions_total[5m]) | Serialization cache evictions | Y
serial_cache_hit_ratio | g6_serial_cache_hit_ratio | Gauge | cache |  | low | avg(g6_serial_cache_hit_ratio) | Serialization cache hit ratio (0-1) | Y
serial_cache_hits | g6_serial_cache_hits_total | Counter | cache |  | low | rate(g6_serial_cache_hits_total[5m]) | Serialization cache hits | Y
serial_cache_misses | g6_serial_cache_misses_total | Counter | cache |  | low | rate(g6_serial_cache_misses_total[5m]) | Serialization cache misses | Y
serial_cache_size | g6_serial_cache_size | Gauge | cache |  | low | avg(g6_serial_cache_size) | Serialization cache current size | Y
sse_flush_seconds | g6_sse_flush_latency_seconds | Histogram | cache |  | low | rate(g6_sse_flush_latency_seconds_bucket[5m]) | End-to-end publish-to-flush latency (server internal) for SSE events | Y
sse_serialize_seconds | g6_sse_serialize_seconds | Histogram | cache |  | low | rate(g6_sse_serialize_seconds_bucket[5m]) | Serialization time distribution for SSE event payloads | Y
sse_trace_stages_total | g6_sse_trace_stages_total | Counter | cache |  | low | rate(g6_sse_trace_stages_total[5m]) | Total trace stage observations (serialize + flush) | Y
iv_iterations | g6_iv_estimation_avg_iterations | Gauge | greeks | index,expiry | moderate | avg by (index) (g6_iv_estimation_avg_iterations) | Average IV solver iterations (rolling per cycle) | N
iv_fail | g6_iv_estimation_failure | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_failure[5m]) | Failed IV estimations (alias short form) | N
iv_fail_alias | g6_iv_estimation_failure | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_failure[5m]) | Failed IV solves (spec alias) | N
iv_success | g6_iv_estimation_success | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_success[5m]) | Successful IV estimations (alias short form) | N
iv_success_alias | g6_iv_estimation_success | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_success[5m]) | Successful IV solves (spec alias) | N
panels_integrity_checks | g6_panels_integrity_checks_total | Counter | panels_integrity |  | low | rate(g6_panels_integrity_checks_total[5m]) | Total panel integrity checks run | N
panels_integrity_failures | g6_panels_integrity_failures_total | Counter | panels_integrity |  | low | rate(g6_panels_integrity_failures_total[5m]) | Total panel integrity check failures | N
panels_integrity_last_elapsed | g6_panels_integrity_last_elapsed_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_elapsed_seconds) | Seconds taken by the last integrity check | N
panels_integrity_last_gap | g6_panels_integrity_last_gap_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_gap_seconds) | Gap (seconds) since last successful check | N
panels_integrity_last_success_age | g6_panels_integrity_last_success_age_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_success_age_seconds) | Age (seconds) of last successful integrity pass | N
panels_integrity_mismatches | g6_panels_integrity_mismatches | Counter | panels_integrity |  | low | rate(g6_panels_integrity_mismatches[5m]) | Cumulative panel hash mismatches detected | N
panels_integrity_ok | g6_panels_integrity_ok | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_ok) | Panels integrity check pass state (1 ok / 0 failing) | N
sse_apply_diff_total | g6_sse_apply_diff_total | Counter | sse_ingest |  | low | rate(g6_sse_apply_diff_total[5m]) | Count of SSE panel diff merges applied | N
sse_apply_full_total | g6_sse_apply_full_total | Counter | sse_ingest |  | low | rate(g6_sse_apply_full_total[5m]) | Count of SSE panel full replacements applied | N
sse_backoff_seconds | g6_sse_backoff_seconds | Histogram | sse_ingest |  | low | rate(g6_sse_backoff_seconds_bucket[5m]) | Backoff sleep duration seconds distribution for SSE reconnect attempts | N
sse_reconnects_total | g6_sse_reconnects_total | Counter | sse_ingest | reason | low-moderate | rate(g6_sse_reconnects_total[5m]) | Number of SSE reconnect attempts (by reason) | N
collection_cycles | g6_collection_cycles | Counter |  |  | low | rate(g6_collection_cycles[5m]) | Number of collection cycles run | N
collection_duration | g6_collection_duration_seconds | Summary |  |  | low | quantile(0.9, g6_collection_duration_seconds_sum / g6_collection_duration_seconds_count) | Time spent collecting data | N
collection_errors | g6_collection_errors | Counter |  | index,error_type | moderate | rate(g6_collection_errors[5m]) | Number of collection errors | N
config_deprecated_keys | g6_config_deprecated_keys | Counter |  | key | low-moderate | rate(g6_config_deprecated_keys[5m]) | Deprecated/legacy config keys encountered | N
index_atm | g6_index_atm_strike | Gauge |  | index | low-moderate | avg by (index) (g6_index_atm_strike) | ATM strike price | N
index_price | g6_index_price | Gauge |  | index | low-moderate | avg by (index) (g6_index_price) | Current index price | N
option_iv | g6_option_iv | Gauge |  | index,expiry,strike,type | very_high | avg by (index) (g6_option_iv) | Option implied volatility | N
option_oi | g6_option_oi | Gauge |  | index,expiry,strike,type | very_high | avg by (index) (g6_option_oi) | Option open interest | N
option_price | g6_option_price | Gauge |  | index,expiry,strike,type | very_high | avg by (index) (g6_option_price) | Option price | N
option_volume | g6_option_volume | Gauge |  | index,expiry,strike,type | very_high | avg by (index) (g6_option_volume) | Option volume | N
options_collected | g6_options_collected | Gauge |  | index,expiry | moderate | avg by (index) (g6_options_collected) | Number of options collected | N
pipeline_cycle_error_rate_window | g6_pipeline_cycle_error_rate_window | Gauge |  |  | low | avg(g6_pipeline_cycle_error_rate_window) | Rolling window error rate (0-1) across last N cycles | N
pipeline_cycle_error_ratio | g6_pipeline_cycle_error_ratio | Gauge |  |  | low | avg(g6_pipeline_cycle_error_ratio) | Per-cycle phase error ratio (phases_error / phases_total) | N
pipeline_cycle_success | g6_pipeline_cycle_success | Gauge |  |  | low | avg(g6_pipeline_cycle_success) | Pipeline cycle success state (1 if no phase errors else 0) | N
pipeline_cycle_success_rate_window | g6_pipeline_cycle_success_rate_window | Gauge |  |  | low | avg(g6_pipeline_cycle_success_rate_window) | Rolling window success rate (0-1) across last N cycles | N
pipeline_cycles_success_total | g6_pipeline_cycles_success_total | Counter |  |  | low | rate(g6_pipeline_cycles_success_total[5m]) | Total successful pipeline cycles (no phase errors) | N
pipeline_cycles_total | g6_pipeline_cycles_total | Counter |  |  | low | rate(g6_pipeline_cycles_total[5m]) | Total pipeline cycles executed (summary produced) | N
pipeline_phase_attempts | g6_pipeline_phase_attempts_total | Counter |  |  | low | rate(g6_pipeline_phase_attempts_total[5m]) | Total phase attempts (includes retries) | N
pipeline_phase_duration_ms | g6_pipeline_phase_duration_ms_total | Counter |  |  | low | rate(g6_pipeline_phase_duration_ms_total[5m]) | Cumulative wall clock milliseconds spent in phase (across attempts) | N
pipeline_phase_duration_seconds | g6_pipeline_phase_duration_seconds | Histogram |  |  | low | rate(g6_pipeline_phase_duration_seconds_bucket[5m]) | Histogram of individual phase execution wall time in seconds (attempts aggregated) | N
pipeline_phase_error_records | g6_pipeline_phase_error_records_total | Counter |  |  | low | rate(g6_pipeline_phase_error_records_total[5m]) | Total structured phase error records captured (one per legacy token) | Y
pipeline_phase_outcomes | g6_pipeline_phase_outcomes_total | Counter |  |  | low | rate(g6_pipeline_phase_outcomes_total[5m]) | Final phase outcomes (one per phase execution sequence) | N
pipeline_phase_retries | g6_pipeline_phase_retries_total | Counter |  |  | low | rate(g6_pipeline_phase_retries_total[5m]) | Total phase retry attempts (attempt index > 1) | N
pipeline_phase_runs | g6_pipeline_phase_runs_total | Counter |  |  | low | rate(g6_pipeline_phase_runs_total[5m]) | Number of completed phase executions (post-retry finalization) | N
pipeline_trends_cycles | g6_pipeline_trends_cycles | Gauge |  |  | low | avg(g6_pipeline_trends_cycles) | Total cycles represented in trend aggregation file | N
pipeline_trends_success_rate | g6_pipeline_trends_success_rate | Gauge |  |  | low | avg(g6_pipeline_trends_success_rate) | Success rate derived from trend aggregation file (long horizon) | N
provider_mode | g6_provider_mode | Gauge |  | mode | low-moderate | avg by (mode) (g6_provider_mode) | Current provider mode (one-hot gauge) | N
pcr | g6_put_call_ratio | Gauge |  | index,expiry | moderate | avg by (index) (g6_put_call_ratio) | Put-Call Ratio | N
stream_append | g6_stream_append_total | Counter |  | mode | low-moderate | rate(g6_stream_append_total[5m]) | Indices stream append events | N
stream_conflict | g6_stream_conflict_total | Counter |  |  | low | rate(g6_stream_conflict_total[5m]) | Potential concurrent indices stream writer conflicts detected | N
stream_skipped | g6_stream_skipped_total | Counter |  | mode,reason | moderate | rate(g6_stream_skipped_total[5m]) | Indices stream gating skips | N
stream_state_persist_errors | g6_stream_state_persist_errors_total | Counter |  |  | low | rate(g6_stream_state_persist_errors_total[5m]) | State file persistence errors for indices stream gating | N
