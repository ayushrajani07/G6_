# G6 Environment Variables
This document is auto-generated from the Environment Registry.

| Variable | Type | Required | Default | Description | Choices | Notes |
|---|---|:---:|---|---|---|---|
| G6_ADAPTIVE_CB_INFLUX | boolean | N | False | Wrap Influx writes with adaptive circuit breaker |  |  |
| G6_ADAPTIVE_CB_PROVIDERS | boolean | N | False | Wrap providers with adaptive circuit breakers |  |  |
| G6_ALERTS | boolean | N | False | Enable alerts subsystem |  |  |
| G6_ALERTS_FLAT_COMPAT | boolean | N | True | Export legacy flat alert_* fields alongside nested alerts block |  |  |
| G6_ALERTS_STATE_DIR | string | N |  | Alerts state directory |  |  |
| G6_ALERT_FIELD_COV_MIN | float | N | 0.5 | Minimum field coverage ratio for low_field_coverage alert |  | range: 0.0..1.0 |
| G6_ALERT_LIQUIDITY_MIN_RATIO | float | N | 0.05 | Min avg volume per option ratio to avoid liquidity_low alert |  | range: 0.0..10.0 |
| G6_ALERT_QUOTE_STALE_AGE_S | float | N | 45.0 | Age in seconds beyond which quotes considered stale |  | range: 1.0..3600.0 |
| G6_ALERT_STRIKE_COV_MIN | float | N | 0.6 | Minimum strike coverage ratio for low_strike_coverage alert |  | range: 0.0..1.0 |
| G6_ALERT_TAXONOMY_EXTENDED | boolean | N | False | Enable extended alert taxonomy categories (liquidity_low, stale_quote, wide_spread) |  |  |
| G6_ALERT_WIDE_SPREAD_PCT | float | N | 5.0 | Spread percentage threshold for wide_spread alert |  | range: 0.1..100.0 |
| G6_CB_BACKOFF | float | N | 2.0 | Adaptive CB backoff factor |  | range: 1.0..10.0 |
| G6_CB_FAILURES | integer | N | 5 | Adaptive CB failure threshold |  | range: 1..1000 |
| G6_CB_HALF_OPEN_SUCC | integer | N | 1 | Adaptive CB required successes in HALF_OPEN |  | range: 1..100 |
| G6_CB_JITTER | float | N | 0.2 | Adaptive CB jitter (0..1) |  | range: 0.0..1.0 |
| G6_CB_MAX_RESET | float | N | 300.0 | Adaptive CB max reset timeout (s) |  | range: 1.0..86400.0 |
| G6_CB_MIN_RESET | float | N | 10.0 | Adaptive CB min reset timeout (s) |  | range: 0.1..3600.0 |
| G6_CB_STATE_DIR | string | N |  | Adaptive CB persistence directory |  |  |
| G6_CIRCUIT_METRICS | boolean | N | False | Enable circuit metrics exporter |  |  |
| G6_CIRCUIT_METRICS_INTERVAL | float | N |  | Circuit metrics export interval (seconds) |  | range: 1.0..3600.0 |
| G6_COLLECTION_INTERVAL | integer | N |  | Collection interval (seconds) |  | range: 1..3600 |
| G6_DISABLE_STRIKE_CACHE | boolean | N | False | Disable strike universe cache layer |  |  |
| G6_ENRICH_ASYNC | boolean | N | False | Enable async enrichment path |  |  |
| G6_ENRICH_ASYNC_BATCH | integer | N | 50 | Async enrichment batch size |  | range: 1..5000 |
| G6_ENRICH_ASYNC_TIMEOUT_MS | integer | N | 3000 | Timeout (ms) for async enrichment batch completion before fallback |  | range: 100..60000 |
| G6_ENRICH_ASYNC_WORKERS | integer | N | 4 | Max worker threads for async enrichment |  | range: 1..128 |
| G6_FEATURES_ANALYTICS_STARTUP | boolean | N | False | Analytics at startup |  |  |
| G6_FEATURES_FANCY_STARTUP | boolean | N | False | Fancy startup banner |  |  |
| G6_FEATURES_LIVE_PANEL | boolean | N | False | Console live panel |  |  |
| G6_HEALTH_API_ENABLED | boolean | N | False | Enable health API |  |  |
| G6_HEALTH_API_HOST | string | N |  | Health API bind host |  | pattern: `^\S+$` |
| G6_HEALTH_API_PORT | integer | N |  | Health API port |  | range: 1024..65535 |
| G6_HEALTH_COMPONENTS | boolean | N | False | Enable per-component health updates |  |  |
| G6_HEALTH_PROMETHEUS | boolean | N | False | Enable health metrics exporter |  |  |
| G6_METRICS_ENABLED | boolean | N | True | Enable metrics |  |  |
| G6_METRICS_PORT | integer | N |  | Metrics port |  | range: 1024..65535 |
| G6_PANELS_DIR | string | N |  | Panels directory for bridge |  |  |
| G6_PARITY_FLOAT_ATOL | float | N | 1e-09 | Absolute tolerance for float parity diffs |  | range: 0.0..1.0 |
| G6_PARITY_FLOAT_RTOL | float | N | 1e-06 | Relative tolerance for float parity diffs |  | range: 0.0..1.0 |
| G6_PIPELINE_INCLUDE_DIAGNOSTICS | boolean | N | False | Include diagnostics block (latency & provider stats) in pipeline result |  |  |
| G6_PIPELINE_ROLLOUT | string | N | legacy | Pipeline rollout mode (legacy | shadow | primary) | legacy, shadow, primary |  |
| G6_RETRY_BACKOFF | float | N | 0.2 | Retry base backoff (s) |  | range: 0.01..60.0 |
| G6_RETRY_BLACKLIST | string | N |  | Retry exception blacklist (CSV of class names) |  |  |
| G6_RETRY_JITTER | boolean | N | True | Retry add jitter |  |  |
| G6_RETRY_MAX_ATTEMPTS | integer | N | 3 | Retry max attempts |  | range: 1..100 |
| G6_RETRY_MAX_SECONDS | float | N | 8.0 | Retry overall time cap (s) |  | range: 0.1..3600.0 |
| G6_RETRY_PROVIDERS | boolean | N | False | Compose standardized retries around provider calls |  |  |
| G6_RETRY_WHITELIST | string | N |  | Retry exception whitelist (CSV of class names) |  |  |
| G6_STORAGE_CSV_DIR | string | N |  | CSV data directory |  |  |
| G6_STORAGE_INFLUX_BUCKET | string | N |  | Influx bucket |  |  |
| G6_STORAGE_INFLUX_ENABLED | boolean | N | False | Enable InfluxDB |  |  |
| G6_STORAGE_INFLUX_ORG | string | N |  | Influx org |  |  |
| G6_STORAGE_INFLUX_URL | string | N |  | Influx URL |  |  |
| G6_STRIKE_POLICY | string | N | fixed | Strike policy mode (fixed | adaptive_v2) | fixed, adaptive_v2 |  |
| G6_STRIKE_POLICY_COOLDOWN | integer | N | 2 | Min cycles between adaptive strike adjustments |  | range: 1..1000 |
| G6_STRIKE_POLICY_MAX_ITM | integer | N |  | Max allowed ITM strikes span for adaptive policy (baseline + N) |  | range: 0..10000 |
| G6_STRIKE_POLICY_MAX_OTM | integer | N |  | Max allowed OTM strikes span for adaptive policy (baseline + N) |  | range: 0..10000 |
| G6_STRIKE_POLICY_STEP | integer | N | 2 | Adaptive strike policy step increment for widening/narrowing |  | range: 1..100 |
| G6_STRIKE_POLICY_TARGET | float | N | 0.85 | Adaptive strike policy target coverage ratio |  | range: 0.1..1.0 |
| G6_STRIKE_POLICY_WINDOW | integer | N | 5 | Window size (cycles) for recent coverage computation |  | range: 1..1000 |
| G6_STRIKE_UNIVERSE_CACHE_SIZE | integer | N | 256 | LRU capacity for strike universe cache (entries) |  | range: 0..100000 |
| G6_SUMMARY_PANELS_MODE | string | N |  | Summary panels mode toggle | on, off |  |
