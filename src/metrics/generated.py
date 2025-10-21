# Auto-generated file
# SOURCE OF TRUTH: metrics/spec/base.yml (YAML)
# DO NOT EDIT MANUALLY - run scripts/gen_metrics.py after modifying the spec.


from __future__ import annotations

from typing import Any

from .cardinality_guard import registry_guard


# Typing-friendly helpers to access metric.label() and set value without
# requiring prometheus_client types at analysis time.
def _labels(m: Any, **kwargs: Any) -> Any:
    try:
        return m.labels(**kwargs)
    except Exception:
        return None

def _labels_set(m: Any, value: float, **kwargs: Any) -> None:
    try:
        h = m.labels(**kwargs)
        s = getattr(h, 'set', None)
        if callable(s):
            s(value)
    except Exception:
        pass

_METRICS: dict[str, Any] = {}  # name -> metric instance

def _get(name: str): return _METRICS.get(name)

SPEC_HASH = '0533405d11f9f66e'  # short sha256 of spec file

def m_api_calls_total():
    if 'g6_api_calls_total' not in _METRICS:
        _METRICS['g6_api_calls_total'] = registry_guard.counter('g6_api_calls_total', 'Provider API calls', ['endpoint', 'result'], 50)
    return _METRICS['g6_api_calls_total']

def m_api_calls_total_labels(endpoint: str, result: str):
    metric = m_api_calls_total()
    if not metric: return None
    if not registry_guard.track('g6_api_calls_total', (endpoint,result,)): return None
    return _labels(metric, endpoint=endpoint, result=result)

def m_api_response_latency_ms():
    if 'g6_api_response_latency_ms' not in _METRICS:
        _METRICS['g6_api_response_latency_ms'] = registry_guard.histogram('g6_api_response_latency_ms', 'Upstream API response latency (ms)', [], 1, buckets=[5, 10, 20, 50, 100, 200, 400, 800, 1600, 3200])
    return _METRICS['g6_api_response_latency_ms']

def m_quote_enriched_total():
    if 'g6_quote_enriched_total' not in _METRICS:
        _METRICS['g6_quote_enriched_total'] = registry_guard.counter('g6_quote_enriched_total', 'Quotes enriched', ['provider'], 5)
    return _METRICS['g6_quote_enriched_total']

def m_quote_enriched_total_labels(provider: str):
    metric = m_quote_enriched_total()
    if not metric: return None
    if not registry_guard.track('g6_quote_enriched_total', (provider,)): return None
    return _labels(metric, provider=provider)

def m_quote_missing_volume_oi_total():
    if 'g6_quote_missing_volume_oi_total' not in _METRICS:
        _METRICS['g6_quote_missing_volume_oi_total'] = registry_guard.counter('g6_quote_missing_volume_oi_total', 'Enriched quotes missing volume & oi', ['provider'], 5)
    return _METRICS['g6_quote_missing_volume_oi_total']

def m_quote_missing_volume_oi_total_labels(provider: str):
    metric = m_quote_missing_volume_oi_total()
    if not metric: return None
    if not registry_guard.track('g6_quote_missing_volume_oi_total', (provider,)): return None
    return _labels(metric, provider=provider)

def m_quote_avg_price_fallback_total():
    if 'g6_quote_avg_price_fallback_total' not in _METRICS:
        _METRICS['g6_quote_avg_price_fallback_total'] = registry_guard.counter('g6_quote_avg_price_fallback_total', 'Avg price fallback usage', ['provider'], 5)
    return _METRICS['g6_quote_avg_price_fallback_total']

def m_quote_avg_price_fallback_total_labels(provider: str):
    metric = m_quote_avg_price_fallback_total()
    if not metric: return None
    if not registry_guard.track('g6_quote_avg_price_fallback_total', (provider,)): return None
    return _labels(metric, provider=provider)

def m_index_zero_price_fallback_total():
    if 'g6_index_zero_price_fallback_total' not in _METRICS:
        _METRICS['g6_index_zero_price_fallback_total'] = registry_guard.counter('g6_index_zero_price_fallback_total', 'Index zero price synthetic fallback applied', ['index', 'path'], 30)
    return _METRICS['g6_index_zero_price_fallback_total']

def m_index_zero_price_fallback_total_labels(index: str, path: str):
    metric = m_index_zero_price_fallback_total()
    if not metric: return None
    if not registry_guard.track('g6_index_zero_price_fallback_total', (index,path,)): return None
    return _labels(metric, index=index, path=path)

def m_expiry_resolve_fail_total():
    if 'g6_expiry_resolve_fail_total' not in _METRICS:
        _METRICS['g6_expiry_resolve_fail_total'] = registry_guard.counter('g6_expiry_resolve_fail_total', 'Expiry resolution failures', ['index', 'rule', 'reason'], 120)
    return _METRICS['g6_expiry_resolve_fail_total']

def m_expiry_resolve_fail_total_labels(index: str, rule: str, reason: str):
    metric = m_expiry_resolve_fail_total()
    if not metric: return None
    if not registry_guard.track('g6_expiry_resolve_fail_total', (index,rule,reason,)): return None
    return _labels(metric, index=index, rule=rule, reason=reason)

def m_metrics_batch_queue_depth():
    if 'g6_metrics_batch_queue_depth' not in _METRICS:
        _METRICS['g6_metrics_batch_queue_depth'] = registry_guard.gauge('g6_metrics_batch_queue_depth', 'Current queued batched counter increments awaiting flush', [], 1)
    return _METRICS['g6_metrics_batch_queue_depth']

def m_cardinality_series_total():
    if 'g6_cardinality_series_total' not in _METRICS:
        _METRICS['g6_cardinality_series_total'] = registry_guard.gauge('g6_cardinality_series_total', 'Observed unique label sets registered per metric name', ['metric'], 200)
    return _METRICS['g6_cardinality_series_total']

def m_cardinality_series_total_labels(metric_name: str):
    _m = m_cardinality_series_total()
    if not _m: return None
    if not registry_guard.track('g6_cardinality_series_total', (metric_name,)): return None
    return _labels(_m, metric=metric_name)

def m_api_success_rate_percent():
    if 'g6_api_success_rate_percent' not in _METRICS:
        _METRICS['g6_api_success_rate_percent'] = registry_guard.gauge('g6_api_success_rate_percent', 'Successful API call percentage (rolling window)', [], 1)
    return _METRICS['g6_api_success_rate_percent']

def m_api_response_time_ms():
    if 'g6_api_response_time_ms' not in _METRICS:
        _METRICS['g6_api_response_time_ms'] = registry_guard.gauge('g6_api_response_time_ms', 'Average upstream API response time (ms, rolling)', [], 1)
    return _METRICS['g6_api_response_time_ms']

def m_provider_mode():
    if 'g6_provider_mode' not in _METRICS:
        _METRICS['g6_provider_mode'] = registry_guard.gauge('g6_provider_mode', 'Active provider mode (one-hot by mode label)', ['mode'], 6)
    return _METRICS['g6_provider_mode']

def m_provider_mode_labels(mode: str):
    metric = m_provider_mode()
    if not metric: return None
    if not registry_guard.track('g6_provider_mode', (mode,)): return None
    return _labels(metric, mode=mode)

def m_provider_failover_total():
    if 'g6_provider_failover_total' not in _METRICS:
        _METRICS['g6_provider_failover_total'] = registry_guard.counter('g6_provider_failover_total', 'Provider failovers', [], 1)
    return _METRICS['g6_provider_failover_total']

def m_metrics_spec_hash_info():
    if 'g6_metrics_spec_hash_info' not in _METRICS:
        _METRICS['g6_metrics_spec_hash_info'] = registry_guard.gauge('g6_metrics_spec_hash_info', 'Static gauge labeled with current metrics spec content hash (value always 1)', ['hash'], 1)
    return _METRICS['g6_metrics_spec_hash_info']

def m_metrics_spec_hash_info_labels(hash: str):
    metric = m_metrics_spec_hash_info()
    if not metric: return None
    if not registry_guard.track('g6_metrics_spec_hash_info', (hash,)): return None
    return _labels(metric, hash=hash)

def m_build_config_hash_info():
    if 'g6_build_config_hash_info' not in _METRICS:
        _METRICS['g6_build_config_hash_info'] = registry_guard.gauge('g6_build_config_hash_info', 'Static gauge labeled with current build/config content hash (value always 1)', ['hash'], 1)
    return _METRICS['g6_build_config_hash_info']

def m_build_config_hash_info_labels(hash: str):
    metric = m_build_config_hash_info()
    if not metric: return None
    if not registry_guard.track('g6_build_config_hash_info', (hash,)): return None
    return _labels(metric, hash=hash)

def m_metric_duplicates_total():
    if 'g6_metric_duplicates_total' not in _METRICS:
        _METRICS['g6_metric_duplicates_total'] = registry_guard.counter('g6_metric_duplicates_total', 'Count of duplicate metric registration attempts (same metric name registered more than once)', ['name'], 50)
    return _METRICS['g6_metric_duplicates_total']

def m_metric_duplicates_total_labels(name: str):
    metric = m_metric_duplicates_total()
    if not metric: return None
    if not registry_guard.track('g6_metric_duplicates_total', (name,)): return None
    return _labels(metric, name=name)

def m_cardinality_guard_offenders_total():
    if 'g6_cardinality_guard_offenders_total' not in _METRICS:
        _METRICS['g6_cardinality_guard_offenders_total'] = registry_guard.gauge('g6_cardinality_guard_offenders_total', 'Number of offending metric groups exceeding allowed growth threshold during last cardinality guard evaluation', [], 1)
    return _METRICS['g6_cardinality_guard_offenders_total']

def m_cardinality_guard_new_groups_total():
    if 'g6_cardinality_guard_new_groups_total' not in _METRICS:
        _METRICS['g6_cardinality_guard_new_groups_total'] = registry_guard.gauge('g6_cardinality_guard_new_groups_total', 'Number of entirely new metric groups discovered relative to baseline during last guard evaluation', [], 1)
    return _METRICS['g6_cardinality_guard_new_groups_total']

def m_cardinality_guard_last_run_epoch():
    if 'g6_cardinality_guard_last_run_epoch' not in _METRICS:
        _METRICS['g6_cardinality_guard_last_run_epoch'] = registry_guard.gauge('g6_cardinality_guard_last_run_epoch', 'Unix epoch seconds timestamp of last successful cardinality guard evaluation', [], 1)
    return _METRICS['g6_cardinality_guard_last_run_epoch']

def m_cardinality_guard_allowed_growth_percent():
    if 'g6_cardinality_guard_allowed_growth_percent' not in _METRICS:
        _METRICS['g6_cardinality_guard_allowed_growth_percent'] = registry_guard.gauge('g6_cardinality_guard_allowed_growth_percent', 'Allowed growth threshold percent configured for cardinality guard at last evaluation', [], 1)
    return _METRICS['g6_cardinality_guard_allowed_growth_percent']

def m_cardinality_guard_growth_percent():
    if 'g6_cardinality_guard_growth_percent' not in _METRICS:
        _METRICS['g6_cardinality_guard_growth_percent'] = registry_guard.gauge('g6_cardinality_guard_growth_percent', 'Observed growth percent for a metric group exceeding baseline (labels: group)', ['group'], 100)
    return _METRICS['g6_cardinality_guard_growth_percent']

def m_cardinality_guard_growth_percent_labels(group: str):
    metric = m_cardinality_guard_growth_percent()
    if not metric: return None
    if not registry_guard.track('g6_cardinality_guard_growth_percent', (group,)): return None
    return _labels(metric, group=group)

def m_option_contracts_active():
    if 'g6_option_contracts_active' not in _METRICS:
        _METRICS['g6_option_contracts_active'] = registry_guard.gauge('g6_option_contracts_active', 'Active option contracts per moneyness & DTE bucket (snapshot)', ['mny', 'dte'], 25)
    return _METRICS['g6_option_contracts_active']

def m_option_contracts_active_labels(mny: str, dte: str):
    metric = m_option_contracts_active()
    if not metric: return None
    if not registry_guard.track('g6_option_contracts_active', (mny,dte,)): return None
    return _labels(metric, mny=mny, dte=dte)

def m_option_open_interest():
    if 'g6_option_open_interest' not in _METRICS:
        _METRICS['g6_option_open_interest'] = registry_guard.gauge('g6_option_open_interest', 'Aggregated open interest per bucket', ['mny', 'dte'], 25)
    return _METRICS['g6_option_open_interest']

def m_option_open_interest_labels(mny: str, dte: str):
    metric = m_option_open_interest()
    if not metric: return None
    if not registry_guard.track('g6_option_open_interest', (mny,dte,)): return None
    return _labels(metric, mny=mny, dte=dte)

def m_option_volume_24h():
    if 'g6_option_volume_24h' not in _METRICS:
        _METRICS['g6_option_volume_24h'] = registry_guard.gauge('g6_option_volume_24h', '24h traded volume aggregated per bucket', ['mny', 'dte'], 25)
    return _METRICS['g6_option_volume_24h']

def m_option_volume_24h_labels(mny: str, dte: str):
    metric = m_option_volume_24h()
    if not metric: return None
    if not registry_guard.track('g6_option_volume_24h', (mny,dte,)): return None
    return _labels(metric, mny=mny, dte=dte)

def m_option_iv_mean():
    if 'g6_option_iv_mean' not in _METRICS:
        _METRICS['g6_option_iv_mean'] = registry_guard.gauge('g6_option_iv_mean', 'Mean implied volatility annualized per bucket', ['mny', 'dte'], 25)
    return _METRICS['g6_option_iv_mean']

def m_option_iv_mean_labels(mny: str, dte: str):
    metric = m_option_iv_mean()
    if not metric: return None
    if not registry_guard.track('g6_option_iv_mean', (mny,dte,)): return None
    return _labels(metric, mny=mny, dte=dte)

def m_option_spread_bps_mean():
    if 'g6_option_spread_bps_mean' not in _METRICS:
        _METRICS['g6_option_spread_bps_mean'] = registry_guard.gauge('g6_option_spread_bps_mean', 'Mean bid-ask spread (basis points of mid) per bucket', ['mny', 'dte'], 25)
    return _METRICS['g6_option_spread_bps_mean']

def m_option_spread_bps_mean_labels(mny: str, dte: str):
    metric = m_option_spread_bps_mean()
    if not metric: return None
    if not registry_guard.track('g6_option_spread_bps_mean', (mny,dte,)): return None
    return _labels(metric, mny=mny, dte=dte)

def m_option_contracts_new_total():
    if 'g6_option_contracts_new_total' not in _METRICS:
        _METRICS['g6_option_contracts_new_total'] = registry_guard.counter('g6_option_contracts_new_total', 'Newly listed option contracts aggregated by DTE bucket', ['dte'], 5)
    return _METRICS['g6_option_contracts_new_total']

def m_option_contracts_new_total_labels(dte: str):
    metric = m_option_contracts_new_total()
    if not metric: return None
    if not registry_guard.track('g6_option_contracts_new_total', (dte,)): return None
    return _labels(metric, dte=dte)

def m_bus_events_published_total():
    if 'g6_bus_events_published_total' not in _METRICS:
        _METRICS['g6_bus_events_published_total'] = registry_guard.counter('g6_bus_events_published_total', 'Total events published to a named in-process bus', ['bus'], 5)
    return _METRICS['g6_bus_events_published_total']

def m_bus_events_published_total_labels(bus: str):
    metric = m_bus_events_published_total()
    if not metric: return None
    if not registry_guard.track('g6_bus_events_published_total', (bus,)): return None
    return _labels(metric, bus=bus)

def m_bus_events_dropped_total():
    if 'g6_bus_events_dropped_total' not in _METRICS:
        _METRICS['g6_bus_events_dropped_total'] = registry_guard.counter('g6_bus_events_dropped_total', 'Total events dropped (overflow or serialization) by bus', ['bus', 'reason'], 10)
    return _METRICS['g6_bus_events_dropped_total']

def m_bus_events_dropped_total_labels(bus: str, reason: str):
    metric = m_bus_events_dropped_total()
    if not metric: return None
    if not registry_guard.track('g6_bus_events_dropped_total', (bus,reason,)): return None
    return _labels(metric, bus=bus, reason=reason)

def m_bus_queue_retained_events():
    if 'g6_bus_queue_retained_events' not in _METRICS:
        _METRICS['g6_bus_queue_retained_events'] = registry_guard.gauge('g6_bus_queue_retained_events', 'Current retained event count in ring buffer per bus', ['bus'], 5)
    return _METRICS['g6_bus_queue_retained_events']

def m_bus_queue_retained_events_labels(bus: str):
    metric = m_bus_queue_retained_events()
    if not metric: return None
    if not registry_guard.track('g6_bus_queue_retained_events', (bus,)): return None
    return _labels(metric, bus=bus)

def m_bus_subscriber_lag_events():
    if 'g6_bus_subscriber_lag_events' not in _METRICS:
        _METRICS['g6_bus_subscriber_lag_events'] = registry_guard.gauge('g6_bus_subscriber_lag_events', 'Subscriber lag (events behind head) per bus & subscriber id', ['bus', 'subscriber'], 25)
    return _METRICS['g6_bus_subscriber_lag_events']

def m_bus_subscriber_lag_events_labels(bus: str, subscriber: str):
    metric = m_bus_subscriber_lag_events()
    if not metric: return None
    if not registry_guard.track('g6_bus_subscriber_lag_events', (bus,subscriber,)): return None
    return _labels(metric, bus=bus, subscriber=subscriber)

def m_bus_publish_latency_ms():
    if 'g6_bus_publish_latency_ms' not in _METRICS:
        _METRICS['g6_bus_publish_latency_ms'] = registry_guard.histogram('g6_bus_publish_latency_ms', 'Publish path latency per bus (milliseconds)', ['bus'], 5, buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50])
    return _METRICS['g6_bus_publish_latency_ms']

def m_bus_publish_latency_ms_labels(bus: str):
    metric = m_bus_publish_latency_ms()
    if not metric: return None
    if not registry_guard.track('g6_bus_publish_latency_ms', (bus,)): return None
    return _labels(metric, bus=bus)

def m_emission_failures_total():
    if 'g6_emission_failures_total' not in _METRICS:
        _METRICS['g6_emission_failures_total'] = registry_guard.counter('g6_emission_failures_total', 'Total emission wrapper failures (exception during metric emission) labeled by emitter signature', ['emitter'], 50)
    return _METRICS['g6_emission_failures_total']

def m_emission_failures_total_labels(emitter: str):
    metric = m_emission_failures_total()
    if not metric: return None
    if not registry_guard.track('g6_emission_failures_total', (emitter,)): return None
    return _labels(metric, emitter=emitter)

def m_emission_failure_once_total():
    if 'g6_emission_failure_once_total' not in _METRICS:
        _METRICS['g6_emission_failure_once_total'] = registry_guard.counter('g6_emission_failure_once_total', 'Unique emitters that have failed at least once (incremented once per emitter signature)', ['emitter'], 50)
    return _METRICS['g6_emission_failure_once_total']

def m_emission_failure_once_total_labels(emitter: str):
    metric = m_emission_failure_once_total()
    if not metric: return None
    if not registry_guard.track('g6_emission_failure_once_total', (emitter,)): return None
    return _labels(metric, emitter=emitter)

def m_metrics_batch_flush_duration_ms():
    if 'g6_metrics_batch_flush_duration_ms' not in _METRICS:
        _METRICS['g6_metrics_batch_flush_duration_ms'] = registry_guard.histogram('g6_metrics_batch_flush_duration_ms', 'Flush execution latency for emission batcher (milliseconds)', [], 1, buckets=[1, 2, 5, 10, 25, 50, 100, 250, 500, 1000])
    return _METRICS['g6_metrics_batch_flush_duration_ms']

def m_metrics_batch_flush_increments():
    if 'g6_metrics_batch_flush_increments' not in _METRICS:
        _METRICS['g6_metrics_batch_flush_increments'] = registry_guard.gauge('g6_metrics_batch_flush_increments', 'Number of distinct counter entries flushed in last batch', [], 1)
    return _METRICS['g6_metrics_batch_flush_increments']

def m_metrics_batch_adaptive_target():
    if 'g6_metrics_batch_adaptive_target' not in _METRICS:
        _METRICS['g6_metrics_batch_adaptive_target'] = registry_guard.gauge('g6_metrics_batch_adaptive_target', 'Current adaptive target batch size (distinct entries) computed by EWMA rate model', [], 1)
    return _METRICS['g6_metrics_batch_adaptive_target']

def m_cs_ingest_rows_total():
    if 'g6_cs_ingest_rows_total' not in _METRICS:
        _METRICS['g6_cs_ingest_rows_total'] = registry_guard.counter('g6_cs_ingest_rows_total', 'Rows successfully ingested into column store (post-batch commit)', ['table'], 10)
    return _METRICS['g6_cs_ingest_rows_total']

def m_cs_ingest_rows_total_labels(table: str):
    metric = m_cs_ingest_rows_total()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_rows_total', (table,)): return None
    return _labels(metric, table=table)

def m_cs_ingest_bytes_total():
    if 'g6_cs_ingest_bytes_total' not in _METRICS:
        _METRICS['g6_cs_ingest_bytes_total'] = registry_guard.counter('g6_cs_ingest_bytes_total', 'Uncompressed bytes ingested (pre-compression) per table', ['table'], 10)
    return _METRICS['g6_cs_ingest_bytes_total']

def m_cs_ingest_bytes_total_labels(table: str):
    metric = m_cs_ingest_bytes_total()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_bytes_total', (table,)): return None
    return _labels(metric, table=table)

def m_cs_ingest_latency_ms():
    if 'g6_cs_ingest_latency_ms' not in _METRICS:
        _METRICS['g6_cs_ingest_latency_ms'] = registry_guard.histogram('g6_cs_ingest_latency_ms', 'End-to-end ingest batch latency (ms) including serialization + network + commit', ['table'], 10, buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000])
    return _METRICS['g6_cs_ingest_latency_ms']

def m_cs_ingest_latency_ms_labels(table: str):
    metric = m_cs_ingest_latency_ms()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_latency_ms', (table,)): return None
    return _labels(metric, table=table)

def m_cs_ingest_failures_total():
    if 'g6_cs_ingest_failures_total' not in _METRICS:
        _METRICS['g6_cs_ingest_failures_total'] = registry_guard.counter('g6_cs_ingest_failures_total', 'Ingest failures (exceptions / rejected batches) per table', ['table', 'reason'], 30)
    return _METRICS['g6_cs_ingest_failures_total']

def m_cs_ingest_failures_total_labels(table: str, reason: str):
    metric = m_cs_ingest_failures_total()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_failures_total', (table,reason,)): return None
    return _labels(metric, table=table, reason=reason)

def m_cs_ingest_backlog_rows():
    if 'g6_cs_ingest_backlog_rows' not in _METRICS:
        _METRICS['g6_cs_ingest_backlog_rows'] = registry_guard.gauge('g6_cs_ingest_backlog_rows', 'Pending rows buffered for ingest per table', ['table'], 10)
    return _METRICS['g6_cs_ingest_backlog_rows']

def m_cs_ingest_backlog_rows_labels(table: str):
    metric = m_cs_ingest_backlog_rows()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_backlog_rows', (table,)): return None
    return _labels(metric, table=table)

def m_cs_ingest_backpressure_flag():
    if 'g6_cs_ingest_backpressure_flag' not in _METRICS:
        _METRICS['g6_cs_ingest_backpressure_flag'] = registry_guard.gauge('g6_cs_ingest_backpressure_flag', 'Backpressure active (1) when backlog exceeds threshold for table', ['table'], 10)
    return _METRICS['g6_cs_ingest_backpressure_flag']

def m_cs_ingest_backpressure_flag_labels(table: str):
    metric = m_cs_ingest_backpressure_flag()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_backpressure_flag', (table,)): return None
    return _labels(metric, table=table)

def m_cs_ingest_retries_total():
    if 'g6_cs_ingest_retries_total' not in _METRICS:
        _METRICS['g6_cs_ingest_retries_total'] = registry_guard.counter('g6_cs_ingest_retries_total', 'Retry attempts for failed batches per table', ['table'], 10)
    return _METRICS['g6_cs_ingest_retries_total']

def m_cs_ingest_retries_total_labels(table: str):
    metric = m_cs_ingest_retries_total()
    if not metric: return None
    if not registry_guard.track('g6_cs_ingest_retries_total', (table,)): return None
    return _labels(metric, table=table)

def m_stream_append_total():
    if 'g6_stream_append_total' not in _METRICS:
        _METRICS['g6_stream_append_total'] = registry_guard.counter('g6_stream_append_total', 'Indices stream append events (gated writes)', ['mode'], 5)
    return _METRICS['g6_stream_append_total']

def m_stream_append_total_labels(mode: str):
    metric = m_stream_append_total()
    if not metric: return None
    if not registry_guard.track('g6_stream_append_total', (mode,)): return None
    return _labels(metric, mode=mode)

def m_stream_skipped_total():
    if 'g6_stream_skipped_total' not in _METRICS:
        _METRICS['g6_stream_skipped_total'] = registry_guard.counter('g6_stream_skipped_total', 'Indices stream skipped events (same cycle/bucket or error)', ['mode', 'reason'], 15)
    return _METRICS['g6_stream_skipped_total']

def m_stream_skipped_total_labels(mode: str, reason: str):
    metric = m_stream_skipped_total()
    if not metric: return None
    if not registry_guard.track('g6_stream_skipped_total', (mode,reason,)): return None
    return _labels(metric, mode=mode, reason=reason)

def m_stream_state_persist_errors_total():
    if 'g6_stream_state_persist_errors_total' not in _METRICS:
        _METRICS['g6_stream_state_persist_errors_total'] = registry_guard.counter('g6_stream_state_persist_errors_total', 'Stream state persistence errors', [], 1)
    return _METRICS['g6_stream_state_persist_errors_total']

def m_stream_conflict_total():
    if 'g6_stream_conflict_total' not in _METRICS:
        _METRICS['g6_stream_conflict_total'] = registry_guard.counter('g6_stream_conflict_total', 'Detected potential concurrent indices_stream writer conflict', [], 1)
    return _METRICS['g6_stream_conflict_total']

def m_panel_diff_writes_total():
    if 'g6_panel_diff_writes_total' not in _METRICS:
        _METRICS['g6_panel_diff_writes_total'] = registry_guard.counter('g6_panel_diff_writes_total', 'Panel diff snapshots written', ['type'], 10)
    return _METRICS['g6_panel_diff_writes_total']

def m_panel_diff_writes_total_labels(type: str):
    metric = m_panel_diff_writes_total()
    if not metric: return None
    if not registry_guard.track('g6_panel_diff_writes_total', (type,)): return None
    return _labels(metric, type=type)

def m_panel_diff_truncated_total():
    if 'g6_panel_diff_truncated_total' not in _METRICS:
        _METRICS['g6_panel_diff_truncated_total'] = registry_guard.counter('g6_panel_diff_truncated_total', 'Panel diff truncation events', ['reason'], 10)
    return _METRICS['g6_panel_diff_truncated_total']

def m_panel_diff_truncated_total_labels(reason: str):
    metric = m_panel_diff_truncated_total()
    if not metric: return None
    if not registry_guard.track('g6_panel_diff_truncated_total', (reason,)): return None
    return _labels(metric, reason=reason)

def m_panel_diff_bytes_total():
    if 'g6_panel_diff_bytes_total' not in _METRICS:
        _METRICS['g6_panel_diff_bytes_total'] = registry_guard.counter('g6_panel_diff_bytes_total', 'Total bytes of diff JSON written', ['type'], 10)
    return _METRICS['g6_panel_diff_bytes_total']

def m_panel_diff_bytes_total_labels(type: str):
    metric = m_panel_diff_bytes_total()
    if not metric: return None
    if not registry_guard.track('g6_panel_diff_bytes_total', (type,)): return None
    return _labels(metric, type=type)

def m_panel_diff_bytes_last():
    if 'g6_panel_diff_bytes_last' not in _METRICS:
        _METRICS['g6_panel_diff_bytes_last'] = registry_guard.gauge('g6_panel_diff_bytes_last', 'Bytes of last diff JSON written', ['type'], 10)
    return _METRICS['g6_panel_diff_bytes_last']

def m_panel_diff_bytes_last_labels(type: str):
    metric = m_panel_diff_bytes_last()
    if not metric: return None
    if not registry_guard.track('g6_panel_diff_bytes_last', (type,)): return None
    return _labels(metric, type=type)

try:
    _hm = m_metrics_spec_hash_info()
    if _hm: _labels_set(_hm, 1, hash=SPEC_HASH)
except Exception: pass

try:
    import os
    _bhv = os.getenv('G6_BUILD_CONFIG_HASH', SPEC_HASH)
    _bh = m_build_config_hash_info()
    if _bh: _labels_set(_bh, 1, hash=_bhv)
except Exception: pass

# Export helper names and SPEC_HASH; avoid dynamic comprehensions that confuse some analyzers
__all__ = (
    [
        'SPEC_HASH',
        'm_api_calls_total','m_api_calls_total_labels','m_api_response_latency_ms','m_quote_enriched_total','m_quote_enriched_total_labels',
        'm_quote_missing_volume_oi_total','m_quote_missing_volume_oi_total_labels','m_quote_avg_price_fallback_total','m_quote_avg_price_fallback_total_labels',
        'm_index_zero_price_fallback_total','m_index_zero_price_fallback_total_labels','m_expiry_resolve_fail_total','m_expiry_resolve_fail_total_labels',
        'm_metrics_batch_queue_depth','m_cardinality_series_total','m_cardinality_series_total_labels','m_api_success_rate_percent','m_api_response_time_ms',
        'm_provider_mode','m_provider_mode_labels','m_provider_failover_total','m_metrics_spec_hash_info','m_metrics_spec_hash_info_labels',
        'm_build_config_hash_info','m_build_config_hash_info_labels','m_metric_duplicates_total','m_metric_duplicates_total_labels',
        'm_cardinality_guard_offenders_total','m_cardinality_guard_new_groups_total','m_cardinality_guard_last_run_epoch','m_cardinality_guard_allowed_growth_percent',
        'm_cardinality_guard_growth_percent','m_cardinality_guard_growth_percent_labels','m_option_contracts_active','m_option_contracts_active_labels',
        'm_option_open_interest','m_option_open_interest_labels','m_option_volume_24h','m_option_volume_24h_labels','m_option_iv_mean','m_option_iv_mean_labels',
        'm_option_spread_bps_mean','m_option_spread_bps_mean_labels','m_option_contracts_new_total','m_option_contracts_new_total_labels',
        'm_bus_events_published_total','m_bus_events_published_total_labels','m_bus_events_dropped_total','m_bus_events_dropped_total_labels',
        'm_bus_queue_retained_events','m_bus_queue_retained_events_labels','m_bus_subscriber_lag_events','m_bus_subscriber_lag_events_labels',
        'm_bus_publish_latency_ms','m_bus_publish_latency_ms_labels','m_emission_failures_total','m_emission_failures_total_labels',
        'm_emission_failure_once_total','m_emission_failure_once_total_labels','m_metrics_batch_flush_duration_ms','m_metrics_batch_flush_increments',
        'm_metrics_batch_adaptive_target','m_cs_ingest_rows_total','m_cs_ingest_rows_total_labels','m_cs_ingest_bytes_total','m_cs_ingest_bytes_total_labels',
        'm_cs_ingest_latency_ms','m_cs_ingest_latency_ms_labels','m_cs_ingest_failures_total','m_cs_ingest_failures_total_labels',
        'm_cs_ingest_backlog_rows','m_cs_ingest_backlog_rows_labels','m_cs_ingest_backpressure_flag','m_cs_ingest_backpressure_flag_labels',
        'm_cs_ingest_retries_total','m_cs_ingest_retries_total_labels','m_stream_append_total','m_stream_append_total_labels',
        'm_stream_skipped_total','m_stream_skipped_total_labels','m_stream_state_persist_errors_total','m_stream_conflict_total',
        'm_panel_diff_writes_total','m_panel_diff_writes_total_labels','m_panel_diff_truncated_total','m_panel_diff_truncated_total_labels',
        'm_panel_diff_bytes_total','m_panel_diff_bytes_total_labels','m_panel_diff_bytes_last','m_panel_diff_bytes_last_labels'
    ]
)
