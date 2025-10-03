# G6 Environment Variables
This document is auto-generated from the Environment Registry.

| Variable | Type | Required | Default | Description | Choices | Notes |
|---|---|:---:|---|---|---|---|
| G6_ADAPTIVE_CB_INFLUX | boolean | N | False | Wrap Influx writes with adaptive circuit breaker |  |  |
| G6_ADAPTIVE_CB_PROVIDERS | boolean | N | False | Wrap providers with adaptive circuit breakers |  |  |
| G6_ALERTS | boolean | N | False | Enable alerts subsystem |  |  |
| G6_ALERTS_STATE_DIR | string | N |  | Alerts state directory |  |  |
| G6_ALERT_LIQUIDITY_MIN_RATIO | float | N | 0.05 | Min avg volume per option ratio to avoid liquidity_low alert |  | range: 0.0..10.0 |
| G6_ALERT_QUOTE_STALE_AGE_S | float | N | 45.0 | Age in seconds beyond which quotes considered stale |  | range: 1.0..3600.0 |
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
| G6_PIPELINE_INCLUDE_DIAGNOSTICS | boolean | N | False | Include diagnostics block (latency & provider stats) in pipeline result |  |  |
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
| (Removed 2025-10) G6_SUMMARY_PANELS_MODE | string | N |  | Former summary panels mode toggle (on/off). Removed – panels mode now auto-detected via panels dir presence. Remove from environments. |  |  |
