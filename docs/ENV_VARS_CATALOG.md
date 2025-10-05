# G6 Environment Variables Catalog

Generated: 2025-10-02T08:38:16.522463Z
Source of truth: docs/env_dict.md (this table is derived, do not edit manually).

Total documented: 461  | Referenced in code: 597  | Undocumented: 112

Name | Type | Default | Referenced | Description
--- | --- | --- | --- | ---
G6_ADAPTIVE_ALERT_COLOR_CRITICAL | str | (unset) | Y | Color override for CRITICAL severity.
G6_ADAPTIVE_ALERT_COLOR_INFO | str | (unset) | Y | ANSI or hex color override for INFO severity rendering in dashboards / terminal (format accepted by theming layer).
G6_ADAPTIVE_ALERT_COLOR_WARN | str | (unset) | Y | Color override for WARN severity.
G6_ADAPTIVE_ALERT_SEVERITY | bool | off | Y | Master enable for adaptive alert severity state machine (enriches alerts with WARN/CRITICAL levels and drives severity…
G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES | int | 0 | Y | Cycles of sustained below-warn condition required before a WARN/CRITICAL severity decays one level (0 uses default deca…
G6_ADAPTIVE_ALERT_SEVERITY_FORCE | enum(info|warn|critical) | (unset) | Y | Force floor severity for all adaptive alerts (diagnostics / demo). Overrides decay (cannot demote below forced level).
G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK | int | 0 | Y | Minimum consecutive triggers before initial severity escalation beyond INFO (guards against noisy single-cycle spikes).
G6_ADAPTIVE_ALERT_SEVERITY_RULES | JSON | (unset) | Y | JSON object mapping alert types → {warn:float,critical:float} threshold overrides. Example: {"interpolation_high":{"war…
G6_ADAPTIVE_CB_INFLUX | bool | off | Y | Adaptive circuit breaker on Influx writes.
G6_ADAPTIVE_CB_PROVIDERS | bool | off | Y | Adaptive circuit breaker wraps provider methods.
G6_ADAPTIVE_CONTROLLER | bool | off | Y | Master enable for adaptive controller (memory/strike/detail mode adjustments). When off, all controller-driven adjustme…
G6_ADAPTIVE_CONTROLLER_ACTIONS_DEBUG | bool | (planned) | Y | Proposed future verbose controller action logging (currently unused allowlist placeholder).
G6_ADAPTIVE_CONTROLLER_SEVERITY | bool | off | Y | Enable using adaptive alert severity state as an input signal to controller decisions (promotion/demotion gating).
G6_ADAPTIVE_DEMOTE_COOLDOWN | int | 0 | Y | Minimum cycles between severity demotions to prevent flip-flopping in borderline conditions.
G6_ADAPTIVE_MAX_DETAIL_MODE | int | 0 | Y | Maximum adaptive detail mode level the runtime can escalate to (0 uses internal cap). Limits granularity of diagnostic…
G6_ADAPTIVE_MAX_SLA_BREACH_STREAK | int | 0 | Y | Hard cap preventing unbounded streak growth for SLA breach driven severity logic.
G6_ADAPTIVE_MIN_DETAIL_MODE | int | 0 | Y | Minimum floor for adaptive detail mode (prevents full de-escalation when partial verbosity desired).
G6_ADAPTIVE_MIN_HEALTH_CYCLES | int | 0 | Y | Minimum healthy baseline cycles required before enabling certain trend/severity escalations (warm-up guard).
G6_ADAPTIVE_PROMOTE_COOLDOWN | int | 0 | Y | Minimum cycles between severity promotions (throttles rapid escalations during volatile conditions).
G6_ADAPTIVE_RECOVERY_CYCLES | int | 0 | Y | Consecutive healthy cycles before resetting historical streak state (streak counters/rolling windows cleared).
G6_ADAPTIVE_SCALE_PASSTHROUGH | bool | off | Y | When on, scaling calculations run but do not alter strike depth (emit diagnostic path only).
G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES | csv | (unset) | Y | Comma list of alert types allowed to demote directly from CRITICAL to lower levels bypassing WARN when recovery is stro…
G6_ADAPTIVE_SEVERITY_STATE_DEBUG | bool | off | Y | Emit verbose internal state transitions for severity controller (high volume; diagnostics only).
G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO | float | 0.0 | Y | Ratio-based trend trigger for automatic critical escalation (e.g., slope or drift ratio). 0 => disabled.
G6_ADAPTIVE_SEVERITY_TREND_SMOOTH | float | 0.0 | Y | Optional exponential smoothing alpha (0 disables explicit smoothing). Applied to raw trend ratio before threshold compa…
G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO | float | 0.0 | Y | Ratio threshold for warning-level trend escalation.
G6_ADAPTIVE_SEVERITY_TREND_WINDOW | int | 0 | Y | Rolling window (cycles) for computing trend ratios (0 uses internal adaptive default). Larger window smooths noise; sma…
G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES | csv | (unset) | Y | Alert types that, while at WARN, block promotion of other types to CRITICAL to avoid alert storms (coordination heurist…
G6_ADAPTIVE_SLA_BREACH_STREAK | int | 0 | Y | Consecutive SLA health breaches before raising severity (0 uses default internal policy if implemented).
G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD | int | 3 | Y | Consecutive breach cycles required before scaling reduction triggers.
G6_ADAPTIVE_STRIKE_MAX_ITM | int | (unset) | Y | Optional explicit maximum ITM strikes (pre-scaling cap).
G6_ADAPTIVE_STRIKE_MAX_OTM | int | (unset) | Y | Optional explicit maximum OTM strikes.
G6_ADAPTIVE_STRIKE_MIN | int | 2 | Y | Minimum allowable strike depth (per side) after scaling (floor).
G6_ADAPTIVE_STRIKE_REDUCTION | float | 0.8 | Y | Multiplicative factor applied to current strike depth on breach.
G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY | int | 10 | Y | Healthy cycles required to begin restoring toward baseline depth.
G6_ADAPTIVE_STRIKE_SCALING | bool | off | Y | Master enable for strike window adaptive scaling.
G6_ADAPTIVE_STRIKE_STEP | int | (unset) | Y | Optional stride increment when computing initial strike depth.
G6_ADAPTIVE_THEME_GZIP | bool | off | Y | Enable gzip compression for adaptive theme responses if client supports it.
G6_ADAPTIVE_THEME_SSE_DIFF | bool | on | Y | Emit diff payloads after initial full snapshot.
G6_ADAPTIVE_THEME_STREAM_INTERVAL | float | 3 | Y | SSE streaming interval for adaptive theme endpoint.
G6_ADAPTIVE_THEME_STREAM_MAX_EVENTS | int | 200 | Y | Soft cap of SSE events per connection.
G6_ALERTS | bool | off | Y | Master enable for legacy alerts pipeline (base alert extraction & serialization). Off = no base alerts generated.
G6_ALERTS_FLAT_COMPAT | bool | on | Y | Preserve legacy flat alerts list shape for downstream consumers during transition to structured taxonomy.
G6_ALERTS_STATE_DIR | path | (unset) | Y | Optional directory for persisting per-alert-type state (streaks / suppression metadata) across restarts. If unset, stat…
G6_ALERT_FIELD_COV_MIN | float | 0.0 | Y | Minimum field coverage (0‑1) required before emitting field coverage warnings; below threshold triggers coverage alert…
G6_ALERT_LIQUIDITY_MIN_RATIO | float | 0.0 | Y | Minimum acceptable aggregated liquidity ratio; below triggers liquidity alert.
G6_ALERT_QUOTE_STALE_AGE_S | int | 0 | Y | Age in seconds after which last quote timestamp is considered stale for stale quote alert (0 disables).
G6_ALERT_STRIKE_COV_MIN | float | 0.0 | Y | Minimum strike coverage (0‑1) before emitting strike coverage shortfall alert.
G6_ALERT_TAXONOMY_EXTENDED | bool | off | Y | Emit extended taxonomy fields (group/subtype) for alerts that support it.
G6_ALERT_WIDE_SPREAD_PCT | float | 0.0 | Y | Percent (0‑1) spread threshold; options above considered wide and may trigger spread alert.
G6_ANALYTICS_COMPRESS | bool | off | Y | If on, gzip compress persisted analytics artifacts (vol surface / risk aggregation) producing `.json.gz` files.
G6_AUTO_SNAPSHOTS | bool | off | Y | Auto-build snapshots each loop when enhanced collector active.
G6_BENCHMARK_ANNOTATE_OUTLIERS | bool | off | Y | Add anomaly analysis block to benchmark artifact (robust stats) when enabled.
G6_BENCHMARK_ANOMALY_HISTORY | int | 50 | Y | Number of historical artifacts considered for robust anomaly stats.
G6_BENCHMARK_ANOMALY_THRESHOLD | float | 3.5 | Y | Robust z-score absolute threshold for outlier flagging.
G6_BENCHMARK_COMPRESS | bool | off | Y | Gzip-compress benchmark artifacts when G6_BENCHMARK_DUMP enabled (writes .json.gz files).
G6_BENCHMARK_KEEP_N | int | 0 | Y | Keep only most recent N benchmark artifacts when >0 (prunes older files after each write).
G6_BENCH_TREND_DEBUG | bool | off | Y | Emit internal recomputation debug lines for benchmark trend tooling (diagnostic noise).
G6_BOOTSTRAP_COMPONENTS | bool | off | Y | Enable experimental bootstrap path assembling providers/sinks modularly.
G6_BUILD_COMMIT | str | unknown | Y | Source control commit SHA used for the build.
G6_BUILD_CONFIG_HASH | str | unknown | Y | Build/config content hash label injected into `g6_build_info` metric (used for deployment provenance / drift detection).
G6_BUILD_TIME | str | unknown | Y | Build timestamp (ISO8601 or human readable). Used for traceability.
G6_BUILD_VERSION | str | dev | Y | Build/version identifier (e.g., semantic version or short tag). Defaults to dev if unset.
G6_CALENDAR_HOLIDAYS_JSON | path | (none) | Y | Deprecated alias for the holidays file path; prefer the canonical holidays file variable.
G6_CARDINALITY_MAX_SERIES | int | 0 | Y | Hard threshold of active metrics time series; above this guard triggers.
G6_CARDINALITY_MIN_DISABLE_SECONDS | int | 300 | Y | Minimum disable window before re-check for re-enable.
G6_CARDINALITY_REENABLE_FRACTION | float | 0.7 | Y | Re-enable per-option metrics when active series drop below fraction*max.
G6_CATALOG_EVENTS_CONTEXT | bool | on | Y | Include event context objects.
G6_CATALOG_EVENTS_LIMIT | int | 20 | Y | Max recent events.
G6_CATALOG_HTTP | bool | off | Y | Start /catalog HTTP server.
G6_CATALOG_HTTP_DISABLE | bool | off | Y | Hard override to prevent starting the catalog HTTP server even if enabling conditions (flags or implied by snapshots/pa…
G6_CATALOG_HTTP_FORCED | bool | off | Y | Force-enable catalog HTTP when snapshots/panels conditions met (internal helper usage).
G6_CATALOG_HTTP_FORCE_RELOAD | bool | off | Y | On next catalog HTTP access triggers controlled server restart (hot reload) for testing.
G6_CATALOG_HTTP_HOST | str | 127.0.0.1 | Y | Bind host.
G6_CATALOG_HTTP_PORT | int | 9315 | Y | Bind port.
G6_CATALOG_HTTP_REBUILD | bool | off | Y | Rebuild catalog each request instead of cached file.
G6_CATALOG_INTEGRITY | bool | off | Y | Add integrity analysis section.
G6_CATALOG_TS | string | (unset) | Y | Optional timestamp or version string injected when generating `docs/METRICS_CATALOG.md` via `scripts/gen_metrics_catalo…
G6_CB_BACKOFF | int | 5 | Y | Base backoff seconds (pre-jitter) before half-open retry.
G6_CB_FAILURES | int | 5 | Y | Failures threshold to open circuit (tests adjust lower).
G6_CB_HALF_OPEN_SUCC | int | 2 | Y | Required consecutive successes in half-open before closing circuit.
G6_CB_JITTER | float | 0.1 | Y | Jitter fraction applied to backoff (random +/- fraction * backoff).
G6_CB_MAX_RESET | int | 30 | Y | Max backoff seconds before next attempt.
G6_CB_MIN_RESET | int | 5 | Y | Minimum seconds before attempting half-open.
G6_CB_STATE_DIR | path | data/health | Y | Directory to persist circuit breaker state (survives restart) if enabled.
G6_CIRCUIT_METRICS | bool | off | Y | Emit detailed per-provider circuit breaker metrics series.
G6_COLLECTION_INTERVAL | float | 60 | Y | Legacy alias for per-cycle interval (prefer G6_CYCLE_INTERVAL/ config interval).
G6_COLLECTOR_REFACTOR_DEBUG | bool | off | Y | Enable verbose diagnostics around collector refactored code paths (alerts emission integration).
G6_COLOR | enum(auto|always|never) | auto | Y | Color policy.
G6_COMPOSITE_PROVIDER | bool | off | Y | Enable composite provider (multi-source fan‑out/merge) experimental path.
G6_COMPUTE_GREEKS | bool | off | Y | Enable Greeks computation path.
G6_CONCISE_LOGS | bool | on | Y | Suppress repetitive per-option chatter.
G6_CONFIG_DOC_STRICT | bool | off | Y | Treat missing config documentation entries as errors (governance mode; CI only).
G6_CONFIG_EMIT_NORMALIZED | bool | off | Y | Emit normalized effective config JSON to logs/normalized_config.json.
G6_CONFIG_LEGACY_SOFT | bool | off | Y | Allow loading with deprecated keys (stripped) instead of failing (currently usually off).
G6_CONFIG_LOADER | bool | off | Y | Force enhanced config loader pathway even if heuristics disabled.
G6_CONFIG_PATH | path | config/g6_config.json | Y | Primary runtime config file path override.
G6_CONFIG_SCHEMA_DOC_STRICT | bool | off | Y | Enforce that every schema key has a corresponding documentation block (superset strict mode).
G6_CONFIG_STRICT | bool | off | Y | Fail fast on any config validation issue (strict schema + semantic). Off = best-effort warnings.
G6_CONFIG_VALIDATE_CAPABILITIES | bool | off | Y | Enable capability validation phase ensuring provider supports requested feature set.
G6_CONTRACT_COOLDOWN | int | 3 | Y | Minimum cycles between successive contraction adjustments for a given index (prevents oscillation).
G6_CONTRACT_MULTIPLIER_DEFAULT | float | 1 | Y | Default contract multiplier applied when estimating notional exposures in risk aggregation (delta/vega notionals = |gre…
G6_CONTRACT_OK_CYCLES | int | 5 | Y | Consecutive healthy cycles (no low strike coverage & no expansions) required before attempting a contraction back towar…
G6_CONTRACT_STEP | int | 2 | Y | Number of strikes to reduce per side (ITM/OTM) when contraction triggers (never drops below initial baseline configurat…
G6_CSV_BASE_DIR | path | (unset) | Y | Base directory override for CSV sink file roots (falls back to config paths if unset).
G6_CSV_DEMO_DIR | path | (unset) | Y | Alternate output root used by demo / showcase scripts (panel snapshots, curated samples).
G6_CSV_JUNK_ENABLE | enum(auto|on|off) | auto | Y | Junk row filtering mode. auto enables when either threshold >0. Rows failing thresholds increment g6_csv_junk_rows_skip…
G6_CSV_JUNK_MIN_TOTAL_OI | int | 0 | Y | Junk filter: minimum combined (CE+PE) open interest required to persist a row (active only if >0 or junk enabled explic…
G6_CSV_JUNK_MIN_TOTAL_VOL | int | 0 | Y | Junk filter: minimum combined (CE+PE) volume required to persist a row.
G6_CSV_JUNK_STALE_THRESHOLD | int | 0 | Y | Junk filter: if >0, number of consecutive identical (CE,PE) last_price signatures per (index,expiry,strike_offset) afte…
G6_CSV_JUNK_SUMMARY_INTERVAL | int | 0 | Y | Seconds interval for periodic aggregated junk skip summary logs (CSV_JUNK_SUMMARY). 0 disables.
G6_CSV_JUNK_WHITELIST | str | (none) | Y | Comma list of patterns exempt from junk filtering. Patterns: INDEX:EXPIRY_CODE, INDEX:*, *:EXPIRY_CODE, or * for global…
G6_CSV_VERBOSE | bool | off | Y | Verbose per-write CSV debug logging (high volume; diagnostics only).
G6_CYCLE_OUTPUT | bool | off | Y | Emit per-cycle debug output (legacy instrumentation).
G6_CYCLE_SLA_FRACTION | float | 0.85 | Y | SLA fraction of interval to classify breach.
G6_CYCLE_STYLE | enum(legacy|readable) | legacy | Y | Select formatting for per-cycle summary lines when concise/quiet modes are active. 'legacy' emits the original compact…
G6_DASHBOARD_CORE_REFRESH_SEC | int | 5 | Y | Core dashboard (legacy web) refresh cadence.
G6_DASHBOARD_DEBUG | bool | off | Y | Enable verbose legacy dashboard debug logging.
G6_DASHBOARD_SECONDARY_REFRESH_SEC | int | 15 | Y | Secondary stats refresh cadence (legacy web).
G6_DEBUG_SHORT_TTL | bool | off | Y | Force very short instrument cache TTL (e.g., 5s) for debugging cache refresh logic.
G6_DETAIL_MODE_BAND_ATM_WINDOW | int | 0 | Y | Width (strikes) around ATM used for dynamic detail mode adjustments (band logic). 0 disables band gating.
G6_DISABLE_ADAPTIVE_STRIKE_RETRY | bool | off | Y | Disable adaptive strike depth expansion logic (R1.14). When set, collectors will not mutate `strikes_itm/strikes_otm` e…
G6_DISABLE_AUTO_DOTENV | bool | off | Y | Prevent automatic loading of .env file by kite provider when API credentials missing (use external secret management in…
G6_DISABLE_COMPONENTS | bool | off | Y | Skip optional component initialization during bootstrap (provider aggregates, sinks, panels). Mainly for ultra-lean tes…
G6_DISABLE_EXPIRY_MAP | bool | off | Y | Disable the pre-built per-index expiry→instrument map fast path and force legacy per-expiry scans. Use only for debuggi…
G6_DISABLE_GREEKS | bool | off | Y | Disable Greeks computation path even if normally implied / enabled.
G6_DISABLE_METRICS_SOURCE | bool | off | Y | Disable emitting per-option source metrics (diagnostic gating / perf reduction).
G6_DISABLE_METRIC_GROUPS | str | (none) | Y | Comma separated list of metric group identifiers to disable at registration time (e.g., analytics_vol_surface,analytics…
G6_DISABLE_MINIMAL_CONSOLE | bool | off | Y | Re-enable default logging format if minimal console active.
G6_DISABLE_PREFILTER | bool | off | Y | Disable pre-index strike/type narrowing (diagnostic or emergency mode; increases scan cost).
G6_DISABLE_PRETTY_CYCLE | bool | off | Y | Disable pretty cycle formatting (plain timing logs).
G6_DISABLE_ROOT_CACHE | bool | off | Y | When set (1/true) disables process-wide root symbol detection cache, forcing direct parsing each call (diagnostics / pr…
G6_DISABLE_STARTUP_BANNER | bool | off | Y | Suppress banner entirely.
G6_DISABLE_STRIKE_CACHE | bool | off | Y | Disable strike metadata caching (forces fresh strike lookups each cycle; higher latency; diagnostics only).
G6_DISABLE_STRUCT_EVENTS | bool | off | Y | Master kill-switch for structured observability events (instrument_prefilter_summary, option_match_stats, zero_data, cy…
G6_DOMAIN_MODELS | bool | off | Y | Map raw quotes to domain model objects for debugging/analysis.
G6_DQ_ERROR_THRESHOLD | int | 0 | Y | Data quality error threshold (context-specific; triggers stricter handling).
G6_DQ_WARN_THRESHOLD | int | 0 | Y | Data quality warning threshold.
G6_EMIT_CATALOG | bool | off | Y | Emit catalog JSON during status writes.
G6_EMIT_CATALOG_EVENTS | bool | off | Y | Include recent events slice.
G6_ENABLE_BACKWARD_EXPIRY_FALLBACK | bool | on | Y | Enable backward (nearest past) expiry fallback search if target and forward are empty.
G6_ENABLE_BLACK | bool | off | Y | When set, enables black formatting pass in `dev_tasks.py format` after ruff format.
G6_ENABLE_DATA_QUALITY | bool | off | Y | Master enable for optional data quality checker integration in collectors. When on, best-effort index / option / expiry…
G6_ENABLE_NEAREST_EXPIRY_FALLBACK | bool | on | Y | Enable forward (nearest future) expiry fallback search when target expiry has zero matches.
G6_ENABLE_OPTIONAL_TESTS | bool | off | Y | Activate optional pytest cases.
G6_ENABLE_PANEL_PUBLISH | bool | off | Y | Enable panel publisher (writes JSON snapshots each cycle).
G6_ENABLE_PERF_TESTS | bool | off | Y | Run performance micro-benchmarks (expiry service, etc.).
G6_ENABLE_SLOW_TESTS | bool | off | Y | Activate slow pytest cases.
G6_ENABLE_TRACEMALLOC | bool | off | Y | Enable tracemalloc tracking at startup (snapshots require other G6_TRACEMALLOC_* vars).
G6_ENHANCED_CONFIG | bool | off | Y | Enable enhanced config validation / enrichment path.
G6_ENHANCED_SNAPSHOT_MODE | bool | off | Y | Forces enhanced collector shim to use snapshot collectors (no persistence) regardless of legacy/unified mode; used by t…
G6_ENHANCED_UI | bool | off | Y | Enable enhanced console UI styling features.
G6_ENHANCED_UI_MARKER | bool | off | Y | Display explicit marker that enhanced UI mode is active (debugging support).
G6_ENRICH_ASYNC | bool | off | Y | Master gate for asynchronous enrichment pipeline.
G6_ENRICH_ASYNC_BATCH | int | 0 | Y | Optional batch size for grouped async enrichment tasks; 0/<=0 means process individually.
G6_ENRICH_ASYNC_TIMEOUT_MS | int | 0 | Y | Per batch/task timeout milliseconds; 0 disables explicit timeout.
G6_ENRICH_ASYNC_WORKERS | int | 4 | Y | Max concurrent async enrichment worker tasks (thread or async tasks depending on implementation).
G6_ENV_DEPRECATION_ALLOW | str | (unset) | Y | Comma list of deprecated env var names exempt from strict-mode failure (temporary grace). Example usage: set to a comma…
G6_ENV_DEPRECATION_STRICT | bool | off | Y | When enabled, any presence of a deprecated environment variable (status=deprecated in lifecycle registry) triggers a ha…
G6_ESTIMATE_IV | bool | off | Y | Enable IV solver attempts.
G6_EVENTS_DISABLE | bool | off | Y | Disable event emission entirely.
G6_EVENTS_FORCE_FULL_RETRY_SECONDS | float | 30 | Y | Cooldown period (seconds) per guard reason before another forced baseline may be emitted. Prevents rapid forced full ch…
G6_EVENTS_LOG_PATH | path | logs/events.log | Y | Override path for structured event log.
G6_EVENTS_MIN_LEVEL | enum(DEBUG|INFO|WARN|ERROR) | INFO | Y | Minimum level to record.
G6_EVENTS_RECENT_MAX | int | 200 | Y | Max in-memory recent events retained for tail queries.
G6_EVENTS_SAMPLE_DEFAULT | float | 1.0 | Y | Default sampling probability (0-1) for events without explicit mapping.
G6_EVENTS_SAMPLE_MAP | str | (none) | Y | Comma separated event=prob pairs (e.g., cycle_start=0.1,error=1.0).
G6_EVENTS_SNAPSHOT_GAP_MAX | int | 500 | Y | Maximum allowed event id gap between last `panel_full` and current latest event before snapshot guard forces a new base…
G6_EVENTS_SSE_HEARTBEAT | float | 45 | Y | Interval in seconds between heartbeat comments written to the `/events` SSE stream to keep idle connections alive.
G6_EVENTS_SSE_POLL | float | 1.0 | Y | Server-side poll cadence in seconds while streaming backlog events over SSE.
G6_EVENTS_SSE_RETRY_MS | int | 3000 | Y | Retry delay (milliseconds) advertised to SSE clients via the `retry:` field when streaming `/events`.
G6_EXPIRY_COERCION_AGGREGATE | bool | off | Y | When enabled, config expiry coercion validation aggregates multiple coercion suggestions instead of first-match shortcu…
G6_EXPIRY_EXPAND_CONFIG | str | (unset/off) | Y | When set truthy (1/true/on or non-empty value) the collectors attempt to expand a single provided expiry tag (e.g. ['th…
G6_EXPIRY_MAP_STRICT | bool | off | Y | When enabled, treats any instrument with unparsable/missing expiry as a hard skip (increments invalid counters) rather…
G6_EXPIRY_RULE_RESOLUTION | bool | off | Y | Enable rule-based resolution of expiry tokens (this_week, next_week, this_month, next_month) to real calendar dates per…
G6_FACADE_PARITY_STRICT | bool | off | Y | When using the orchestrator facade with `mode=auto|pipeline` and `parity_check=True`, a parity hash mismatch (pipeline…
G6_FANCY_CONSOLE | bool | auto (enabled if TTY) | Y | Force fancy startup banner / panels.
G6_FIELD_COVERAGE_OK | float | 0.55 | Y | Field (volume+oi+avg_price) coverage threshold (0-1) for OK classification. Lower to reduce PARTIAL statuses under spar…
G6_FILTER_MIN_OI | int | 0 | Y | Minimum per-option open interest required to retain an option. 0 disables OI filtering.
G6_FILTER_MIN_VOLUME | int | 0 | Y | Minimum per-option volume required to retain an option during expiry processing (filter stage in `expiry_processor`). 0…
G6_FILTER_VOLUME_PERCENTILE | float | 0.0 | Y | When >0, drops options below the given lower volume percentile (0-1) per expiry after initial min filters. Applied befo…
G6_FOLLOWUPS_BUCKET_CONSEC | int | 0 | Y | Consecutive cycles below bucket threshold required before bucket followup emits.
G6_FOLLOWUPS_BUCKET_THRESHOLD | float | 0.0 | Y | Threshold for bucket utilization degradation followup trigger.
G6_FOLLOWUPS_BUFFER_MAX | int | 200 | Y | Ring buffer size of recent raw observations per alert type (memory for trend logic). Non‑positive => fallback default.
G6_FOLLOWUPS_DEBUG | bool | off | Y | Verbose logging for followup evaluation decisions (guarded; noisy in production).
G6_FOLLOWUPS_DEMOTE_THRESHOLD | float | 0.0 | Y | Threshold indicating sustained degraded condition suggesting controller demotion (advisory followup).
G6_FOLLOWUPS_ENABLED | bool | off | Y | Master enable for followups subsystem.
G6_FOLLOWUPS_EVENTS | bool | off | Y | Emit structured followup events onto event bus instead of (or in addition to) panel‑only data.
G6_FOLLOWUPS_INTERP_CONSEC | int | 0 | Y | Consecutive cycles exceeding interpolation threshold needed before followup.
G6_FOLLOWUPS_INTERP_THRESHOLD | float | 0.0 | Y | Threshold for interpolation fraction anomaly followup.
G6_FOLLOWUPS_PANEL_LIMIT | int | 50 | Y | Maximum number of followup entries surfaced in panels (older trimmed).
G6_FOLLOWUPS_RISK_DRIFT_PCT | float | 0.0 | Y | Absolute delta drift % threshold for risk drift followup.
G6_FOLLOWUPS_RISK_MIN_OPTIONS | int | 0 | Y | Minimum options required for risk drift computation; fewer => no followup.
G6_FOLLOWUPS_RISK_WINDOW | int | 0 | Y | Sliding window length for risk drift baseline; 0 disables drift followup logic.
G6_FOLLOWUPS_SUPPRESS_SECONDS | int | 0 | Y | Suppression window after a followup fires before same type may fire again (0 disables suppression).
G6_FOLLOWUPS_WEIGHTS | JSON | (unset) | Y | Optional JSON mapping alert_type -> weight (or scheme descriptor) overriding default equal weighting.
G6_FOLLOWUPS_WEIGHT_WINDOW | int | 30 | Y | Window size (cycles) for weighted / EWMA calculations (if logic enabled). 0 disables weighting.
G6_FORCE_ASCII | bool | off | Y | Force ASCII-only output (disable unicode for terminals lacking support).
G6_FORCE_DATA_SOURCE | enum(metrics|runtime_status|catalog) | (auto) | Y | Force underlying dataset for summary views.
G6_FORCE_GREEKS | bool | off | Y | Force enable Greeks computation regardless of heuristics (overrides disable flag precedence if both set).
G6_FORCE_MARKET_OPEN | bool | off | Y | Bypass market-hours gating (tests / backfill).
G6_FORCE_NEW_REGISTRY | bool | off | Y | When set forces `setup_metrics_server` to discard the existing Prometheus default registry and rebuild a fresh `Metrics…
G6_FORCE_UNICODE | bool | off | Y | Force unicode (skip ASCII fallback).
G6_FOREIGN_EXPIRY_SALVAGE | bool | off | Y | Salvage heuristic: when every row of an expiry was pruned solely due to foreign_expiry classification, rewrites batch t…
G6_GIT_COMMIT | str(sha) | (auto) | Y | Override git commit label.
G6_HEALTH_API | bool | off | Y | Expose health API endpoint (legacy/diagnostic).
G6_HEALTH_COMPONENTS | bool | off | Y | Emit component health metrics / panel section when enabled.
G6_HEALTH_PROMETHEUS | bool | off | Y | Expose Prometheus metrics endpoint (legacy toggle; prefer always-on when metrics enabled).
G6_HOLIDAYS_FILE | path | (none) | Y | JSON file enumerating YYYY-MM-DD holidays (market closed days) used for gating.
G6_HTTP_BASIC_PASS | str | (none) | Y | Basic Auth password.
G6_HTTP_BASIC_USER | str | (none) | Y | Enable Basic Auth (paired with pass).
G6_INDICES_PANEL_LOG | path | (none) | Y | Optional log path capturing indices panel frames.
G6_INFLUX_BATCH_SIZE | int | 0 | Y | Number of points per Influx line protocol batch before flush (0 uses internal default / unbatched path).
G6_INFLUX_FLUSH_INTERVAL | int | 0 | Y | Seconds between forced Influx flushes when batching active; 0 disables periodic flush forcing.
G6_INFLUX_MAX_QUEUE_SIZE | int | 0 | Y | Upper bound on queued pending points before backpressure / drop strategy.
G6_INFLUX_POOL_MAX_SIZE | int | 0 | Y | Maximum connection pool size.
G6_INFLUX_POOL_MIN_SIZE | int | 0 | Y | Minimum connection pool size (if client supports pooling).
G6_INSTRUMENT_CACHE_TTL | float | 600 | Y | Base TTL (seconds) for provider instrument metadata cache. Adjust lower in tests; automatically reduced in LEAN or DEBU…
G6_INTEGRITY_AUTO_EVERY | int | 0 | Y | Seconds between periodic integrity auto-runs; 0 disables recurring schedule.
G6_INTEGRITY_AUTO_RUN | bool | off | Y | Enable automatic integrity verification pass (structure / artifact cross-check) on startup.
G6_INTERP_FRACTION_ALERT_STREAK | int | 0 | Y | Consecutive cycles exceeding interpolation fraction threshold before initial alert.
G6_INTERP_FRACTION_ALERT_THRESHOLD | float | 0.0 | Y | Baseline interpolation fraction threshold feeding alert generation (distinct from followups threshold if both present).
G6_JSON_LOGS | bool | off | Y | Emit structured JSON lines to console instead of human-friendly formatter.
G6_KITE_AUTH_VERBOSE | bool | off | Y | When enabled, token validation logs full tracebacks & structured error handler output for invalid/expired Kite tokens i…
G6_KITE_RATE_LIMIT_BURST | int | 0 | Y | Allowed burst above steady CPS before throttling begins.
G6_KITE_RATE_LIMIT_CPS | int | 0 | Y | Target max calls per second throttle (client side) for Kite provider; 0 disables custom throttle.
G6_KITE_THROTTLE_MS | int | 0 | Y | Additional fixed millisecond delay injected between Kite API calls (diagnostics or pacing).
G6_KITE_TIMEOUT | float | 0.0 | Y | Per-request timeout seconds (float) for Kite API; 0 => library default.
G6_KITE_TIMEOUT_SEC | int | 0 | Y | Integer alias for per-request timeout (takes precedence if set >0).
G6_LEAN_MODE | bool | off | Y | Activate lean collection mode: reduces instrument cache TTL and may skip heavyweight enrichment paths.
G6_LEGACY_LOOP_WARNED | internal sentinel | (unset) | Y | Internal process-level flag set after first deprecation warning emission (not a user-facing toggle; documented to satis…
G6_LIFECYCLE_COMPRESSION_AGE_SEC | int | 0 | Y | Minimum artifact age seconds before lifecycle compression job considers it.
G6_LIFECYCLE_COMPRESSION_EXT | str | .json | Y | File extension filter for lifecycle compression candidate selection.
G6_LIFECYCLE_JOB | bool | off | Y | Enable background lifecycle maintenance job (compression / pruning).
G6_LIFECYCLE_MAX_PER_CYCLE | int | 0 | Y | Maximum number of lifecycle operations (compress/prune/delete) performed per maintenance cycle; 0 = no explicit cap.
G6_LIFECYCLE_QUAR_DIR | path | (unset) | Y | Optional quarantine directory where problematic or partially written artifacts are moved instead of deleted (diagnostic…
G6_LIFECYCLE_RETENTION_DAYS | int | 0 | Y | Retain artifacts newer than N days; older eligible for deletion (0 disables age-based deletion).
G6_LIFECYCLE_RETENTION_DELETE_LIMIT | int | 0 | Y | Hard cap of deletion operations per cycle (independent of compression). 0 = unlimited within selection.
G6_LIVE_PANEL | bool | on (TTY) | Y | Enable per-cycle live panel refresh.
G6_LOG_FILE | path | logs/g6_platform.log | Y | Log file output path.
G6_LOG_LEVEL | str | INFO | Y | Set via scripts for run_live convenience.
G6_LOOP_INTERVAL_SECONDS | float | (config/default) | Y | Explicit orchestrator loop interval override captured in runtime_config (Phase 3). Set implicitly when CLI --interval d…
G6_LOOP_MARKET_HOURS | bool | off | Y | Apply market hours gating inside new loop path.
G6_LOOP_MAX_CYCLES | int | 0/unset | Y | Orchestrator `run_loop` only: when >0 stops loop after N successfully executed (non-skipped) cycles; set automatically…
G6_MASTER_REFRESH_SEC | int | 0 | Y | When >0, legacy master refresh cadence overriding unified refresh logic (migrating away).
G6_MAX_CYCLES | int | 0 | Y | Upper bound on main loop iterations (0 = unbounded).
G6_MEMORY_GC_INTERVAL_SEC | int | 0 | Y | Force manual garbage collection every N seconds (0=disabled).
G6_MEMORY_LEVEL1_MB | int | 200 | Y | Tier 1 memory soft limit (MB) for adaptive behaviors.
G6_MEMORY_LEVEL2_MB | int | 300 | Y | Tier 2 memory soft limit (MB) for intensified mitigation.
G6_MEMORY_LEVEL3_MB | int | 500 | Y | Tier 3 hard memory threshold (MB) triggers aggressive scaling or abort logic.
G6_MEMORY_MINOR_GC_EACH_CYCLE | bool | off | Y | Trigger gc.collect() each cycle (diagnostics; may impact latency).
G6_MEMORY_PRESSURE_RECOVERY_SECONDS | int | 120 | Y | Consecutive healthy seconds before recovering a memory tier.
G6_MEMORY_PRESSURE_TIERS | str | (auto) | Y | Comma list of MB thresholds overriding tier env vars.
G6_MEMORY_ROLLBACK_COOLDOWN | int | 60 | Y | Cooldown seconds before retrying deeper strike depth after rollback.
G6_MEMORY_TIER | int | 0 | Y | Legacy single numeric memory tier selector (1/2/3). When set (>0) may override derived tier from LEVEL{1,2,3}_MB bounda…
G6_METRICS_CARD_ATM_WINDOW | int | 0 | Y | When >0 restrict detailed option metrics to strikes within +/- window steps of ATM (pre-filter before cardinality guard…
G6_METRICS_CARD_CHANGE_THRESHOLD | float | 0.0 | Y | Required price delta for re-emission.
G6_METRICS_CARD_ENABLED | bool | on | Y | Master switch controlling dynamic option-metric cardinality management features.
G6_METRICS_CARD_RATE_LIMIT_PER_SEC | int | 0 | Y | Global per-option emission cap.
G6_METRICS_ENABLED | bool | on | Y | Master enable switch for metrics server initialization & metric family registration. Set 0/false to disable Prometheus…
G6_METRICS_ENDPOINT | str | (unset) | Y | Explicit metrics HTTP endpoint path override (e.g., /metrics_alt). If unset default exporter path used.
G6_METRICS_HOST | str | 0.0.0.0 | Y | Override bind host for metrics server (takes precedence over config file value when set).
G6_METRICS_INTROSPECTION_DUMP | bool | off | Y | When enabled (1/true/yes/on) logs a one-shot debug dump of registered metrics metadata (name, type, labels, group) on m…
G6_METRICS_PORT | int | 9108 | Y | Override bind port for metrics server (takes precedence over config file value when set).
G6_METRICS_STRICT_EXCEPTIONS | bool | off | Y | When enabled unexpected exceptions during metric registration (placeholders, spec minimum assurance, _maybe_register) a…
G6_METRICS_URL | url | (unset) | Y | Full push/pull remote metrics URL override used by external scraper/pusher integration (experimental). Not normally req…
G6_MISSING_CYCLE_FACTOR | float | 2.0 | Y | Multiplier for detecting missed cycles (gap >= factor * interval triggers g6_missing_cycles_total increment; clamp min…
G6_MONTHLY_EXPIRY_DOW | int | 4 | Y | Override day-of-week (0=Mon..6=Sun) used to infer monthly expiry anchor when rule-based resolver uncertain.
G6_MYPY_BIN | path | mypy | Y | Override mypy executable path.
G6_NEW_BOOTSTRAP | bool | off | Y | Force new bootstrap even if legacy path still present.
G6_NEW_LOOP | bool | off | Y | Enable experimental orchestrator `run_loop` driver.
G6_OPTION_METRIC_ATM_WINDOW | int | 0 | Y | Additional filter: only strikes within +/- window steps around ATM for option-detail metrics (pre-guard heuristic).
G6_OUTPUT_JSONL_PATH | path | g6_output.jsonl | Y | Output JSONL file path for unified source output sink.
G6_OUTPUT_LEVEL | str | INFO | Y | Override base log level (also via --log-level maybe).
G6_OUTPUT_SINKS | csv | stdout,logging | Y | Comma list: stdout,logging,panels,memory.
G6_OVERLAY_SKIP_NON_TRADING | bool | off | Y | Skip overlay generation on non-trading days.
G6_OVERLAY_VIS_CHUNK_SIZE | int | 2048 | Y | Batch size when building overlays.
G6_OVERLAY_VIS_MEMORY_LIMIT_MB | int | 512 | Y | Memory budget for overlay aggregation.
G6_OVERLAY_WRITE_BACKUP | bool | off | Y | Write backup copy of overlay output for audit.
G6_OVERVIEW_INTERVAL_SECONDS | int | 180 | Y | Interval (seconds) between overview snapshot persistence operations.
G6_PANELS_ALWAYS_META | bool | off | Y | When enabled forces writer to always include metadata block (version, schema_version, build info) even if unchanged, si…
G6_PANELS_ATOMIC | bool | on | Y | Write panel JSON atomically (tmp + replace). Disable (0/false) only for debugging on filesystems where atomic rename be…
G6_PANELS_DIR | path | data/panels | Y | Directory for emitted panel JSON.
G6_PANELS_INCLUDE | csv | (unset) | Y | Optional comma list of panel names to emit (others skipped). Empty/unset emits all. Useful for focused benchmarking or…
G6_PANELS_INTEGRITY_INTERVAL | int | 30 | Y | Minimum seconds between integrity monitor runs (hash recompute / manifest compare). Lower for aggressive detection; rai…
G6_PANELS_INTEGRITY_MONITOR | bool | on | Y | Master enable for panels integrity monitoring loop (hashing + mismatch counters). Disable to skip all integrity computa…
G6_PANELS_INTEGRITY_STRICT | bool | off | Y | When enabled, any detected mismatch triggers a hard process exit (after logging) instead of metric-only signaling. Inte…
G6_PANELS_LOOP_BACKOFF_MS | int | 250 | Y | Backoff sleep (milliseconds) between successive panel writer loop iterations when no triggering events occur.
G6_PANELS_READ_BACKOFF_MS | int | 250 | Y | Backoff sleep (milliseconds) used by panel reader/ingestor loops when waiting for new or updated panel artifacts.
G6_PANELS_READ_RETRY | int | 3 | Y | Retry attempts when transient read errors (partial write/permission) encountered during panel ingestion; 0 disables ret…
G6_PANELS_SCHEMA_WRAPPER | bool | on | Y | Emit panels with top-level schema_version wrapper for forward compatibility (enforced by panel schema governance). Disa…
G6_PANELS_SSE_DEBUG | bool | off | Y | Increase verbosity for SSEPanelsIngestor (logs raw SSE events, merge decisions). Use only for debugging; noisy otherwis…
G6_PANELS_SSE_OVERLAY | bool | off | Y | When enabled, the SSE panels ingestor overlays (merges) its in-memory baseline status into the live snapshot used by th…
G6_PANELS_SSE_STRICT | bool | off | Y | Treat malformed or merge-conflicting SSE panel events as hard errors (raise) instead of warnings. Useful for CI enforce…
G6_PANELS_SSE_TIMEOUT | float | 45 | Y | Client-side timeout (seconds) for the panels SSE ingestion plugin (`SSEPanelsIngestor`). When the underlying HTTP read…
G6_PANELS_SSE_TYPES | csv | panel_full,panel_diff | Y | Comma-separated list of SSE event types the panels ingestion plugin subscribes to. Extend to include `severity_state`,…
G6_PANELS_SSE_URL | url | (unset) | Y | If set, activates SSEPanelsIngestor plugin which connects to the panels SSE endpoint (e.g. `http://127.0.0.1:9315/event…
G6_PANELS_VALIDATE | bool | off | Y | Enable strict schema validation of panels prior to write; failures log error and skip write.
G6_PANELS_WRITER_BASIC | bool | off | Y | Use simplified basic writer (no integrity hashing / diff) for performance testing or constrained environments.
G6_PANEL_AUTO_FIT | bool | on | Y | Enable automatic column width fitting for tabular panels (off retains configured / static widths).
G6_PANEL_CLIP | bool | off | Y | Clip overlong cell contents instead of wrapping (reduces row height volatility).
G6_PANEL_DIFFS | bool | on | Y | Master enable for diff panel generation (panel_diff events / metrics). Off => only full snapshots.
G6_PANEL_DIFF_FULL_INTERVAL | int | 0 | Y | Force a full panel snapshot every N diff cycles (0 disables forced periodic fulls) to bound drift.
G6_PANEL_DIFF_MAX_KEYS | int | 0 | Y | Upper cap on number of diff keys included (largest changes prioritized). 0 = unlimited.
G6_PANEL_DIFF_NEST_DEPTH | int | 3 | Y | Maximum nested object depth included in diff computation (beyond truncated / summarized). 0 disables diff recursion (sh…
G6_PANEL_H_ | int | 0 | Y | Fixed height override for summary panel (0=auto).
G6_PANEL_H_MARKET | int | 0 | Y | Fixed height override for market panel.
G6_PANEL_MIN_COL_W | int | 10 | Y | Minimum column width when auto-fitting.
G6_PANEL_W_ | int | 0 | Y | Fixed width override for summary panel (0=auto).
G6_PANEL_W_MARKET | int | 0 | Y | Fixed width override for market panel.
G6_PARALLEL_CYCLE_BUDGET_FRACTION | float | 0.9 | Y | Fraction of cycle interval available for parallel collection; remaining indices skipped once exceeded.
G6_PARALLEL_INDEX_RETRY | int | 0 | Y | Retry attempts (serial) after parallel failures/timeouts (best-effort within remaining budget).
G6_PARALLEL_INDEX_TIMEOUT_SEC | float | 0.25 * interval | Y | Per-index soft timeout in parallel mode; timeout increments timeout counter and optionally retries.
G6_PARALLEL_INDEX_WORKERS | int | 4 | Y | Maximum threads for parallel per-index collectors.
G6_PARALLEL_INDICES | bool | off | Y | Enable parallel per-index collection (pipeline/enhanced modes).
G6_PARALLEL_MAX_WORKERS | int | 0 | Y | Hard ceiling on parallel worker threads/processes for multi-index or multi-expiry tasks (0 => internal default heuristi…
G6_PARALLEL_STAGGER_MS | int | 0 | Y | Millisecond stagger between task submissions to reduce burst contention.
G6_PARITY_FLOAT_ATOL | float | 1e-09 | Y | Absolute tolerance for float near-equality in parity comparisons.
G6_PARITY_FLOAT_RTOL | float | 1e-06 | Y | Relative tolerance for float comparisons.
G6_PARITY_GOLDEN_VERIFY | bool | off | Y | When set to 1/true enables parity golden verification test (`tests/test_parity_golden_verify.py`) which recomputes chec…
G6_PARITY_INCLUDE_REASON_GROUPS | bool | off | Y | Include expanded reason group metadata in parity artifacts (increases JSON size; helps debugging mismatches).
G6_PIPELINE_COLLECTOR | (deprecated) | (ignored) | Y | Historical opt-in flag for the pipeline collector path. As of 2025-10-01 the pipeline path is the default via orchestra…
G6_PIPELINE_INCLUDE_DIAGNOSTICS | bool | off | Y | Force inclusion of extended diagnostic blocks (timing, allocation hints) in pipeline status artifacts.
G6_PIPELINE_REENTRY | internal sentinel | (unset) | Y | Internal guard set during pipeline delegation to prevent infinite recursion (pipeline -> legacy -> pipeline). Not user-…
G6_PIPELINE_ROLLOUT | str | (unset) | Y | Rollout phase marker (e.g., canary,beta,ga) used for conditional logging / gating during staged pipeline adoption.
G6_PIP_AUDIT_IGNORE | csv | (unset) | Y | Comma list of vulnerability IDs to ignore (temporary mitigation until upstream fix / dependency upgrade).
G6_PIP_AUDIT_SEVERITY | enum(critical|high|medium|low) | high | Y | Minimum severity of vulnerabilities that cause pip audit governance to fail (invoked in tooling scripts if enabled).
G6_PLOTLY_JS_PATH | path/url | (cdn) | Y | Where to load Plotly JS.
G6_PLOTLY_VERSION | str | (auto) | Y | Override Plotly version label.
G6_PREFILTER_CLAMP_STRICT | bool | off | Y | When on, a clamp downgrade marks the expiry PARTIAL (partial_reason=prefilter_clamp) to surface the event.
G6_PREFILTER_DISABLE | bool | off | Y | Disable prefilter clamp logic entirely (no trimming even if above threshold).
G6_PREFILTER_MAX_INSTRUMENTS | int | 2500 | Y | Safety valve upper bound on per-expiry instrument list; lists above this are truncated before quote enrichment (floor=5…
G6_PREVENTIVE_DEBUG | bool | off | Y | Verbose logging for preventive validation adjustments.
G6_PRICE_MAX_INDEX_FRAC | float | 0.0 | Y | If >0, filter strikes above frac * underlying index price.
G6_PRICE_MAX_STRIKE_FRAC | float | 0.35 | Y | Fraction of underlying price above which strikes may be filtered.
G6_PRICE_PAISE_THRESHOLD | float | 1e8 | Y | Upper monetary guard before paise normalization adjustments (tests set huge to trigger path).
G6_PROCESS_START_TS | int | (auto) | Y | Override process start timestamp (testing/time travel).
G6_PROFILE_EXPIRY_MAP | bool | off | Y | Emit one-shot timing / stats for expiry map build in profiling harness (`scripts/profile_unified_cycle.py`). Use to mea…
G6_PROVIDERS_PRIMARY_API_KEY | str | (unset) | Y | Explicit primary provider API key override (alternate secret injection path; prefer secure secret store in production).
G6_PROVIDER_FAILFAST | bool | off | Y | Abort composite provider traversal after first failure (diagnostics).
G6_PROVIDER_LAT_ERR_MS | int | 0 | Y | Milliseconds error threshold for provider call latency (above emits elevated severity / event; 0 disables).
G6_PROVIDER_LAT_WARN_MS | int | 0 | Y | Milliseconds warning threshold for provider call latency instrumentation (0 disables warn-level thresholding).
G6_PUBLISHER_EMIT_INDICES_STREAM | bool | off | Y | Add indices stream file when publisher active.
G6_PYTEST_BIN | path | pytest | Y | Override pytest executable path.
G6_QUIET_ALLOW_TRACE | bool | off | Y | Override within quiet mode to allow `_trace` diagnostic emissions (set to 1/true). Without quiet mode this flag is igno…
G6_QUIET_MODE | bool | off | Y | Quiet mode: elevate root log level and suppress verbose trace chatter (implies concise logs).
G6_REFACTOR_DEBUG | bool | off | Y | Emit verbose logs for ongoing refactor touchpoints outside collector-specific refactor debug flag.
G6_REGEN_PARITY_GOLDEN | bool | off | Y | When set to 1/true, enables regeneration of parity harness golden report in `test_orchestrator_parity_golden_regen` (wr…
G6_RETRY_BACKOFF | float | 0.0 | Y | Base retry backoff seconds for provider operations.
G6_RETRY_BLACKLIST | str | (none) | Y | Comma list of exception names to never retry.
G6_RETRY_JITTER | float | 0.1 | Y | Jitter fraction applied to retry backoff.
G6_RETRY_MAX_ATTEMPTS | int | 0 | Y | Max provider retry attempts (0 disables custom retry loop).
G6_RETRY_MAX_SECONDS | int | 0 | Y | Max cumulative seconds for retries.
G6_RETRY_PROVIDERS | bool | off | Y | Standardized retry for provider get_quote/get_ltp.
G6_RETRY_WHITELIST | str | (none) | Y | Comma list of exception names eligible for retry (if set overrides defaults).
G6_RETURN_SNAPSHOTS | bool | off | Y | Force collectors to return per-option snapshots.
G6_RISK_AGG_BUCKETS | str | -20,-10,-5,0,5,10,20 | Y | Moneyness bucket edges for risk aggregation (same semantics as surface buckets).
G6_RISK_AGG_MAX_OPTIONS | int | 25000 | Y | Safety cap on options processed per risk aggregation build.
G6_RISK_AGG_PERSIST | bool | off | Y | Persist latest risk aggregation artifact (risk_agg.latest.json[.gz]) to analytics directory.
G6_RISK_BUCKET_UTIL_MIN | float | 0.0 | Y | Minimum acceptable bucket utilization fraction; below triggers internal degraded classification aiding volatility surfa…
G6_RISK_BUCKET_UTIL_STREAK | int | 0 | Y | Consecutive cycles of low bucket utilization before escalation / classification persists.
G6_RISK_DELTA_DRIFT_PCT | float | 0.0 | Y | Absolute delta drift percent threshold for risk parity drift evaluation (separate from followups if both active).
G6_RISK_DELTA_DRIFT_WINDOW | int | 0 | Y | Window length (cycles) for establishing baseline delta drift; 0 disables windowed drift logic.
G6_RISK_DELTA_STABLE_ROW_TOLERANCE | int | 0 | Y | Maximum allowed differing row count before delta considered unstable (0 uses default heuristic).
G6_RISK_NOTIONALS_PER_INDEX | int | 0 | Y | Upper safety bound on number of per-index notional records tracked in risk aggregation output (0 unlimited).
G6_ROOT_CACHE_MAX | int | 4096 | Y | Soft maximum number of distinct symbol roots retained in cache before opportunistic eviction (~5%). Adjust if working u…
G6_RUFF_BIN | path | ruff | Y | Override ruff executable path for `scripts/dev_tasks.py`.
G6_RUNTIME_STATUS | bool | off | Y | Enable runtime status writer (legacy alias; prefer always-on status writer path).
G6_RUNTIME_STATUS_FILE | path | data/runtime_status.json | Y | Override status file path.
G6_RUN_ID | str | (auto) | Y | Unique run identifier injected into logs/metrics.
G6_SBOM_INCLUDE_HASH | bool | off | Y | Include per-component cryptographic hash metadata in generated SBOM artifacts (slightly higher generation cost; improve…
G6_SECONDARY_PROVIDER_PATH | path | (unset) | Y | Optional module path or config file enabling secondary provider injection for composite failover tests.
G6_SKIP_CONFIG_DOC_VALIDATION | bool | off | Y | Skip config documentation coverage test (emergency only; must be accompanied by follow-up PR adding docs).
G6_SKIP_CONFIG_SCHEMA_DOC_SYNC | bool | off | Y | Skip schema-to-doc sync validation pass (emergency only).
G6_SKIP_PROVIDER_READINESS | bool | off | Y | Skip provider readiness / health validation (tests).
G6_SKIP_ZERO_ROWS | bool | off | Y | Skip writing CSV rows with all zero volume & OI.
G6_SNAPSHOT_CACHE | bool | off | Y | Maintain in-memory latest snapshots (requires catalog HTTP for /snapshots endpoint).
G6_SNAPSHOT_CACHE_FORCE | bool | off | Y | Force snapshot cache refresh / rebuild on next access regardless of staleness heuristics (diagnostic/testing aid). Avoi…
G6_SNAPSHOT_TEST_MODE | bool | off | Y | When enabled and snapshots are being built (AUTO or RETURN path), bypasses market-hours gating (test accommodation) ens…
G6_SOURCE_PRIORITY_LOGS | int | 4 | Y | Priority for logs as data source.
G6_SOURCE_PRIORITY_METRICS | int | 1 | Y | Priority (lower is higher precedence) for metrics as a data source.
G6_SOURCE_PRIORITY_PANELS | int | 2 | Y | Priority for panels data source.
G6_SOURCE_PRIORITY_STATUS | int | 3 | Y | Priority for runtime_status data source.
G6_STARTUP_EXPIRY_TRACE | bool | off | Y | During orchestrator startup logs one-shot expiry matrix (rules resolved for each configured index) before first collect…
G6_STARTUP_LEGACY_PLACEHOLDERS | bool | off | Y | Emit minimal legacy placeholder artifacts/panels during early bootstrap before first full status snapshot (compatibilit…
G6_STREAM_GATE_MODE | enum(lenient|strict) | lenient | Y | Stream gating strictness.
G6_STREAM_STALE_ERR_SEC | int | 120 | Y | Error threshold seconds since last data update.
G6_STREAM_STALE_WARN_SEC | int | 60 | Y | Warning threshold seconds since last data update.
G6_STRIKE_CLUSTER | bool | off | Y | Enable experimental strike clustering heuristic in collectors (groups strikes before selection logic). Diagnostic / tun…
G6_STRIKE_COVERAGE_OK | float | 0.75 | Y | Strike coverage threshold (0-1) for classifying an expiry OK (fraction of requested strikes realized). Lower to relax O…
G6_STRIKE_POLICY | bool | off | Y | Enable legacy strike policy tuning logic (superseded by adaptive strike scaling but still available for parity runs).
G6_STRIKE_POLICY_COOLDOWN | int | 0 | Y | Minimum cycles between successive policy adjustments (prevents oscillation).
G6_STRIKE_POLICY_MAX_ITM | int | 0 | Y | Hard cap ITM strikes for policy (0 unlimited / config default).
G6_STRIKE_POLICY_MAX_OTM | int | 0 | Y | Hard cap OTM strikes for policy.
G6_STRIKE_POLICY_STEP | int | 0 | Y | Adjustment step (strikes) when policy expands or contracts.
G6_STRIKE_POLICY_TARGET | int | 0 | Y | Baseline per-side strike depth target for policy planner.
G6_STRIKE_POLICY_WINDOW | int | 0 | Y | Sliding performance window for evaluating strike policy adjustments (0 disables windowed evaluation).
G6_STRIKE_UNIVERSE_CACHE_SIZE | int | 0 | Y | Cache size limit for strike universe candidate sets (0 unlimited).
G6_SUMMARY_ALERTS_LOG_MAX | int | 500 | Y | Maximum number of alert entries retained in rolling `data/panels/alerts_log.json`. Older entries trimmed when snapshot…
G6_SUMMARY_ALT_SCREEN | bool | off | Y | Use alternate screen buffer for richer terminal rendering (default on; set 0 to disable)
G6_SUMMARY_AUTO_FULL_RECOVERY | bool | on | Y | Enable automatic recovery to full refresh after degraded cycles (set 0 to require manual intervention)
G6_SUMMARY_BACKOFF_BADGE_MS | int | 0 | Y | Milliseconds window for backoff severity badge decay (default 120000)
G6_SUMMARY_CURATED_MODE | bool | off | Y | Enable curated (reduced/noise-filtered) summary presentation mode
G6_SUMMARY_DOSSIER_INTERVAL_SEC | int | 0 | Y | Interval in seconds between dossier snapshot writes (default 5)
G6_SUMMARY_DOSSIER_PATH | path | (unset) | Y | Path for dossier JSON output (omit to disable dossier emission)
G6_SUMMARY_META_REFRESH_SEC | int | 0 | Y | Override metadata panel refresh cadence; applied only when unified refresh specified
G6_SUMMARY_MODE | str | (auto) | Y | Select summary layout/mode variant (e.g. 'minimal','full'); leave unset for default adaptive
G6_SUMMARY_REFRESH_SEC | int | 5 | Y | Unified refresh cadence (seconds) for summary loops; overrides per-type defaults when set
G6_SUMMARY_RES_REFRESH_SEC | int | 30 | Y | Override resource panel refresh cadence; applied only when unified refresh specified
G6_SUMMARY_RICH_DIFF | bool | off | Y | Enable rich diff demo panel instrumentation (experimental visual diff counters)
G6_SUMMARY_SSE_TIMEOUT | float | 45 | Y | SSE client read timeout in seconds for terminal consumer (default 45)
G6_SUMMARY_SSE_TYPES | csv | panel_full,panel_diff | Y | Comma list of SSE event types to consume (default panel_full,panel_diff)
G6_SUMMARY_STATUS_FILE | path | data/runtime_status.json | Y | Path to runtime status JSON consumed by summary (default data/runtime_status.json)
G6_SUMMARY_THRESH_OVERRIDES | JSON | (unset) | Y | JSON object of threshold overrides for badges/alerts
G6_SUMMARY_UNIFIED_SNAPSHOT | N (deprecated) | Legacy gate for unified snapshot model; retained only for deprecation tracking
G6_SUMMARY_PANELS_MODE | N (removed) | Legacy panels/plain mode selector replaced by auto-detect of panels dir
G6_SUMMARY_READ_PANELS | N (removed) | Legacy flag for reading existing panels directory; superseded by automatic behavior
G6_SUPPRESS_CLOSED_METRICS | bool | off | Y | Suppress metrics emission when market closed.
G6_SUPPRESS_DEPRECATED_WARNINGS | bool | off | Y | Suppress deprecation warnings emitted by deprecated legacy scripts (currently `scripts/terminal_dashboard.py`; may exte…
G6_SYMBOL_MATCH_MODE | enum(legacy|strict|loose) | legacy | Y | Matching algorithm variant.
G6_SYMBOL_MATCH_SAFEMODE | bool | off | Y | Additional validation / fallback path.
G6_SYMBOL_MATCH_UNDERLYING_STRICT | bool | off | Y | Enforce strict underlying symbol match rules (reject partial/ambiguous matches).
G6_TERMINAL_MODE | enum(plain|rich) | (auto) | Y | Force terminal renderer backend.
G6_TEST_CONFIG | path | config/g6_config.json | Y | Override configuration path used by orchestrator test fixtures (run_orchestrator_cycle); allows pointing to alt minimal…
G6_TEST_TIME_HARD | float | 30.0 | Y | Hard per-test runtime ceiling (seconds). Tests exceeding this duration trigger an immediate failure (after best-effort…
G6_TEST_TIME_SOFT | float | 5.0 | Y | Soft per-test runtime budget (seconds). When exceeded a non-failing warning is emitted by the autouse timing guard fixt…
G6_TIME_TOLERANCE_SECONDS | int | 1 | Y | Timestamp tolerance in overlay alignment.
G6_TRACEMALLOC_SNAPSHOT_DIR | path | (none) | Y | Directory to store tracemalloc snapshots.
G6_TRACEMALLOC_TOPN | int | 25 | Y | Top N allocations to report in snapshot.
G6_TRACEMALLOC_WRITE_SNAPSHOTS | bool | off | Y | Enable periodic tracemalloc snapshot writes.
G6_TRACE_AUTO_DISABLE | bool | off | Y | Auto-disable verbose trace flags after first N cycles (internal experimental safety; if implemented logs de-escalation)…
G6_TRACE_COLLECTOR | bool | off | Y | Verbose per-index/per-expiry collector path tracing (high volume; diagnostics only).
G6_TRACE_EXPIRY | bool | off | Y | Emit detailed trace logs of expiry candidate selection in collectors (diagnostic noise; enable only temporarily).
G6_TRACE_EXPIRY_PIPELINE | bool | off | Y | Emit per-expiry stage counts (post_fetch, post_enrich, post_validate) and intermediate pruning reasons at INFO/DEBUG ev…
G6_TRACE_EXPIRY_SELECTION | bool | off | Y | Emit per-index detailed TRACE logs of rule->date mapping decisions (candidate list, filtered list, rule outcome). Usefu…
G6_TRACE_OPTION_MATCH | bool | off | Y | Emit per-option acceptance TRACE diagnostics (reason counts + samples) in provider filtering.
G6_TRACE_QUOTES | bool | off | Y | Verbose per-quote emission tracing inside provider interface (logs raw quote objects / transformations). High volume; e…
G6_UNIFIED_METRICS | bool | off | Y | Enable unified summary metrics emission (PanelsWriter / summary plugins) producing aggregated metrics families otherwis…
G6_UNIFIED_MODEL_INIT_DEBUG | bool | off | Y | Verbose initialization logging for unified model snapshot builder.
G6_USE_MOCK_PROVIDER | bool | off | Y | Force mock provider.
G6_VALIDATION_BYPASS | bool | off | Y | When enabled, skips preventive validation drop logic (all rows pass through; issues list replaced with ['bypassed']). U…
G6_VERBOSE_CONSOLE | bool | off | Y | Force full log line formatting even in concise mode.
G6_VERSION | str | (auto) | Y | Override version label (build info metric).
G6_VOL_SURFACE_BUCKETS | csv | (unset) | Y | Override default volatility surface moneyness bucket edges (comma separated). Empty/unset => internal defaults.
G6_VOL_SURFACE_INTERPOLATE | bool | off | Y | When enabled, fills internal missing moneyness buckets by linear interpolation between existing neighboring buckets (ad…
G6_VOL_SURFACE_MAX_OPTIONS | int | 0 | Y | Hard cap on options processed for surface build (0 unlimited; rely on upstream filters).
G6_VOL_SURFACE_MODEL | bool | off | Y | Enable model phase timing scaffold (records `g6_vol_surface_model_build_seconds` when active) for future advanced model…
G6_VOL_SURFACE_PERSIST | bool | off | Y | Persist latest volatility surface artifact to `G6_ANALYTICS_DIR` as `vol_surface.latest.json[.gz]` (gzip when compressi…
G6_VOL_SURFACE_PER_EXPIRY | bool | off | Y | Enable per-expiry volatility surface metrics (row counts & interpolated fraction per expiry). Adds labelled metrics; of…
G6_WARN_LEGACY_METRICS_IMPORT | bool | off | Y | Emit a deprecation warning when `src.metrics.metrics` is imported directly (encourages facade adoption). Set to 1/true…
G6_WEB_PORT | int | 0 | Y | Port for lightweight HTTP endpoints (0=auto/random or disabled).
G6_WEEKDAY_OVERLAYS_HTML | path | weekday_overlays.html | Y | Output HTML path for weekday overlays (legacy dashboard).
G6_WEEKDAY_OVERLAYS_META | path | weekday_overlays_meta.json | Y | Output metadata path for weekday overlays (legacy dashboard).
G6_WEEKLY_EXPIRY_DOW | int | 3 | Y | Override expected weekday (0=Mon..6=Sun) for weekly expiry anchor selection when heuristics ambiguous.
G6_WRITE_CONFIG_DOC_BASELINE | bool | off | Y | When set, writes (or rewrites) config documentation baseline snapshot for governance tooling (developer use only; CI de…
G6_WRITE_CONFIG_SCHEMA_DOC_BASELINE | bool | off | Y | Similar baseline emitter for schema doc coverage governance.

## Undocumented (present in code but missing from env_dict.md)

Name | Referenced | Rationale
--- | --- | ---
G6_ADAPTIVE_MEMORY_TIER | Y | needs docs
G6_ALERTS_EMBED_LEGACY | Y | needs docs
G6_ALERT_LIQ_MIN_RATIO | Y | needs docs
G6_ALERT_SPREAD_PCT | Y | needs docs
G6_ALERT_STALE_SEC | Y | needs docs
G6_ALLOW_LEGACY_PANELS_BRIDGE | Y | needs docs
G6_ALLOW_LEGACY_SCAN | Y | needs docs
G6_ANALYTICS_DIR | Y | needs docs
G6_ASYNC_PERSIST | Y | needs docs
G6_BENCHMARK_DUMP | Y | needs docs
G6_CIRCUIT_METRICS_INTERVAL | Y | needs docs
G6_CONTRACT_MULTIPLIER_NIFTY | Y | needs docs
G6_CSV_BATCH_FLUSH | Y | needs docs
G6_CSV_BUFFER_SIZE | Y | needs docs
G6_CSV_DEDUP_ENABLED | Y | needs docs
G6_CSV_DQ_MIN_POSITIVE_COUNT | Y | needs docs
G6_CSV_DQ_MIN_POSITIVE_FRACTION | Y | needs docs
G6_CSV_FLUSH_INTERVAL | Y | needs docs
G6_CSV_FLUSH_NOW | Y | needs docs
G6_CSV_JUNK_DEBUG | Y | needs docs
G6_CSV_JUNK_MIN_LEG_OI | Y | needs docs
G6_CSV_JUNK_MIN_LEG_VOL | Y | needs docs
G6_CSV_MAX_OPEN_FILES | Y | needs docs
G6_CSV_PRICE_SANITY | Y | needs docs
G6_CYCLE_INTERVAL | Y | needs docs
G6_DIAG_EXIT | Y | needs docs
G6_DISABLE_PER_OPTION_METRICS | Y | needs docs
G6_ENABLE_METRIC_GROUPS | Y | needs docs
G6_ENV_DOC_STRICT | Y | needs docs
G6_EXPIRY_MISCLASS_DEBUG | Y | needs docs
G6_EXPIRY_MISCLASS_DETECT | Y | needs docs
G6_EXPIRY_MISCLASS_POLICY | Y | needs docs
G6_EXPIRY_MISCLASS_SKIP | Y | needs docs
G6_EXPIRY_QUARANTINE_DIR | Y | needs docs
G6_EXPIRY_QUARANTINE_MAX_DAYS | Y | needs docs
G6_EXPIRY_QUARANTINE_SUMMARY | Y | needs docs
G6_EXPIRY_REWRITE_ANNOTATE | Y | needs docs
G6_EXPIRY_SERVICE | Y | needs docs
G6_EXPIRY_SUMMARY_INTERVAL_SEC | Y | needs docs
G6_FEATURES_ANALYTICS_STARTUP | Y | needs docs
G6_FEATURES_FANCY_STARTUP | Y | needs docs
G6_FEATURES_LIVE_PANEL | Y | needs docs
G6_FOO_BAR | Y | needs docs
G6_FORCE_UNIFIED_PANELS_WRITE | Y | needs docs
G6_HEALTH_API_ENABLED | Y | needs docs
G6_HEALTH_API_HOST | Y | needs docs
G6_HEALTH_API_PORT | Y | needs docs
G6_LATENCY_PROFILING | Y | needs docs
G6_LEGACY_COLLECTOR | Y | needs docs
G6_MEMORY_TIER_OVERRIDE | Y | needs docs
G6_METRICS_ENABLE | Y | needs docs
G6_METRICS_VERBOSE | Y | needs docs
G6_PANELS_BRIDGE_PHASE | Y | needs docs
G6_PANELS_BRIDGE_SUPPRESS | Y | needs docs
G6_PARALLEL_COLLECTION | Y | needs docs
G6_PARTIAL_REASON_HIERARCHY | Y | needs docs
G6_RISK_AGG | Y | needs docs
G6_RUNTIME_FLAGS | Y | needs docs
G6_SCHEMA_STRICT | Y | needs docs
G6_SKIP_ENV_DOC_VALIDATION | Y | needs docs
G6_STATUS_FILE | Y | needs docs
G6_STORAGE_CSV_DIR | Y | needs docs
G6_STORAGE_INFLUX_BUCKET | Y | needs docs
G6_STORAGE_INFLUX_ENABLED | Y | needs docs
G6_STORAGE_INFLUX_ORG | Y | needs docs
G6_STORAGE_INFLUX_URL | Y | needs docs
G6_STRICT_MODULE_IMPORTS | Y | needs docs
G6_STRIKE_STEP_NIFTY | Y | needs docs
G6_SUMMARY_AGG_V2 | Y | needs docs
G6_SUMMARY_ALERT_DEDUPE | Y | needs docs
G6_SUMMARY_ALERT_LOG_BACKUPS | Y | needs docs
G6_SUMMARY_ALERT_LOG_MAX_MB | Y | needs docs
G6_SUMMARY_ANOMALY | Y | needs docs
G6_SUMMARY_CONTROLLER_META | Y | needs docs
G6_SUMMARY_DOSSIER_INTERVAL | Y | needs docs
G6_SUMMARY_EVENT_DEBOUNCE_MS | Y | needs docs
G6_SUMMARY_FOLLOWUP_SPARK | Y | needs docs
G6_SUMMARY_HEADER_ENH | Y | needs docs
G6_SUMMARY_HIDE_EMPTY_BLOCKS | Y | needs docs
G6_SUMMARY_HISTORY_FILE | Y | needs docs
G6_SUMMARY_HISTORY_FILE_MAX_MB | Y | needs docs
G6_SUMMARY_HISTORY_SIZE | Y | needs docs
G6_SUMMARY_LEGACY | Y | needs docs
G6_SUMMARY_MAX_LINES | Y | needs docs
G6_SUMMARY_MEM_PROJECTION | Y | needs docs
G6_SUMMARY_METRICS | Y | needs docs
G6_SUMMARY_PANEL_ISOLATION | Y | needs docs
G6_SUMMARY_PARITY | Y | needs docs
G6_SUMMARY_RICH_MODE | Y | needs docs
G6_SUMMARY_ROOT_CAUSE | Y | needs docs
G6_SUMMARY_SCHEMA_ENFORCE | Y | needs docs
G6_SUMMARY_SCORING | Y | needs docs
G6_SUMMARY_SEVERITY_BADGE | Y | needs docs
G6_SUMMARY_SPARKLINES | Y | needs docs
G6_SUMMARY_THEME | Y | needs docs
G6_SUMMARY_TRENDS | Y | needs docs
G6_SUMMARY_UNIFIED_SNAPSHOT | Y | needs docs
G6_SUMMARY_V2_ONLY | Y | needs docs
G6_SUPPRESS_BENCHMARK_DEPRECATED | N (deprecated alias) | Legacy per-script suppression; auto-mapped to G6_SUPPRESS_DEPRECATIONS (remove R+1)
G6_SUPPRESS_DEPRECATED_RUN_LIVE | N (deprecated alias) | Legacy suppression for run_live script deprecation banner; auto-mapped; remove R+1
G6_SUPPRESS_DEPRECATIONS | Y | Global suppression for non-critical deprecation warnings (set to 1/true/yes/on to silence)
G6_SUPPRESS_EXPIRY_MATRIX_WARN | Y | Suppress noisy expiry matrix heuristic warnings (use sparingly; default surfaces guidance)
G6_SUPPRESS_KITE_DEPRECATIONS | Y | Suppress broker integration deprecation banners (transitional)
G6_SUPPRESS_LEGACY_METRICS_WARN | Y | Suppress legacy metrics access or alias deprecation warnings (migration aid)
G6_TOKEN_HEADLESS | Y | needs docs
G6_TOKEN_PROVIDER | Y | needs docs
G6_TRACE_METRICS | Y | needs docs
G6_VOL_SURFACE | Y | needs docs
G6_WRITE_ENV_DOC_BASELINE | Y | needs docs
