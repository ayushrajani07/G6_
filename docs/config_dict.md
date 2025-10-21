# G6 Configuration Dictionary

_Last generated: 2025-09-26 (doc consolidation refresh 2025-10-03: added metrics facade modularization note & clarified schema governance)_

This document catalogs all known configuration options and relevant environment variable overrides for the G6 platform. It merges current (v2 style) configuration (`g6_config.json`) with legacy/compat files (`_config.json`, `_g6_config.json`) and runtime feature/env flags. Use this as the authoritative reference when introducing schema validation or deprecating legacy keys.

---
## Governance & Automation
Automated tests enforce documentation coverage for config keys:
- Test: `tests/test_config_doc_coverage.py` scans JSON configs (`config/*config*.json`) and code for string dict subscripts, building key paths.
- Baseline file: `tests/config_doc_baseline.txt` (must remain empty; historical backlog would have lived here).
- Flags: `G6_SKIP_CONFIG_DOC_VALIDATION=1` (skip), `G6_WRITE_CONFIG_DOC_BASELINE=1` (regenerate), `G6_CONFIG_DOC_STRICT=1` (fail if baseline not empty — used in CI).

Wildcard paths: Use a trailing `.*` to denote a documented subtree (e.g., `indices.*`). Any concrete key with that prefix counts as documented.

Principles:
1. Add documentation in the same PR as new config keys.
2. Prefer structured config keys over new environment variables for durable behavior.
3. Deprecate via a legacy row before removal; specify replacement and timeline.
4. Keep examples minimal but sufficient for type inference.

---
## 1. Version / Application Metadata
| Path | Key | Type | Default / Example | Description | Status |
|------|-----|------|-------------------|-------------|--------|
| `version` | `2.0` | string | `"2.0"` | Config format version (not semantic release version). | Active |
| `application` | – | string | `"G6 Options Trading Platform"` | Human readable name surfaced in banners. | Active |

---
## 2. Metrics Server
| Path | Key | Type | Default | Description | Env Override |
|------|-----|------|---------|-------------|--------------|
| `metrics.port` | – | int | `9108` | Prometheus exposition port. | – |
| `metrics.host` | – | string | `0.0.0.0` | Bind address. | – |
| `metrics.option_details_enabled` | – | bool | `false` | Explicit gating for per-option detailed metrics emission (schema key; may mirror env-based gating). | – |
| (legacy) `orchestration.prometheus_port` | – | int | `9108` | Legacy location of port before `metrics` block. | Legacy (prefer `metrics.port`) |
| `features.*` | subtree | * | Wildcard root: all feature flag keys covered when added. | Active |

---
## 3. Collection / Orchestration Timing
| Path | Key | Type | Default | Description | Env Override |
|------|-----|------|---------|-------------|--------------|
| `collection.interval_seconds` | – | int | `60` | Target wall clock between collection cycles. | – |
| (legacy) `orchestration.run_interval_sec` | – | int | `60` | Prior location for interval. | Legacy |
| (legacy) `orchestration.run_offset_sec` | – | int | `0` | Start offset alignment seconds. | Legacy |
| (legacy) `orchestration.market_start_time` | – | `HH:MM` string | `09:15` | Market open (used for gating in legacy paths). | Legacy |
| (legacy) `orchestration.market_end_time` | – | `HH:MM` string | `15:30` | Market close (legacy gating). | Legacy |
| `market_hours` | object | (derived / util) | – | Utility structure returned by market hours helpers (not persisted config key; documented for governance). | Internal |

---
## 4. Storage Configuration
| Path | Key | Type | Default / Example | Description | Env / Runtime Tie-ins |
|------|-----|------|-------------------|-------------|------------------------|
| `storage.csv_dir` | – | string (path) | `data/g6_data` | Root directory for per-option & overview CSV output. | Influences derived `data_subdir()` paths. |
| `storage.influx.enabled` | – | bool | `false` | Enable InfluxDB writes. | – |
| `storage.influx.url` | – | URL | `http://localhost:8086` | Influx endpoint. | – |
| `storage.influx.org` | – | string | `g6` | Influx organization. | – |
| `storage.influx.bucket` | – | string | `g6_data` | Target bucket/container. | – |
| (legacy) `storage.influx_enabled` | – | bool | `false` | Legacy enable flag (flattened). | Legacy |
| (legacy) `storage.influx_url` | – | string | – | Legacy URL key. | Legacy |
| (legacy) `storage.influx_org` | – | string | – | Legacy org key. | Legacy |
| (legacy) `storage.influx_bucket` | – | string | – | Legacy bucket key. | Legacy |
| (removed) `retention.*` | – | – | – | Retention worker removed; platform uses infinite retention (see `docs/RETENTION_POLICY.md`). | Removed |
| `storage.influx.*` | subtree | * | Wildcard: performance / retry / pool tuning keys (batch_size, flush_interval_seconds, max_queue_size, pool_min_size, pool_max_size, max_retries, backoff_base, breaker_failure_threshold, breaker_reset_timeout). | Active |
| `storage.parquet.enabled` | – | bool | `false` | Enable Parquet columnar sink (experimental; implementation gated). | – |
| `storage.parquet.dir` | – | path | – | Target directory for Parquet output (required if enabled). | – |
| `storage.*` | subtree | * | Wildcard root: existing and future storage subtree keys (csv_dir, influx.*, parquet.*) considered documented. | Active |

### 4.1 CSV Writer Tuning (Runtime via env, not persisted yet)
| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `G6_CSV_BUFFER_SIZE` | int | `0` | Buffer size (rows) before flush; `0` = immediate. |
| `G6_CSV_MAX_OPEN_FILES` | int | `64` | Soft cap on simultaneously open CSV file handles. |
| `G6_CSV_FLUSH_INTERVAL` | float seconds | `2.0` | Periodic flush cadence for buffered writer. |

---
## 5. Index Universe & Strike Depth
Two parallel styles exist:
1. Current style (`indices`) giving enable flags, fixed ITM/OTM strike depth, explicit expiry rule list.
2. Legacy style (`index_params`) containing `strike_step`, `expiry_rules`, `offsets` used to derive strike lists dynamically.

### 5.1 Current (`indices`)
| Path | Key | Type | Example | Description |
|------|-----|------|---------|-------------|
| `indices.<SYMBOL>.enable` | bool | `true` | Toggle index participation. |
| `indices.<SYMBOL>.strikes_itm` | int | `10` | Number of in-the-money strikes to include (per side). |
| `indices.<SYMBOL>.strikes_otm` | int | `10` | Number of out-of-the-money strikes to include. |
| `indices.<SYMBOL>.expiries` | list[str] | `["this_week","next_week",...]` | Expiry selection rules. |
| `indices.*` | subtree | * | Wildcard: any additional per-index config keys beneath `indices.` are considered documented when added (extend table if stable). |

### 5.2 Legacy (`index_params`)
| Path | Key | Type | Example | Description | Status |
|------|-----|------|---------|-------------|--------|
| `index_params.<SYMBOL>.strike_step` | int | `50` | Price increment granularity for strike generation. | Legacy |
| `index_params.<SYMBOL>.segment` | string | `NFO-OPT` | Trading segment identifier. | Legacy |
| `index_params.<SYMBOL>.exchange` | string | `NSE` | Exchange code. | Legacy |
| `index_params.<SYMBOL>.expiry_rules` | list[str] | Similar to current | Expiry rule names. | Legacy |
| `index_params.<SYMBOL>.offsets` | list[int] | `[-10,-5,...,10]` | Relative strike offsets from ATM used to derive strike list. | Legacy |

### 5.3 Planned Adaptive Scaling (Not Yet Implemented)
Future configuration will likely introduce `indices_defaults` + adaptive scaling thresholds (see roadmap section 4.2 & 8) – not present today.

---
## 6. Providers
| Path | Key | Type | Example | Description | Status |
|------|-----|------|---------|-------------|--------|
| `providers.primary.type` | string | `dummy` | Selects provider implementation (e.g., `dummy`, `kite`, etc.). | Active (only in dummy config) |
| (legacy) `kite.instrument_cache_path` | path | `.cache/kite_instruments.json` | Cache file for instrument master. | Legacy (kite-specific) |
| (legacy) `kite.instrument_ttl_hours` | int | `6` | TTL for instrument cache refresh. | Legacy |
| (legacy) `kite.rate_limit_per_sec` | float | `5.0` | Soft desired rate limit (internal throttling). | Legacy |
| (legacy) `kite.max_retries` | int | `5` | Retry attempts on transient failures. | Legacy |
| (legacy) `kite.http_timeout` | int | `10` | HTTP timeout seconds. | Legacy |
| (legacy) `kite.default_exchanges` | list[str] | `["NSE","NFO","BSE","BFO"]` | Universe of exchanges for symbol search. | Legacy |
| `providers.*` | subtree | * | Wildcard: additional provider-specific tuned keys (rate limits, auth, etc.) considered covered; document explicitly when stable. | Active |

---
## 7. Feature Flags (Config File)
| Path | Key | Type | Default | Description |
|------|-----|------|---------|-------------|
| `features.analytics_startup` | bool | `true` | Run analytics (Greek/IV or enrichment) early in lifecycle. |

---
## 8. Console / UI Block
| Path | Key | Type | Default | Description | Env Interaction |
|------|-----|------|---------|-------------|-----------------|
| `console.fancy_startup` | bool | `true` | Enable richer banner output. | `G6_FANCY_CONSOLE` (bool) fallback path |
| `console.live_panel` | bool | `true` | Enable live panel rendering (stdout). | `G6_LIVE_PANEL` (can override) |
| `console.startup_banner` | bool | `true` | Display startup informational banner. | – |
| `console.force_ascii` | bool | `true` | Force ASCII rendering for panel characters. | `G6_FORCE_UNICODE` (inverse logic; if set truthy disables fallback) |
| `console.runtime_status_file` | string | `data/runtime_status.json` | Target path for runtime JSON snapshot. | – |
| `console.*` | subtree | * | Wildcard: new console presentation keys may appear; add explicit rows if permanent. | Active |

---
## 9. Environment Variable Feature / Behavior Flags (Non-persisted)
| Env Var | Type | Default | Purpose |
|---------|------|---------|---------|
| `G6_USE_MOCK_PROVIDER` | bool | off | Force mock/dummy provider regardless of config. |
| `G6_FORCE_UNICODE` | bool | off | Force enabling of unicode output (disables ascii fallback). |
| `G6_FANCY_CONSOLE` | bool | off | Force fancy console mode even if config absent. |
| `G6_LIVE_PANEL` | bool | off | Force enable/disable live panel independent of config. |
| `G6_MAX_CYCLES` | int | 0 (unbounded) | Hard stop after N cycles (dev/testing). |
| `G6_HEALTH_COMPONENTS` | bool | off | Enable verbose component health panel sections. |
| `G6_ENABLE_PANEL_PUBLISH` | bool | off | Enable writing panel JSON files to panels dir. |
| `G6_PANELS_DIR` | path | `data/panels` | Directory for panel JSON output. |
| `G6_OUTPUT_SINKS` | csv string | `stdout,logging` | Output sinks list (e.g., add `panels`). |
| `G6_PUBLISHER_EMIT_INDICES_STREAM` | bool | off | Emit streaming indices updates (publisher). |
| `G6_COLOR` | string (`auto`,`always`,`never`) | `auto` | Color handling for enhanced UI. |
| `G6_ADAPTIVE_CB_PROVIDERS` | bool | off | Enable adaptive circuit breaker mode for providers. |
| `G6_RETRY_PROVIDERS` | bool | off | Enable wrapping provider calls with retry logic. |
| `G6_METRICS_CARD_ENABLED` | bool | off | Enable cardinality gating of per-option metrics. |
| `G6_METRICS_CARD_ATM_WINDOW` | int | 0 | +/- strike window around ATM to allow when gating. |
| `G6_METRICS_CARD_RATE_LIMIT_PER_SEC` | int | 0 | Global per-option metrics emission rate cap. |
| `G6_METRICS_CARD_CHANGE_THRESHOLD` | float | 0.0 | Absolute option price change required to re-emit. |

---
## 10. Deprecated / Legacy Grouping Summary
| Legacy Group | Replacement | Notes |
|--------------|------------|-------|
| `orchestration.*` | `collection` + `metrics` + env | Split into more explicit sections. |
| `index_params` | `indices` | New model favors simple ITM/OTM counts over offset arrays. |
| `kite.*` | `providers.*` | Provider abstraction pending; kite-specific keys will move under typed provider config. |
| Flattened `storage.influx_*` | `storage.influx.{enabled,url,org,bucket}` | Normalized shape. |
| (legacy) `orchestration.*` extra keys (`redis_enabled`, `redis_host`, `redis_port`, `log_level`) | pending removal | Transitional detection only; not part of v2 schema. |
| (Removed now-invalid) deprecated disallowed keys | n/a | Hardened schema now hard-fails on previously deprecated keys instead of warning. |

---
## 11. Pending / Planned Additions (Not Present Yet)
| Proposed Key | Rationale |
|--------------|-----------|
| `config.schema_version` | Schema evolution & validation. |
| `resilience.providers.circuit.mode` | Consolidate circuit breaker strategy selection. |
| `adaptive.scaling.*` | Control strike depth auto-scaling thresholds. |
| `storage.parquet.*` | Columnar output (enabled + dir) for analytics & compression (wildcard doc coverage). |
| `_legacy.*` | Container for acknowledged legacy keys (if retained). |

---
## 12. Change Management Guidance
1. Enforce JSON Schema (`config/schema_v2.json`) validation at load. Unknown or deprecated/disallowed keys now cause immediate failure (hard-fail policy) rather than soft warnings.
2. Optional normalized merged config emission (`logs/normalized_config.json`) when `G6_CONFIG_EMIT_NORMALIZED=1` (post-validation sanitized view for diffing / audits).
3. `g6_config_deprecated_keys_total{key}` metric reserved for future soft deprecation phases; currently no deprecated keys are allowed past schema so this counter will not increment.
4. Provide migration doc updates in `MIGRATION.md` when introducing a soft-deprecation window before removal (if reintroducing transitional acceptance).
5. `G6_CONFIG_LEGACY_SOFT=1`: Accepts (and strips) deprecated keys while incrementing the counter to measure remaining usage.
 6. Metrics Facade Modularization: as of 2025-10 Phase 3.x the legacy monolith `metrics/metrics.py` is being decomposed (see `README.md` Section 3.1). Config references SHOULD avoid deep imports; no config keys are required for modularization (purely internal), but any future `metrics.*` subtree keys MUST appear in this file concurrently with code.
 7. Duplication Policy: Do not duplicate config key definitions in ancillary markdown (e.g. `README.md`) beyond high-level summaries; this file remains authoritative for key path documentation.

---
## 13. Quick Reference (Most Common Runtime Knobs)
| Purpose | Preferred Control |
|---------|-------------------|
| Adjust cycle interval | `collection.interval_seconds` |
| Enable panel publishing | `G6_ENABLE_PANEL_PUBLISH=1` + ensure `G6_PANELS_DIR` |
| Limit per-option metric explosion | `G6_METRICS_CARD_ENABLED=1` + gating env values |
| Use mock data in dev | `--mock-data` CLI or `G6_USE_MOCK_PROVIDER=1` |
| Cap cycles for test | `G6_MAX_CYCLES=N` |
| Enable retries | `G6_RETRY_PROVIDERS=1` |
| Enable adaptive CB | `G6_ADAPTIVE_CB_PROVIDERS=1` |

---
_This file is manually curated (no generator yet). Update on every schema evolution, new env flag (`G6_CONFIG_*`), or deprecation policy change._
\n---\n## 14. Overlays Subsystem (Weekday)
| Path | Key | Type | Example | Description | Status |
|------|-----|------|---------|-------------|--------|
| `overlays.weekday.alpha` | float | `0.5` | Example smoothing / blending parameter (visual overlay weighting). | Active |
| `overlays.weekday.output_dir` | path | `data/weekday_master` | Output directory for generated weekday overlays. | Active |
| `overlays.*` | subtree | * | Wildcard for future overlay families (e.g., seasonality). | Active |

## 15. Preventive Validation (Batch Sanity) (Config-style Inline Dict Usage)
These keys appear in internal preventive validation configuration merges (not yet persisted in primary JSON schema but treated as tunable parameters).
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_strike_deviation_pct` | float | `40.0` | Reject strikes outside ±pct of ATM. |
| `min_required_strikes` | int | `10` | Minimum unique strikes required to accept batch. |
| `max_zero_volume_ratio` | float | `0.90` | Threshold ratio of zero-volume strikes flagging anomaly. |
| `reject_future_year` | int | `2050` | Upper bound year guard for expiries. |
| `preventive_validation.*` | subtree | * | Placeholder wildcard if promoted to namespaced config later. |

---
## 16. Greeks and IV Estimation
The Greeks/IV computation module is controlled via the `greeks` section in the config. Documented keys below; use conservative defaults in production.

- Root (wildcard coverage): `greeks.*`

| Path | Type | Default | Description |
|------|------|---------|-------------|
| `greeks.enabled` | bool | `false` | Toggle analytics to compute option Greeks/IV. |
| `greeks.estimate_iv` | bool | `false` | Enable IV estimation (e.g., via root-finding) when direct IV not available. |
| `greeks.risk_free_rate` | number | `0.05` | Annualized risk-free rate used in models (e.g., Black-Scholes). |
| `greeks.iv_max_iterations` | integer | `100` | Maximum iterations for IV solver. |
| `greeks.iv_min` | number | `0.01` | Lower bound for IV search. |
| `greeks.iv_max` | number | `5.0` | Upper bound for IV search. |
| `greeks.iv_precision` | number | `1e-5` | Target absolute precision for IV solver. |
