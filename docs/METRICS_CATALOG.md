# G6 Metrics Catalog

Auto-generated from YAML specification (`metrics/spec/base.yml`). Do not edit manually — regenerate via `scripts/gen_metrics.py`.

Generated: (runtime)

## Group Gating Environment Variables

- **adaptive_controller**: G6_ENABLE_METRIC_GROUPS, G6_ADAPTIVE_CONTROLLER
- **analytics_vol_surface**: G6_ENABLE_METRIC_GROUPS, G6_VOL_SURFACE, G6_VOL_SURFACE_PER_EXPIRY
- **greeks**: G6_ENABLE_METRIC_GROUPS
- **panel_diff**: G6_ENABLE_METRIC_GROUPS
- **panels_integrity**: G6_ENABLE_METRIC_GROUPS
- **perf_cache**: G6_ENABLE_METRIC_GROUPS

Attr | Prom Name | Type | Group | Labels | Cardinality | Example Query | Description | Conditional
--- | --- | --- | --- | --- | --- | --- | --- | ---
adaptive_controller_actions | g6_adaptive_controller_actions_total | Counter | adaptive_controller | reason,action | moderate | rate(g6_adaptive_controller_actions_total[5m]) | Adaptive controller actions taken | Y
option_detail_mode | g6_option_detail_mode | Gauge | adaptive_controller | index | low-moderate | avg by (index) (g6_option_detail_mode) | Current option detail mode (0=full,1=medium,2=low) | Y
vol_surface_interp_seconds | g6_vol_surface_interp_seconds | Histogram | analytics_vol_surface |  | low | rate(g6_vol_surface_interp_seconds_bucket[5m]) | Interpolation timing distribution | Y
vol_surface_interpolated_fraction | g6_vol_surface_interpolated_fraction | Gauge | analytics_vol_surface | index | low-moderate | avg by (index) (g6_vol_surface_interpolated_fraction) | Fraction of interpolated rows in surface | Y
vol_surface_quality_score | g6_vol_surface_quality_score | Gauge | analytics_vol_surface | index | low-moderate | avg by (index) (g6_vol_surface_quality_score) | Vol surface quality score (0-100) | Y
vol_surface_rows | g6_vol_surface_rows | Gauge | analytics_vol_surface | index,source | moderate | avg by (index) (g6_vol_surface_rows) | Vol surface row count by source | Y
vol_surface_rows_expiry | g6_vol_surface_rows_expiry | Gauge | analytics_vol_surface | index,expiry,source | high | avg by (index) (g6_vol_surface_rows_expiry) | Vol surface per-expiry row count by source | Y
iv_iterations | g6_iv_estimation_avg_iterations | Gauge | greeks | index,expiry | moderate | avg by (index) (g6_iv_estimation_avg_iterations) | Average IV solver iterations (rolling per cycle) | N
iv_fail | g6_iv_estimation_failure | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_failure[5m]) | Failed IV estimations (alias short form) | N
iv_fail_alias | g6_iv_estimation_failure | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_failure[5m]) | Failed IV solves (spec alias) | N
iv_success | g6_iv_estimation_success | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_success[5m]) | Successful IV estimations (alias short form) | N
iv_success_alias | g6_iv_estimation_success | Counter | greeks | index,expiry | moderate | rate(g6_iv_estimation_success[5m]) | Successful IV solves (spec alias) | N
panel_diff_bytes_last | g6_panel_diff_bytes_last | Gauge | panel_diff | type | low-moderate | avg by (type) (g6_panel_diff_bytes_last) | Bytes of last diff JSON written | N
panel_diff_bytes_total | g6_panel_diff_bytes_total | Counter | panel_diff | type | low-moderate | rate(g6_panel_diff_bytes_total[5m]) | Total bytes of diff JSON written | N
panel_diff_truncated | g6_panel_diff_truncated_total | Counter | panel_diff | reason | low-moderate | rate(g6_panel_diff_truncated_total[5m]) | Panel diff truncation events | N
panel_diff_writes | g6_panel_diff_writes_total | Counter | panel_diff | type | low-moderate | rate(g6_panel_diff_writes_total[5m]) | Panel diff snapshots written | N
panels_integrity_checks | g6_panels_integrity_checks_total | Counter | panels_integrity |  | low | rate(g6_panels_integrity_checks_total[5m]) | Total panel integrity checks run | N
panels_integrity_failures | g6_panels_integrity_failures_total | Counter | panels_integrity |  | low | rate(g6_panels_integrity_failures_total[5m]) | Total panel integrity check failures | N
panels_integrity_last_elapsed | g6_panels_integrity_last_elapsed_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_elapsed_seconds) | Seconds taken by the last integrity check | N
panels_integrity_last_gap | g6_panels_integrity_last_gap_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_gap_seconds) | Gap (seconds) since last successful check | N
panels_integrity_last_success_age | g6_panels_integrity_last_success_age_seconds | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_last_success_age_seconds) | Age (seconds) of last successful integrity pass | N
panels_integrity_mismatches | g6_panels_integrity_mismatches | Counter | panels_integrity |  | low | rate(g6_panels_integrity_mismatches[5m]) | Cumulative panel hash mismatches detected | N
panels_integrity_ok | g6_panels_integrity_ok | Gauge | panels_integrity |  | low | avg(g6_panels_integrity_ok) | Panels integrity check pass state (1 ok / 0 failing) | N
root_cache_evictions | g6_root_cache_evictions | Counter | perf_cache |  | low | rate(g6_root_cache_evictions[5m]) | Root symbol cache evictions | N
root_cache_hit_ratio | g6_root_cache_hit_ratio | Gauge | perf_cache |  | low | avg(g6_root_cache_hit_ratio) | Root symbol cache hit ratio (0-1) | N
root_cache_hits | g6_root_cache_hits | Counter | perf_cache |  | low | rate(g6_root_cache_hits[5m]) | Root symbol cache hits | N
root_cache_misses | g6_root_cache_misses | Counter | perf_cache |  | low | rate(g6_root_cache_misses[5m]) | Root symbol cache misses | N
root_cache_size | g6_root_cache_size | Gauge | perf_cache |  | low | avg(g6_root_cache_size) | Current root symbol cache size | N
serial_cache_hits | g6_serial_cache_hits_total | Counter | perf_cache |  | low | rate(g6_serial_cache_hits_total[5m]) | Serialization cache hits | N
serial_cache_misses | g6_serial_cache_misses_total | Counter | perf_cache |  | low | rate(g6_serial_cache_misses_total[5m]) | Serialization cache misses | N
serial_cache_evictions | g6_serial_cache_evictions_total | Counter | perf_cache |  | low | rate(g6_serial_cache_evictions_total[5m]) | Serialization cache evictions | N
serial_cache_size | g6_serial_cache_size | Gauge | perf_cache |  | low | avg(g6_serial_cache_size) | Serialization cache current size | N
serial_cache_hit_ratio | g6_serial_cache_hit_ratio | Gauge | perf_cache |  | low | avg(g6_serial_cache_hit_ratio) | Serialization cache hit ratio (0-1) | N
sse_serialize_seconds | g6_sse_serialize_seconds | Histogram | perf_cache |  | low | rate(g6_sse_serialize_seconds_bucket[5m]) | Serialization time distribution for SSE payloads | Y
sse_flush_seconds | g6_sse_flush_latency_seconds | Histogram | perf_cache |  | low | rate(g6_sse_flush_latency_seconds_bucket[5m]) | Publish-to-flush latency distribution | Y
sse_trace_stages_total | g6_sse_trace_stages_total | Counter | perf_cache |  | low | rate(g6_sse_trace_stages_total[5m]) | Trace stage observations (serialize+flush) | Y
adaptive_backlog_ratio | g6_adaptive_backlog_ratio | Gauge | perf_cache |  | low | avg(g6_adaptive_backlog_ratio) | Adaptive controller backlog ratio sample | Y
adaptive_transitions_total | g6_adaptive_transitions_total | Counter | perf_cache | reason | low | rate(g6_adaptive_transitions_total[5m]) | Adaptive controller transitions | Y
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
provider_mode | g6_provider_mode | Gauge |  | mode | low-moderate | avg by (mode) (g6_provider_mode) | Current provider mode (one-hot gauge) | N
pcr | g6_put_call_ratio | Gauge |  | index,expiry | moderate | avg by (index) (g6_put_call_ratio) | Put-Call Ratio | N
risk_agg_bucket_utilization | g6_risk_agg_bucket_utilization | Gauge |  |  | low | avg(g6_risk_agg_bucket_utilization) | Risk aggregation bucket utilization fraction (0-1) | N
risk_agg_notional_delta | g6_risk_agg_notional_delta | Gauge |  |  | low | avg(g6_risk_agg_notional_delta) | Aggregate delta notional for last risk aggregation | N
risk_agg_notional_vega | g6_risk_agg_notional_vega | Gauge |  |  | low | avg(g6_risk_agg_notional_vega) | Aggregate vega notional for last risk aggregation | N
risk_agg_rows | g6_risk_agg_rows | Gauge |  |  | low | avg(g6_risk_agg_rows) | Rows in last risk aggregation build | N
