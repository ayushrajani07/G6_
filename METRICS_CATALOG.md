# Metrics Catalog

Generated: 2025-10-05T12:27:46Z


## Family: provider
Owner: collectors/providers_interface.py

### g6_api_calls_total
Type: counter  
Help: Provider API calls  
Labels: endpoint, result  
Cardinality Budget: 50

### g6_api_response_latency_ms
Type: histogram  
Help: Upstream API response latency (ms)  
Labels: (none)  
Cardinality Budget: 1

### g6_quote_enriched_total
Type: counter  
Help: Quotes enriched  
Labels: provider  
Cardinality Budget: 5

### g6_quote_missing_volume_oi_total
Type: counter  
Help: Enriched quotes missing volume & oi  
Labels: provider  
Cardinality Budget: 5

### g6_quote_avg_price_fallback_total
Type: counter  
Help: Avg price fallback usage  
Labels: provider  
Cardinality Budget: 5

### g6_index_zero_price_fallback_total
Type: counter  
Help: Index zero price synthetic fallback applied  
Labels: index, path  
Cardinality Budget: 30

### g6_expiry_resolve_fail_total
Type: counter  
Help: Expiry resolution failures  
Labels: index, rule, reason  
Cardinality Budget: 120

### g6_metrics_batch_queue_depth
Type: gauge  
Help: Current queued batched counter increments awaiting flush  
Labels: (none)  
Cardinality Budget: 1

### g6_cardinality_series_total
Type: gauge  
Help: Observed unique label sets registered per metric name  
Labels: metric  
Cardinality Budget: 200

## Family: system
Owner: metrics/api_call.py

### g6_api_success_rate_percent
Type: gauge  
Help: Successful API call percentage (rolling window)  
Labels: (none)  
Cardinality Budget: 1

### g6_api_response_time_ms
Type: gauge  
Help: Average upstream API response time (ms, rolling)  
Labels: (none)  
Cardinality Budget: 1

## Family: provider_mode
Owner: metrics/provider_failover.py

### g6_provider_mode
Type: gauge  
Help: Active provider mode (one-hot by mode label)  
Labels: mode  
Cardinality Budget: 6

### g6_provider_failover_total
Type: counter  
Help: Provider failovers  
Labels: (none)  
Cardinality Budget: 1

## Family: governance
Owner: metrics/spec_hash

### g6_metrics_spec_hash_info
Type: gauge  
Help: Static gauge labeled with current metrics spec content hash (value always 1)  
Labels: hash  
Cardinality Budget: 1

### g6_build_config_hash_info
Type: gauge  
Help: Static gauge labeled with current build/config content hash (value always 1)  
Labels: hash  
Cardinality Budget: 1

### g6_metric_duplicates_total
Type: counter  
Help: Count of duplicate metric registration attempts (same metric name registered more than once)  
Labels: name  
Cardinality Budget: 50

### g6_cardinality_guard_offenders_total
Type: gauge  
Help: Number of offending metric groups exceeding allowed growth threshold during last cardinality guard evaluation  
Labels: (none)  
Cardinality Budget: 1

### g6_cardinality_guard_new_groups_total
Type: gauge  
Help: Number of entirely new metric groups discovered relative to baseline during last guard evaluation  
Labels: (none)  
Cardinality Budget: 1

### g6_cardinality_guard_last_run_epoch
Type: gauge  
Help: Unix epoch seconds timestamp of last successful cardinality guard evaluation  
Labels: (none)  
Cardinality Budget: 1

### g6_cardinality_guard_allowed_growth_percent
Type: gauge  
Help: Allowed growth threshold percent configured for cardinality guard at last evaluation  
Labels: (none)  
Cardinality Budget: 1

### g6_cardinality_guard_growth_percent
Type: gauge  
Help: Observed growth percent for a metric group exceeding baseline (labels: group)  
Labels: group  
Cardinality Budget: 100

## Family: option_chain
Owner: metrics/option_chain_aggregator.py

### g6_option_contracts_active
Type: gauge  
Help: Active option contracts per moneyness & DTE bucket (snapshot)  
Labels: mny, dte  
Cardinality Budget: 25

### g6_option_open_interest
Type: gauge  
Help: Aggregated open interest per bucket  
Labels: mny, dte  
Cardinality Budget: 25

### g6_option_volume_24h
Type: gauge  
Help: 24h traded volume aggregated per bucket  
Labels: mny, dte  
Cardinality Budget: 25

### g6_option_iv_mean
Type: gauge  
Help: Mean implied volatility annualized per bucket  
Labels: mny, dte  
Cardinality Budget: 25

### g6_option_spread_bps_mean
Type: gauge  
Help: Mean bid-ask spread (basis points of mid) per bucket  
Labels: mny, dte  
Cardinality Budget: 25

### g6_option_contracts_new_total
Type: counter  
Help: Newly listed option contracts aggregated by DTE bucket  
Labels: dte  
Cardinality Budget: 5

## Family: bus
Owner: bus/in_memory_bus.py

### g6_bus_events_published_total
Type: counter  
Help: Total events published to a named in-process bus  
Labels: bus  
Cardinality Budget: 5

### g6_bus_events_dropped_total
Type: counter  
Help: Total events dropped (overflow or serialization) by bus  
Labels: bus, reason  
Cardinality Budget: 10

### g6_bus_queue_retained_events
Type: gauge  
Help: Current retained event count in ring buffer per bus  
Labels: bus  
Cardinality Budget: 5

### g6_bus_subscriber_lag_events
Type: gauge  
Help: Subscriber lag (events behind head) per bus & subscriber id  
Labels: bus, subscriber  
Cardinality Budget: 25

### g6_bus_publish_latency_ms
Type: histogram  
Help: Publish path latency per bus (milliseconds)  
Labels: bus  
Cardinality Budget: 5

## Family: emission
Owner: metrics/safe_emit.py

### g6_emission_failures_total
Type: counter  
Help: Total emission wrapper failures (exception during metric emission) labeled by emitter signature  
Labels: emitter  
Cardinality Budget: 50

### g6_emission_failure_once_total
Type: counter  
Help: Unique emitters that have failed at least once (incremented once per emitter signature)  
Labels: emitter  
Cardinality Budget: 50

### g6_metrics_batch_flush_duration_ms
Type: histogram  
Help: Flush execution latency for emission batcher (milliseconds)  
Labels: (none)  
Cardinality Budget: 1

### g6_metrics_batch_flush_increments
Type: gauge  
Help: Number of distinct counter entries flushed in last batch  
Labels: (none)  
Cardinality Budget: 1

### g6_metrics_batch_adaptive_target
Type: gauge  
Help: Current adaptive target batch size (distinct entries) computed by EWMA rate model  
Labels: (none)  
Cardinality Budget: 1

## Family: column_store
Owner: storage/column_store_pipeline.py

### g6_cs_ingest_rows_total
Type: counter  
Help: Rows successfully ingested into column store (post-batch commit)  
Labels: table  
Cardinality Budget: 10

### g6_cs_ingest_bytes_total
Type: counter  
Help: Uncompressed bytes ingested (pre-compression) per table  
Labels: table  
Cardinality Budget: 10

### g6_cs_ingest_latency_ms
Type: histogram  
Help: End-to-end ingest batch latency (ms) including serialization + network + commit  
Labels: table  
Cardinality Budget: 10

### g6_cs_ingest_failures_total
Type: counter  
Help: Ingest failures (exceptions / rejected batches) per table  
Labels: table, reason  
Cardinality Budget: 30

### g6_cs_ingest_backlog_rows
Type: gauge  
Help: Pending rows buffered for ingest per table  
Labels: table  
Cardinality Budget: 10

### g6_cs_ingest_backpressure_flag
Type: gauge  
Help: Backpressure active (1) when backlog exceeds threshold for table  
Labels: table  
Cardinality Budget: 10

### g6_cs_ingest_retries_total
Type: counter  
Help: Retry attempts for failed batches per table  
Labels: table  
Cardinality Budget: 10

## Family: stream
Owner: scripts/summary/plugins/stream_gater.py

### g6_stream_append_total
Type: counter  
Help: Indices stream append events (gated writes)  
Labels: mode  
Cardinality Budget: 5

### g6_stream_skipped_total
Type: counter  
Help: Indices stream skipped events (same cycle/bucket or error)  
Labels: mode, reason  
Cardinality Budget: 15

### g6_stream_state_persist_errors_total
Type: counter  
Help: Stream state persistence errors  
Labels: (none)  
Cardinality Budget: 1

### g6_stream_conflict_total
Type: counter  
Help: Detected potential concurrent indices_stream writer conflict  
Labels: (none)  
Cardinality Budget: 1

## Family: panels
Owner: web/dashboard/panel_diff.py

### g6_panel_diff_writes_total
Type: counter  
Help: Panel diff snapshots written  
Labels: type  
Cardinality Budget: 10

### g6_panel_diff_truncated_total
Type: counter  
Help: Panel diff truncation events  
Labels: reason  
Cardinality Budget: 10

### g6_panel_diff_bytes_total
Type: counter  
Help: Total bytes of diff JSON written  
Labels: type  
Cardinality Budget: 10

### g6_panel_diff_bytes_last
Type: gauge  
Help: Bytes of last diff JSON written  
Labels: type  
Cardinality Budget: 10

