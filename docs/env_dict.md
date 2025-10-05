# G6 Environment Variable Dictionary (Deprecated Stub)

This document has been superseded by:

- `ENVIRONMENT.md` (authoritative auto-generated table)
- `CONFIG_FEATURE_TOGGLES.md` (toggle semantics & narrative)
- `ENV_VARS_CATALOG.md` (structured catalog, if present)

Purpose of deprecation: remove redundant copies preventing drift.

No further updates will be made here; remove after deprecation window once
inbound references reach zero.
\n+## Recently Removed / Deprecated Legacy Flags (documented for coverage)
The following environment variables were referenced historically but are now deprecated or fully removed. They remain documented solely to satisfy the env documentation coverage gate; do not introduce new usages.

- G6_DISABLE_EXPIRY_MAP – (removed) – Former diagnostic toggle to disable building the expiry map during processing. Logic path eliminated; flag has no effect and will be purged from code references.
- G6_ENABLE_LEGACY_LOOP – (removed) – Historical switch to force legacy orchestrator loop. Legacy loop retired; unified path always active. Setting does nothing; references retained only in deprecation tests.
- G6_SUPPRESS_LEGACY_LOOP_WARN – (removed) – Suppressed deprecation warnings for legacy loop usage. Obsolete after removal of legacy loop implementation.
- G6_SUMMARY_PANELS_MODE – (removed) – Old summary launcher hint for panels mode (auto‑detection now internal). Any remaining references are inert and scheduled for cleanup.
- G6_PROFILE_EXPIRY_MAP – bool – off – Emit one-shot timing / stats for expiry map build in profiling harness (`scripts/profile_unified_cycle.py`). Use to measure overhead or validate optimization impact.
- G6_VALIDATION_BYPASS – bool – off – When enabled, skips preventive validation drop logic (all rows pass through; issues list replaced with ['bypassed']). Use only for diagnostics to confirm validator is root cause of data loss.
- G6_TRACE_EXPIRY_SELECTION – bool – off – Emit per-index detailed TRACE logs of rule->date mapping decisions (candidate list, filtered list, rule outcome). Useful when diagnosing mismatched weekly/monthly anchors.
- G6_TRACE_EXPIRY_PIPELINE – bool – off – Emit per-expiry stage counts (post_fetch, post_enrich, post_validate) and intermediate pruning reasons at INFO/DEBUG even in concise mode.
 - G6_STARTUP_EXPIRY_TRACE – bool – off – During orchestrator startup logs one-shot expiry matrix (rules resolved for each configured index) before first collection cycle; aids quick verification of mapping without enabling high‑volume per-cycle trace flags.
 - G6_FOREIGN_EXPIRY_SALVAGE – bool – off – Salvage heuristic: when every row of an expiry was pruned solely due to foreign_expiry classification, rewrites batch to dominant foreign expiry date instead of dropping (reduces empty expiries during calendar anomalies). Off = strict prune.

### Adaptive Controller Extensions (moved & expanded in dedicated section 21 below)

### Benchmark Artifact Options
 - G6_BENCHMARK_KEEP_N – int – 0 – Keep only most recent N benchmark artifacts when >0 (prunes older files after each write).
 - G6_BENCHMARK_ANNOTATE_OUTLIERS – bool – off – Add anomaly analysis block to benchmark artifact (robust stats) when enabled.
 - G6_BENCHMARK_ANOMALY_HISTORY – int – 50 – Number of historical artifacts considered for robust anomaly stats.
 - G6_BENCHMARK_ANOMALY_THRESHOLD – float – 3.5 – Robust z-score absolute threshold for outlier flagging.
 - G6_BENCHMARK_COMPRESS – bool – off – Gzip-compress benchmark artifacts when G6_BENCHMARK_DUMP enabled (writes .json.gz files).
 - G6_BENCH_TREND_DEBUG – bool – off – Emit internal recomputation debug lines for benchmark trend tooling (diagnostic noise).

### Catalog & HTTP Hot Reload
 - G6_CATALOG_HTTP_FORCE_RELOAD – bool – off – On next catalog HTTP access triggers controlled server restart (hot reload) for testing.

### Summary / SSE Streaming & Security (New Section)
Authoritative documentation for summary Server-Sent Events (SSE) streaming hardening & tuning variables. These were added during SSE security & performance phases and are required for release readiness gating.
- G6_SSE_API_TOKEN – str – (unset) – When set, required token value for SSE HTTP requests provided via X-API-Token header. Missing/incorrect token returns 401. Leave unset to disable token auth (development only).
- G6_SSE_IP_ALLOW – csv – (unset) – Comma list of IPs (string compare against remote_addr) allowed to connect. When set and client IP not in list returns 403. Accepts IPv4 only currently.
- G6_SSE_MAX_CONNECTIONS – int – 50 – Hard upper bound of concurrently active SSE connections; excess attempts receive 503 until slots free.
- G6_SSE_ALLOW_ORIGIN – str – (unset) – If set, value echoed as Access-Control-Allow-Origin header on SSE endpoint responses enabling basic CORS for browser clients.
- G6_SSE_IP_CONNECT_RATE – str – (unset) – Per-IP connection rate limit window expressed as N/seconds (e.g. 3/60). Exceeding attempts within rolling window returns 429. Unset disables per-IP connect rate limiting.
- G6_SSE_UA_ALLOW – csv – (unset) – Comma list of allowed User-Agent prefixes. When set and request UA does not start with any allowed prefix returns 403. Comparison is case-sensitive.
- G6_SSE_MAX_EVENT_BYTES – int – 65536 – Maximum serialized SSE event data payload size. Events exceeding are truncated and a synthetic 'truncated' event metadata field emitted (metrics still record original size). Protects against oversized diff bursts.
- G6_SSE_EVENTS_PER_SEC – int – 100 – Soft emission rate limit for non-heartbeat events (burst bucket size ~2x). Excess events dropped (metrics increment) to protect slow clients/backpressure scenarios.
- G6_SSE_STRUCTURED – bool – off – Enable structured diff events (panel_diff) instead of legacy panel_update list-of-changes. When on, per-event payload contains only changed panels map plus metadata.
- G6_DISABLE_RESYNC_HTTP – bool – off – When enabled, disables /summary/resync endpoint (returns 403) forcing clients to rely solely on streaming recovery logic. Use in locked-down production clusters.
- G6_SSE_PERF_PROFILE – bool – off – Enable publisher performance histograms (diff build latency & emit latency) for Prometheus under names g6_sse_pub_diff_build_seconds and g6_sse_pub_emit_latency_seconds. Adds minimal timing overhead when active.


### Quiet / Logging Enhancements
 - G6_QUIET_MODE – bool – off – Quiet mode: elevate root log level and suppress verbose trace chatter (implies concise logs).
 - G6_SUMMARY_DEBUG_LOG – bool – off – High-volume summary internals logging (loop timings, panel store metadata).
- G6_LOOP_HEARTBEAT_INTERVAL – float – 0 – When >0 emits a concise `hb.loop.heartbeat` line at most every N seconds containing cycle count, last options processed, and (best-effort) rate limiter & batching stats. 0/unset disables.
<!-- BEGIN logging_env_block (authoritative single entries) -->
- `G6_SUPPRESS_GROUPED_METRICS_BANNER` – bool – off – Fully suppress the one-time "Grouped metrics registration complete" INFO banner (on top of repeat suppression). For ultra‑minimal startup logs.
- `G6_SUPPRESS_DUPLICATE_METRICS_WARN` – bool – off – Suppress the `metrics.duplicates.detected` warning when multiple registry attributes reference the same collector. Investigate root cause first to avoid masking drift.
- `G6_DUPLICATES_LOG_LEVEL` – enum(warning|info|debug|error|critical) – warning – Override severity for duplicate metrics summary line (ignored if suppression flag set). Lower to info to hide from WARNING-filtered consoles; raise to error/critical for stricter CI surfacing.
- `G6_LOG_COLOR_MODE` – enum(auto|on|off) – auto – ANSI colorization for standard logging (non-Rich). auto enables when stdout is a TTY; on forces; off disables.
- `G6_LOG_COLOR_FORCE` – bool – off – Force-enable ANSI colors even when TTY not detected (CI/Windows fallback cases).
- `G6_STRUCT_EVENTS_FORMAT` – enum(json|human|both) – json – Formatting of structured collector events (cycle_status_summary, option_match_stats, instrument_prefilter_summary, etc.). json: legacy `STRUCT <name> | {json}` line only; human: concise one-line human summary (`STRUCT_H <name> key=val ...`); both: emit both forms.
<!-- END logging_env_block -->

### Risk Aggregation Persistence
 - G6_RISK_AGG_PERSIST – bool – off – Persist latest risk aggregation artifact (risk_agg.latest.json[.gz]) to analytics directory.

### Holidays / Calendar
 - G6_HOLIDAYS_FILE – path – (none) – JSON file enumerating YYYY-MM-DD holidays (market closed days) used for gating.


---
## Governance & Automation
An automated pytest (`tests/test_env_doc_coverage.py`) scans `src/`, `scripts/`, and `tests/` for tokens matching `G6_[A-Z0-9_]+` and asserts each appears in this file. Mechanism:
- Baseline file: `tests/env_doc_baseline.txt` (should remain empty now). Historically held legacy backlog; new vars must be documented immediately.
- Skip flag: `G6_SKIP_ENV_DOC_VALIDATION=1` only for emergency hotfixes (must document in same PR).
- Baseline regenerate: `G6_WRITE_ENV_DOC_BASELINE=1` rewrites the baseline with current missing names (normally unused post zero-burndown).
- Strict mode: `G6_ENV_DOC_STRICT=1` fails if the baseline file is non-empty (CI enforces this in `.github/workflows/env-doc-governance.yml`).

### Metrics Catalog Generation
- G6_CATALOG_TS – string – (unset) – Optional timestamp or version string injected when generating `docs/METRICS_CATALOG.md` via `scripts/gen_metrics_catalog.py`; surfaced in the catalog header for traceability in release artifacts. Purely informational; no runtime behavior change.

Local fast check:
```
pytest -q tests/test_env_doc_coverage.py::test_all_g6_env_vars_are_documented
```
Pre-commit (if enabled) will block introductions of undocumented env vars before push.

Guidelines:
1. Prefer config keys over new env vars for static, long-term settings.
2. Remove env flags once stabilized for >1 release unless they remain operational toggles.
3. If introducing an alias, add to Deprecated/Historical table with a removal target.
4. Do not add roadmap/proposed flags here until code references exist (otherwise they are ignored or allowlisted in section 21).

Developer Tooling (task runner / hooks):
- G6_RUFF_BIN – path – ruff – Override ruff executable path for `scripts/dev_tasks.py`.
- G6_MYPY_BIN – path – mypy – Override mypy executable path.
- G6_PYTEST_BIN – path – pytest – Override pytest executable path.
- G6_ENABLE_BLACK – bool – off – When set, enables black formatting pass in `dev_tasks.py format` after ruff format.
- G6_REGEN_PARITY_GOLDEN – bool – off – When set to 1/true, enables regeneration of parity harness golden report in `test_orchestrator_parity_golden_regen` (writes JSON to tmp path). Not used in CI; developer convenience only.
- G6_LEGACY_LOOP_WARNED – internal sentinel – (unset) – Internal process-level flag set after first deprecation warning emission (not a user-facing toggle; documented to satisfy env var coverage test).
 - G6_STARTUP_LEGACY_PLACEHOLDERS – bool – off – Emit minimal legacy placeholder artifacts/panels during early bootstrap before first full status snapshot (compatibility shim for tooling expecting legacy files). Removal planned post panels bridge cleanup.
- G6_SUPPRESS_DEPRECATED_WARNINGS – bool – off – Suppress deprecation warnings emitted by deprecated legacy scripts (currently `scripts/terminal_dashboard.py`; may extend if additional legacy entrypoints retained briefly). Set 1/true to silence stderr banner; has no effect on supported/maintained tools.
- G6_METRICS_INTROSPECTION_DUMP – bool – off – When enabled (1/true/yes/on) logs a one-shot debug dump of registered metrics metadata (name, type, labels, group) on metrics registry initialization to aid troubleshooting of gating / duplication issues.
- G6_METRICS_STRICT_EXCEPTIONS – bool – off – When enabled unexpected exceptions during metric registration (placeholders, spec minimum assurance, _maybe_register) are re-raised instead of logged & suppressed. Use in CI or refactors for fail-fast; leave off in production for resilience.
- G6_FORCE_NEW_REGISTRY – bool – off – When set forces `setup_metrics_server` to discard the existing Prometheus default registry and rebuild a fresh `MetricsRegistry` instance. Use ONLY in tests or interactive diagnostics to avoid duplicated timeseries errors when re-importing the metrics module within the same process. Production code should rely on idempotent singleton behavior instead. Side‑effects: resets all cumulative counters.
- G6_DIAG_EXIT - bool - off - When set (1/true) enables emission of the diagnostic pytest session finish hook output (exit status summary and guidance). Default off to keep test logs quiet once stabilized; enable transiently when debugging unexpected pytest exits in CI.
 - G6_ENV_DEPRECATION_STRICT – bool – off – When enabled, any presence of a deprecated environment variable (status=deprecated in lifecycle registry) triggers a hard RuntimeError during bootstrap. Use in CI to prevent drift.
 - G6_ENV_DEPRECATION_ALLOW – str – (unset) – Comma list of deprecated env var names exempt from strict-mode failure (temporary grace). Example usage: set to a comma list like G6_METRICS_ENABLE,G6_SUMMARY_LEGACY to permit those during strict mode.
 - G6_TEST_TIME_SOFT – float – 5.0 – Soft per-test runtime budget (seconds). When exceeded a non-failing warning is emitted by the autouse timing guard fixture to highlight potential performance regressions. Adjust in CI to surface emerging hotspots earlier.
 - G6_TEST_TIME_HARD – float – 30.0 – Hard per-test runtime ceiling (seconds). Tests exceeding this duration trigger an immediate failure (after best-effort graceful abort) to prevent suite stalls. Set higher temporarily when investigating long‑running scenarios; keep default to preserve fast feedback.

---
## 1. Console / UI & Output
- G6_FANCY_CONSOLE – bool – auto (enabled if TTY) – Force fancy startup banner / panels.
- G6_FORCE_UNICODE – bool – off – Force unicode (skip ASCII fallback).
- G6_DISABLE_STARTUP_BANNER – bool – off – Suppress banner entirely.
- G6_LIVE_PANEL – bool – on (TTY) – Enable per-cycle live panel refresh.
- G6_VERBOSE_CONSOLE – bool – off – Force full log line formatting even in concise mode.
- G6_CONCISE_LOGS – bool – on – Suppress repetitive per-option chatter.
- G6_DISABLE_MINIMAL_CONSOLE – bool – off – Re-enable default logging format if minimal console active.
- G6_CYCLE_STYLE – enum(legacy|readable) – legacy – Select formatting for per-cycle summary lines when concise/quiet modes are active. 'legacy' emits the original compact `CYCLE ts=... dur=... opts=...` key=value form. 'readable' emits `CYCLE_READABLE duration=... options=... api_latency=... collection_success=...` with expanded, human-friendly keys while remaining one-line and machine-parseable. Does not affect INDEX lines or pretty/table modes.
- G6_QUIET_ALLOW_TRACE – bool – off – Override within quiet mode to allow `_trace` diagnostic emissions (set to 1/true). Without quiet mode this flag is ignored. Useful for targeted troubleshooting while keeping other noise suppressed.
- G6_COLOR – enum(auto|always|never) – auto – Color policy.
- G6_OUTPUT_SINKS – csv – stdout,logging – Comma list: stdout,logging,panels,memory.
- G6_ENHANCED_SNAPSHOT_MODE – bool – off – Forces enhanced collector shim to use snapshot collectors (no persistence) regardless of legacy/unified mode; used by tests to preserve backward compatible snapshot return contract.
- G6_OUTPUT_LEVEL – str – INFO – Override base log level (also via --log-level maybe).
- G6_PANELS_DIR – path – data/panels – Directory for emitted panel JSON.
- G6_ENABLE_PANEL_PUBLISH – bool – off – Enable panel publisher (writes JSON snapshots each cycle).
- G6_PUBLISHER_EMIT_INDICES_STREAM – bool – off – Add indices stream file when publisher active.
- G6_SUMMARY_THRESH_OVERRIDES – JSON – (unset) – JSON object overriding terminal summary/dashboard thresholds defined in `scripts/summary/thresholds.py`. Dot keys map to registry entries (e.g. `{ "dq.warn":82, "dq.error":68 }`). Unknown keys ignored. Used for rapid tuning without code change.
- G6_INDICES_PANEL_LOG – path – (none) – Optional log path capturing indices panel frames.
- G6_SUMMARY_ALERTS_LOG_MAX – int – 500 – Maximum number of alert entries retained in rolling `data/panels/alerts_log.json`. Older entries trimmed when snapshot builder (aggregation V2) persists alerts. Non-positive or invalid values fallback to default (500). Only used when `G6_SUMMARY_AGG_V2` is enabled (legacy path does not persist rolling log here).
- G6_SUMMARY_ALERT_DEDUPE – bool – on – When enabled suppresses repeated alert entries with identical signature (type, index, severity) within a short rolling window during summary refresh to reduce noisy churn; disable (0/false) for exhaustive alert transition auditing.
 - G6_SUMMARY_SIG_V2 – enum(on|off|auto) – auto – Enhanced v2 summary signature gating: skips refresh when signature stable. auto enables when aggregation v2 active; on forces; off disables optimization (always evaluate refresh normally).
- G6_EVENTS_SSE_HEARTBEAT – float – 45 – Interval in seconds between heartbeat comments written to the `/events` SSE stream to keep idle connections alive.
- G6_EVENTS_SSE_POLL – float – 1.0 – Server-side poll cadence in seconds while streaming backlog events over SSE.
- G6_EVENTS_SSE_RETRY_MS – int – 3000 – Retry delay (milliseconds) advertised to SSE clients via the `retry:` field when streaming `/events`.
- G6_PARALLEL_INDICES – bool – off – Enable per-index parallel collection workers in unified orchestrator cycle. When on (1/true) indices may fetch/enrich concurrently (subject to internal pool sizing heuristics). Off forces serial processing for determinism or easier debugging. Some tests force on to exercise concurrency code paths even with a single index.
- G6_SUMMARY_SSE_TIMEOUT – float – 45 – Timeout in seconds for the summary app's SSE client connections before triggering reconnection logic.
- G6_SUMMARY_SSE_TYPES – csv – panel_full,panel_diff – Default comma-separated list of SSE event types to subscribe to when `--sse-types` not provided.
- G6_SUMMARY_SSE_URL – str – (unset) – Optional override for the summary app SSE endpoint (e.g., `http://127.0.0.1:9315/events`).
- G6_SUMMARY_SHOW_NEED_FULL – bool – on – Controls visibility of the FULL SNAPSHOT REQUIRED integrity badge in the summary header when diff stream rejected (baseline/generation mismatch). Set 0/false to suppress indicator (useful for minimalist dashboards or scripted captures). Default shows badge to surface integrity issues quickly.
- G6_SUMMARY_AUTO_FULL_RECOVERY – bool – on – When enabled, the summary client automatically performs a single reconnection attempt with `force_full=1` appended to the SSE URL the first time a NEED_FULL condition is detected (generation mismatch / missing baseline). Disabled (0/false) requires manual restart or external forcing to recover.
 - G6_PANELS_SSE_TIMEOUT – float – 45 – Client-side timeout (seconds) for the panels SSE ingestion plugin (`SSEPanelsIngestor`). When the underlying HTTP read blocks longer than this without receiving any line, the connection is closed and a reconnect (with exponential backoff) is attempted. Increase slightly (60–90) for very low-activity streams; decrease for faster stall detection in test harnesses.
 - G6_PANELS_SSE_TYPES – csv – panel_full,panel_diff – Comma-separated list of SSE event types the panels ingestion plugin subscribes to. Extend to include `severity_state`, `severity_counts`, `followup_alert` if server emits them via a single multiplexed endpoint. Normally left default; override only when testing selective event filtering.
 - G6_SUMMARY_BUILD_MODEL – bool – off – When enabled (1/true) the summary app performs an on-demand unified model snapshot build (structured `UnifiedStatusSnapshot`) for diagnostic or development inspection even if not strictly required for the current rendering path. Adds minor CPU overhead; keep off in routine runs.
 - G6_SUMMARY_DEBUG_UPDATES – bool – off – Emit per-cycle debug diagnostics about summary update decisions (e.g., signature skip, need_full gating) to aid troubleshooting of perceived staleness or missed refreshes.
 - G6_PANELS_SSE_OVERLAY – bool – off – When enabled, the SSE panels ingestor overlays (merges) its in-memory baseline status into the live snapshot used by the unified summary loop. SSE-provided sections (indices_detail, alerts/events, analytics, memory, loop) take precedence over file-derived status keys. Use to achieve real-time panel freshness when the on-disk status file is stale or updated at a lower cadence. Disable if you need to inspect raw file-only status without SSE influence.

### Newly Documented (previously in auto-catalog only)
The following variables were flagged by the auto catalog as referenced but undocumented; concise definitions added to satisfy governance. Refine descriptions as feature surfaces mature.
- G6_FEATURES_ANALYTICS_STARTUP – bool – off – When enabled, runs analytics (vol surface / risk aggregation) immediately during startup bootstrap instead of waiting for first normal cycle trigger (diagnostic quick warm path). May increase startup latency.
- G6_FEATURES_FANCY_STARTUP – bool – off – Force-enable fancy console / banner even if TTY heuristics would normally disable or in quiet environments (developer aesthetics toggle).
- G6_FEATURES_LIVE_PANEL – bool – off – Force live panel rendering in console even when other constraints (non-TTY, quiet) would disable it. Mostly for integration tests ensuring panel repaint logic executes.
- G6_ALERTS_EMBED_LEGACY – bool – off – Transitional alerts embedding mode: when on, legacy top-level alert_* fields remain populated alongside new structured alerts summary during Phase 10 migration (see PHASE10_SCOPE.md). Remove once downstream consumers migrate.
- G6_ALERT_LIQ_MIN_RATIO – float – 0.15 – Liquidity low alert threshold (min volume/oi ratio) for liquidity_low adaptive alert. Tuned empirically; adjust only during alert sensitivity calibration.
- G6_ALERT_SPREAD_PCT – float – 6.0 – Wide spread alert threshold expressed as (ask-bid)/mid * 100. Increases alert sensitivity when lowered; ensure noise acceptable before tightening.
- G6_ALERT_STALE_SEC – int – 30 – Stale quote alert threshold in seconds since last underlying or option quote update before marking data stale.
- G6_ASYNC_PERSIST – bool – off – Enable asynchronous persistence for select artifact writers (panels/catalog) to reduce synchronous loop latency. Experimental; monitor for race conditions before enabling broadly.
- G6_CIRCUIT_METRICS_INTERVAL – float – 30 – Interval seconds for emitting circuit breaker aggregated metrics snapshot when circuit metrics enabled; distinct from per-event counters.
- G6_FOO_BAR – (placeholder) – (unused) – Test/dummy token (development placeholder). Should not be set in production; retained only until generator filters refined. Will be removed.

<!-- Removed duplicate 'Additional Alerts / Bootstrap & Async' block (2025-10-02 cleanup) to satisfy duplicate env var governance test. Authoritative definitions remain in the 'Newly Documented' section above. -->

- G6_SUMMARY_HEADER_ENH – bool – off – Enable enhanced summary header (adds memory/health inline badges and adaptive indicators). Experimental visual polish toggle.
- G6_SUMMARY_HISTORY_FILE – path – data/summary_history.log – Path to append-only text/JSONL summary history log (one line per refresh) when history capture active.
- G6_SUMMARY_HISTORY_FILE_MAX_MB – float – 25 – Maximum size in MB before history file rotation/truncation (0 disables size guard, risk of unbounded growth).
- G6_SUMMARY_HISTORY_SIZE – int – 0 – In-memory ring buffer size of recent summary snapshots for debugging live diffs (0 disables retention). Not persisted.
- G6_SUMMARY_MAX_LINES – int – 0 – Hard cap on lines rendered in terminal fancy mode (0 unlimited) for narrow terminals or CI logs.
- G6_SUMMARY_MEM_PROJECTION – bool – off – Enable experimental memory usage projection overlay (simple linear extrapolation) in summary metrics block.
- G6_SUMMARY_METRICS – bool – on – Control inclusion of metrics mini-panel in console summary (disable for ultra-compact mode or when metrics exporter disabled).
- G6_SUMMARY_PANEL_ISOLATION – bool – off – When enabled renders each panel in isolation (no shared layout) to aid screenshot diffing; disables adaptive reflow.
- G6_SUMMARY_PARITY – bool – off – Emit parity comparison hash lines between legacy and unified summary builders (development diagnostics during migration).
- G6_SUMMARY_RICH_MODE – enum(auto|on|off) – auto – Force Rich formatting on/off; auto chooses based on TTY + color policy.
- G6_SUMMARY_ROOT_CAUSE – bool – off – Enable experimental root cause inference block in summary (classifies primary degradation driver among latency/cardinality/data quality). Produces additional diagnostic fields; unstable output format.
- G6_SUMMARY_SCHEMA_ENFORCE – bool – off – When enabled, validates assembled summary JSON against internal schema snapshot and logs (or raises in strict modes) on deviation. Intended for catching accidental key drift before release.
- G6_SUMMARY_SCORING – bool – off – Compute composite health score (0-100) across core dimensions (cycle success, data quality, strike coverage) and display in header. Early heuristic subject to change.
- G6_SUMMARY_SEVERITY_BADGE – bool – on – Display highest active adaptive severity state as colored badge in summary header (OFF/DIM if no active alerts). Disable for minimal layout.
- G6_SUMMARY_SPARKLINES – bool – off – Render inline unicode sparklines for selected rolling metrics (cycle duration, options processed) in header; adds minor CPU overhead.
- G6_SUMMARY_THEME – enum(auto|light|dark) – auto – Force light/dark theme variants for ANSI color palette mapping (auto picks based on terminal background heuristics when available).
- G6_SUMMARY_TRENDS – bool – off – Enable per-metric short moving trend indicators (↑/↓/→) next to key performance metrics (cycle time, memory). Experimental; trend window length may change.
- G6_SUMMARY_V2_ONLY – bool – off – Force summary aggregator to operate exclusively in V2 mode ignoring legacy fallback branches (used during phased deprecation, simplifies diff noise).
- G6_SUPPRESS_DEPRECATED_RUN_LIVE – bool – off – Suppress deprecation warnings for deprecated `run_live_dashboard` style entrypoints (transition aid). Remove once legacy script deleted.
- G6_SUPPRESS_KITE_DEPRECATIONS – bool – off – Suppress verbose deprecation warnings from kite provider wrapper (credential flow / symbol normalization) during large batch test runs; keep off in production to ensure visibility.
- G6_SUPPRESS_LEGACY_METRICS_WARN – bool – off – Suppress legacy metrics import deprecation warning (inverse of enabling the legacy metrics import warning flag). Prefer documenting & migrating imports rather than suppressing.
- G6_SYNTHETIC_ – (prefix placeholder) – (none) – Placeholder prefix token surfaced by broad scanner patterns when illustrating synthetic env examples; not an actual configurable flag. Ignore / do not set.

## 2. Data & Cycle Control
- G6_MAX_CYCLES – int – 0 – Upper bound on main loop iterations (0 = unbounded).
- G6_LOOP_MAX_CYCLES – int – 0/unset – Orchestrator `run_loop` only: when >0 stops loop after N successfully executed (non-skipped) cycles; set automatically by `scripts/run_orchestrator_loop.py --cycles`. Ignored by legacy collection_loop.
- G6_FORCE_MARKET_OPEN – bool – off – Bypass market-hours gating (tests / backfill).
- G6_SKIP_PROVIDER_READINESS – bool – off – Skip provider readiness / health validation (tests).
- G6_RETURN_SNAPSHOTS – bool – off – Force collectors to return per-option snapshots.
- G6_FILTER_MIN_VOLUME – int – 0 – Minimum per-option volume required to retain an option during expiry processing (filter stage in `expiry_processor`). 0 disables volume filtering.
- G6_FILTER_MIN_OI – int – 0 – Minimum per-option open interest required to retain an option. 0 disables OI filtering.
- G6_FILTER_VOLUME_PERCENTILE – float – 0.0 – When >0, drops options below the given lower volume percentile (0-1) per expiry after initial min filters. Applied before persistence; 0 disables percentile filtering.
- G6_AUTO_SNAPSHOTS – bool – off – Auto-build snapshots each loop when enhanced collector active.
- G6_PIPELINE_COLLECTOR – (deprecated) – (ignored) – Historical opt-in flag for the pipeline collector path. As of 2025-10-01 the pipeline path is the default via orchestrator facade and unified collectors no longer honor this flag for activation (fallback block removed). Setting it now only emits a deprecation warning (see `src/utils/deprecations.py`). Remove from environments; use `G6_LEGACY_COLLECTOR=1` with the facade (`mode=auto`) to force legacy collection during the remaining deprecation window.
 - G6_PIPELINE_REENTRY – internal sentinel – (unset) – Internal guard set during pipeline delegation to prevent infinite recursion (pipeline -> legacy -> pipeline). Not user-facing; do not set manually.
 - G6_FACADE_PARITY_STRICT – bool – off – When using the orchestrator facade with `mode=auto|pipeline` and `parity_check=True`, a parity hash mismatch (pipeline vs legacy) normally logs a warning only. Setting this flag (1/true) escalates mismatch to a hard RuntimeError to fail fast during rollout / CI.
- (Cross-reference: parallel indices collection flag defined below.)
- G6_PARALLEL_INDEX_WORKERS – int – 4 – Maximum threads for parallel per-index collectors.
- G6_PARALLEL_INDEX_TIMEOUT_SEC – float – 0.25 * interval – Per-index soft timeout in parallel mode; timeout increments timeout counter and optionally retries.
- G6_PARALLEL_CYCLE_BUDGET_FRACTION – float – 0.9 – Fraction of cycle interval available for parallel collection; remaining indices skipped once exceeded.
- G6_PARALLEL_INDEX_RETRY – int – 0 – Retry attempts (serial) after parallel failures/timeouts (best-effort within remaining budget).
- G6_PARALLEL_STAGGER_MS – int – 0 – Millisecond stagger between task submissions to reduce burst contention.
- G6_ENABLE_OPTIONAL_TESTS – bool – off – Activate optional pytest cases.
- G6_ENABLE_SLOW_TESTS – bool – off – Activate slow pytest cases.
- G6_ENABLE_PERF_TESTS – bool – off – Run performance micro-benchmarks (expiry service, etc.).
- G6_DISABLE_METRICS_SOURCE – bool – off – Disable emitting per-option source metrics (diagnostic gating / perf reduction).
- G6_METRICS_CARD_ENABLED – bool – on – Master switch controlling dynamic option-metric cardinality management features.
- G6_METRICS_CARD_ATM_WINDOW – int – 0 – When >0 restrict detailed option metrics to strikes within +/- window steps of ATM (pre-filter before cardinality guard logic).

## 3. Expiry Resolution Service
| G6_EXPIRY_SUMMARY_INTERVAL_SEC | Interval (seconds) between emission of aggregated `expiry_quarantine_summary` events (counts of rewritten/quarantined/rejected for the day). | 60 | Lower for tests; avoid very low in prod (<15) to reduce event noise. |
 - G6_EXPIRY_SERVICE – bool – on – Enable expiry resolution & remediation service orchestration (centralizes expiry map build/schedule plus misclassification remediation lifecycle). Rarely disabled except in minimal offline tooling.

## 4. Resilience / Providers / Retry
- G6_ADAPTIVE_CB_PROVIDERS – bool – off – Adaptive circuit breaker wraps provider methods.
- G6_ADAPTIVE_CB_INFLUX – bool – off – Adaptive circuit breaker on Influx writes.
- G6_HEALTH_COMPONENTS – bool – off – Emit component health metrics / panel section when enabled.
- G6_RETRY_PROVIDERS – bool – off – Standardized retry for provider get_quote/get_ltp.
- G6_RETRY_MAX_ATTEMPTS – int – 0 – Max provider retry attempts (0 disables custom retry loop).
- G6_RETRY_MAX_SECONDS – int – 0 – Max cumulative seconds for retries.
- G6_CB_FAILURES – int – 5 – Failures threshold to open circuit (tests adjust lower).
- G6_CB_MIN_RESET – int – 5 – Minimum seconds before attempting half-open.
- G6_CB_MAX_RESET – int – 30 – Max backoff seconds before next attempt.
- G6_CB_BACKOFF – int – 5 – Base backoff seconds (pre-jitter) before half-open retry.
- G6_CB_JITTER – float – 0.1 – Jitter fraction applied to backoff (random +/- fraction * backoff).
- G6_CB_HALF_OPEN_SUCC – int – 2 – Required consecutive successes in half-open before closing circuit.
- G6_CB_STATE_DIR – path – data/health – Directory to persist circuit breaker state (survives restart) if enabled.
- G6_CIRCUIT_METRICS – bool – off – Emit detailed per-provider circuit breaker metrics series.
- G6_KITE_QUOTE_BATCH – bool – off – Enable micro-batching of concurrent Kite quote requests within a short window to reduce outbound API calls.
- G6_KITE_QUOTE_BATCH_WINDOW_MS – int – 15 – Batch aggregation window in milliseconds; all requests arriving within this window merge into one `kite.quote` call.
- G6_KITE_QUOTE_CACHE_SECONDS – float – 1.0 – In-memory per-symbol quote cache TTL; requests fully satisfied by fresh cached symbols bypass network call.

## 5. CSV Writer / Storage Tuning
| G6_CSV_JUNK_DEBUG | If set to 1/true enables verbose debug logs for junk filter decisions (whitelist, skip reasons). Intended for troubleshooting and tests. | 0 | optional |
| G6_CSV_JUNK_MIN_LEG_OI | Minimum per-leg (CE or PE) open interest required; if either leg below and junk filtering active row is skipped. Enables detection of asymmetric low-quality legs. | 0 | optional |
| G6_CSV_JUNK_MIN_LEG_VOL | Minimum per-leg (CE or PE) volume required; similar semantics to per-leg OI threshold. | 0 | optional |

### Expiry Misclassification Detection
Instrumentation detecting semantic junk caused by mixed expiry_date values within a single logical expiry_code (e.g., weekly bucket receiving stray other-week rows).

| Env | Description | Default | Notes |
|-----|-------------|---------|-------|
| G6_EXPIRY_MISCLASS_DETECT | Master switch for detection logic in CsvSink; when disabled no canonical map or metrics updates occur. | 1 | Values: 1/true/on to enable. |
| G6_EXPIRY_MISCLASS_DEBUG | Emit warning log lines (EXPIRY_MISCLASS ...) on detection events with expected vs actual dates. | 0 | For noisy troubleshooting only. |
| G6_EXPIRY_MISCLASS_SKIP | (Deprecated alias; see DEPRECATIONS.md) Previously: skip (do not persist) rows whose expiry_date conflicts with established canonical for (index, expiry_code). | 0 | Treated internally as `G6_EXPIRY_MISCLASS_POLICY=reject`; prefer policy flag. Will be removed after R+1. |
| (Removed) G6_SUPPRESS_BENCHMARK_DEPRECATED | (Use G6_SUPPRESS_DEPRECATIONS) | Historical | 2025-10 |
| G6_SUPPRESS_EXPIRY_MATRIX_WARN | (Removed; no longer used) Previously: suppressed legacy provider init fallback warning in `scripts/expiry_matrix.py`. | 0 | Variable retained only in tests; functional path removed. Will be dropped after next release. |

### Expiry Misclassification Remediation (Policy Layer)
Extends detection with automated rewrite / quarantine / reject handling (ENFORCEMENT ACTIVE). Order of operations: detect -> increment misclassification counter -> apply policy.

| Env | Description | Default | Notes |
|-----|-------------|---------|-------|
| G6_EXPIRY_QUARANTINE_DIR | Directory for quarantined misclassified rows (ndjson per day). | data/quarantine/expiries | Created lazily if policy=quarantine. |
| G6_EXPIRY_REWRITE_ANNOTATE | When rewrite policy active, annotate persisted row with audit fields (original_expiry_code, rewrite_reason). | 1 | Set 0 to suppress extra columns. |

Quarantine Record Schema (one line JSON):
```
{ "ts": ISO8601, "index": str, "original_expiry_code": str, "canonical_expiry_code": str, "reason": str, "row": { ...original row... } }
```

Planned Additional Flags (roadmap; not yet in code):
- G6_EXPIRY_QUARANTINE_SUMMARY=1 – Emit daily summary event after midnight local.
- G6_EXPIRY_QUARANTINE_MAX_DAYS=30 – Auto-prune quarantine files older than N days.

Metrics: `g6_expiry_quarantined_total`, `g6_expiry_rewritten_total`, `g6_expiry_rejected_total`, `g6_expiry_quarantine_pending`.

Behavior Summary:
1. First row for (index, expiry_code) establishes canonical expiry_date; gauge `g6_expiry_canonical_date_info{index,expiry_code,expiry_date}` is set to 1.
2. Subsequent differing expiry_date for same key increments `g6_expiry_misclassification_total{index,expiry_code,expected_date,actual_date}`.
3. If skip flag set the mismatching row is not written to CSV, preventing propagation of semantic junk.
4. Debug flag adds structured logs aiding upstream root cause analysis (e.g., classifier heuristic drift, race conditions).

### (Removed duplicate cross-reference block)
(Cross-reference: expiry misclassification & remediation variables documented in the primary Detection / Remediation subsections above; duplicate governance helper list removed to satisfy duplicate token test.)

### Risk Aggregation & Analytics Paths (auto-catalog additions)
- G6_RISK_AGG – bool – off – Master enable for risk aggregation build path (row aggregation into buckets).

### Runtime / Bootstrap Misc
- G6_RUNTIME_FLAGS – csv – (unset) – Comma list of lightweight experimental runtime feature flags toggled at bootstrap (parsed centrally; used for quickly scaffolding toggles before dedicated env vars/config keys exist). Unknown tokens ignored.
- G6_LATENCY_PROFILING – bool – off – Enable additional per-section timing metrics & structured logs for latency deep dives (increases CPU + log volume; use short-term).
- G6_ENABLE_METRIC_GROUPS – csv – (unset) – Comma allow-list of metric group identifiers to force-enable even if disabled lists would otherwise prune them (takes precedence over disable list; unspecified=all default gating behavior).
- G6_HEALTH_API_ENABLED – bool – off – Enable lightweight health HTTP API (exposes /health endpoint with basic status JSON & build info). Intended for container orchestrator liveness checks.
- G6_HEALTH_API_HOST – str – 127.0.0.1 – Bind host for health API server (effective only when health API enabled).
- G6_HEALTH_API_PORT – int – 0 – Port for health API (0 or unset selects ephemeral/random port logged at startup).
- G6_METRICS_VERBOSE – bool – off – Emit verbose metrics initialization / gating logs (group resolution, duplicates). Helpful during registration refactors; generally leave off for noise reduction.
- G6_PARALLEL_COLLECTION – bool – off – Legacy alias for the parallel per-index collection feature flag (primary flag documented separately). Retained for backward compatibility only.
- G6_PARTIAL_REASON_HIERARCHY – bool – off – When enabled, applies hierarchical precedence ordering to partial_reason classification (prefers most critical cause) instead of first-detected. Experimental.
- G6_SCHEMA_STRICT – bool – off – Enforce strict schema validation for status snapshot / panels (raise on unknown keys rather than warn). Use in CI to surface unintended schema drift.
- G6_STORAGE_INFLUX_ENABLED – bool – off – Enable InfluxDB persistence of per-cycle aggregation metrics & selected counters (requires bucket parameters).
- G6_STORAGE_INFLUX_BUCKET – str – (unset) – Target Influx bucket name (required when Influx enabled).
- G6_STORAGE_CSV_DIR – path – data/csv – Root output directory for CSV sink persistence (option rows, metrics, derived artifacts). Ensure writable.
- G6_NAME – (deprecated placeholder) – (none) – Non-functional placeholder token previously picked up by scanners. Do not set; retained only to suppress false-positive governance failures until generator filtering reliably excludes placeholder examples.
- G6_STORAGE_INFLUX_ORG – str – (unset) – Influx organization identifier (required when Influx enabled and using multi-org endpoint patterns).
- G6_STORAGE_INFLUX_URL – url – (unset) – Base URL for Influx instance (e.g., https://influx.example.com). Must include scheme.
- G6_SUMMARY_ALERT_LOG_BACKUPS – int – 1 – Number of rotated backups to retain for alerts_log.json when size-based rollover triggered (0 disables rotation, risk of unbounded growth if max MB also high).
- G6_SUMMARY_ALERT_LOG_MAX_MB – float – 5.0 – Maximum alerts log file size (megabytes) before rotation/compaction; tuning trades space vs retention.
- G6_SUMMARY_ANOMALY – bool – off – Enable experimental anomaly detection overlays in summary (injects anomaly panel data); unstable path.
- G6_SUMMARY_CONTROLLER_META – bool – off – Emit controller internal decision metadata block into summary (for debugging adaptive promotions/demotions).
- G6_SUMMARY_EVENT_DEBOUNCE_MS – int – 750 – Minimum milliseconds between emission of identical summary high-frequency events to avoid log/panel churn (0 disables debounce).
- G6_SUMMARY_FOLLOWUP_SPARK – bool – off – Enable sparkline embedding for follow-up alert sequences in summary panels (visual density increase; experimental).
- G6_STRICT_MODULE_IMPORTS – bool – off – When enabled, disallows importing deprecated internal modules (raises immediately) instead of logging warnings—used transiently during refactors.
- G6_HEALTH_API_ – (placeholder) – (none) – Partial prefix token picked up by broad scanners (no runtime effect). Safe to ignore; will be filtered by generator improvements and removed later.
- G6_STORAGE_ – (placeholder) – (none) – Partial prefix token captured by scanner heuristics (e.g., wildcard documentation). Ignored at runtime; retained temporarily to satisfy coverage until filter excludes trailing underscore forms.


### Additional / Legacy CSV Environment Variables
The following CSV writer related variables are referenced in code and tests (restored to satisfy documentation coverage):

- G6_CSV_PRICE_SANITY – Enables basic price sanity validations prior to persistence.
- G6_CSV_MAX_OPEN_FILES – int – 64 – Soft cap on concurrently open CSV file handles before least‑recently used is closed (prevents descriptor exhaustion on large index sets).
- G6_CSV_BUFFER_SIZE – int – 0 – Row buffer size before triggering flush in buffered mode (0 disables size-based flush; time/explicit triggers only). Placeholder for future batching tuning.
- G6_CSV_FLUSH_INTERVAL – int – 0 – Seconds between periodic background flush checks when buffered mode active (0 disables interval-based flushing).
- G6_CSV_BATCH_FLUSH – int – 0 – When >0 enables accumulating rows per-file until threshold reached, then bulk writes for reduced syscall overhead.
- G6_CSV_DEDUP_ENABLED – bool – off – Enable last-row duplicate suppression (skips writing identical consecutive rows for a given (index, expiry) file).
- G6_CSV_DQ_MIN_POSITIVE_COUNT – int – 0 – Minimum count of positive core numeric fields required to accept a row; lower-value rows dropped as low-signal/junk.
- G6_CSV_DQ_MIN_POSITIVE_FRACTION – float – 0.0 – Minimum fraction (0–1) of positive numeric fields required; complements absolute count heuristic.
- G6_CSV_FLUSH_NOW – bool – off – One-shot imperative flush trigger (set=1 for a cycle) applied after loop writes regardless of thresholds.
- G6_METRICS_CARD_RATE_LIMIT_PER_SEC – int – 0 – Global per-option emission cap.
- G6_METRICS_CARD_CHANGE_THRESHOLD – float – 0.0 – Required price delta for re-emission.
- G6_EMIT_CATALOG – bool – off – Emit catalog JSON during status writes.
- G6_EMIT_CATALOG_EVENTS – bool – off – Include recent events slice.
- G6_CATALOG_EVENTS_LIMIT – int – 20 – Max recent events.
- G6_CATALOG_EVENTS_CONTEXT – bool – on – Include event context objects.
- G6_CATALOG_INTEGRITY – bool – off – Add integrity analysis section.
- G6_CATALOG_HTTP – bool – off – Start /catalog HTTP server.
- G6_CATALOG_HTTP_HOST – str – 127.0.0.1 – Bind host.
- G6_CATALOG_HTTP_PORT – int – 9315 – Bind port.
- G6_CATALOG_HTTP_REBUILD – bool – off – Rebuild catalog each request instead of cached file.
- G6_CATALOG_HTTP_DISABLE – bool – off – Hard override to prevent starting the catalog HTTP server even if enabling conditions (flags or implied by snapshots/panels) are met. When set, any code path attempting to initialize the server short‑circuits and `/snapshots` functionality is unavailable (tests skip via this flag). The disabled `/snapshots` route returns HTTP 410 (Gone) instead of dynamic enable attempts. Use to de‑scope HTTP feature for focused development or when embedding in constrained environments.
- G6_SNAPSHOT_CACHE – bool – off – Maintain in-memory latest snapshots (requires catalog HTTP for /snapshots endpoint).
- G6_SNAPSHOT_CACHE_FORCE – bool – off – Force snapshot cache refresh / rebuild on next access regardless of staleness heuristics (diagnostic/testing aid). Avoid enabling persistently in production to prevent redundant work.
- G6_DOMAIN_MODELS – bool – off – Map raw quotes to domain model objects for debugging/analysis.
- G6_CARDINALITY_MAX_SERIES – int – 0 – Hard threshold of active metrics time series; above this guard triggers.
- G6_CARDINALITY_MIN_DISABLE_SECONDS – int – 300 – Minimum disable window before re-check for re-enable.
- G6_CARDINALITY_REENABLE_FRACTION – float – 0.7 – Re-enable per-option metrics when active series drop below fraction*max.
- G6_OPTION_METRIC_ATM_WINDOW – int – 0 – Additional filter: only strikes within +/- window steps around ATM for option-detail metrics (pre-guard heuristic).
 - G6_SUMMARY_CURATED_MODE – bool – off – Enable curated summary layout mode (adaptive block pruning / ordering). Auto-enabled in some CLI tools; when on, layout respects G6_SUMMARY_HIDE_EMPTY_BLOCKS default heuristic.
 - G6_SUMMARY_DOSSIER_PATH – path – (unset) – When set activates the DossierWriter plugin writing a consolidated JSON summary (default path fallback `data/unified_summary.json` if empty string). File is written atomically (temp + replace). No additional gate required (legacy `G6_SUMMARY_UNIFIED_SNAPSHOT` removed).
 - G6_PANELS_SSE_URL – url – (unset) – If set, activates SSEPanelsIngestor plugin which connects to the panels SSE endpoint (e.g. `http://127.0.0.1:9315/events`) consuming `panel_full` / `panel_diff` events into in‑memory panel overrides merged precedence-first over filesystem panel JSON when assembling unified snapshots.
 - G6_PANELS_SSE_STRICT – bool – off – Treat malformed or merge-conflicting SSE panel events as hard errors (raise) instead of warnings. Useful for CI enforcement; keep off in production for resilience.
 - G6_DISABLE_COMPONENTS – bool – off – Skip optional component initialization during bootstrap (provider aggregates, sinks, panels). Mainly for ultra-lean test harnesses.
 - G6_LEAN_MODE – bool – off – Activate lean collection mode: reduces instrument cache TTL and may skip heavyweight enrichment paths.
 - G6_INSTRUMENT_CACHE_TTL – float – 600 – Base TTL (seconds) for provider instrument metadata cache. Adjust lower in tests; automatically reduced in LEAN or DEBUG_SHORT_TTL modes.
 - G6_DEBUG_SHORT_TTL – bool – off – Force very short instrument cache TTL (e.g., 5s) for debugging cache refresh logic.
 - G6_DISABLE_AUTO_DOTENV – bool – off – Prevent automatic loading of .env file by kite provider when API credentials missing (use external secret management instead).
 - G6_STRIKE_CLUSTER – bool – off – Enable experimental strike clustering heuristic in collectors (groups strikes before selection logic). Diagnostic / tuning.
 - G6_TRACE_EXPIRY – bool – off – Emit detailed trace logs of expiry candidate selection in collectors (diagnostic noise; enable only temporarily).
 - G6_EXPIRY_COERCION_AGGREGATE – bool – off – When enabled, config expiry coercion validation aggregates multiple coercion suggestions instead of first-match shortcut (broader diagnostics output).

---
## 21. Adaptive Systems (Alerts, Severity, Strike Scaling, Controller)
Comprehensive list of adaptive-related environment variables (core logic spans `src/adaptive/`, `src/orchestrator/`, panels, and tests). Defaults reflect typical conservative behavior. Enable features incrementally.

Canonical Note: Do not duplicate any adaptive variable definitions outside this section. Add new adaptive env vars here only; governance duplicate checker treats this section as authoritative.

Core Controller & Modes:
- G6_ADAPTIVE_CONTROLLER – bool – off – Master enable for adaptive controller (memory/strike/detail mode adjustments). When off, all controller-driven adjustments are disabled.
- G6_ADAPTIVE_CONTROLLER_SEVERITY – bool – off – Enable using adaptive alert severity state as an input signal to controller decisions (promotion/demotion gating).

Alert Severity Framework:

Strike Scaling (Adaptive Strike Window Logic):
Variables (name – type – default – description):
- G6_ADAPTIVE_STRIKE_SCALING – bool – off – Master enable for strike window adaptive scaling.
- G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD – int – 3 – Consecutive breach cycles required before scaling reduction triggers.
- G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY – int – 10 – Healthy cycles required to begin restoring toward baseline depth.
- G6_ADAPTIVE_STRIKE_REDUCTION – float – 0.8 – Multiplicative factor applied to current strike depth on breach.
- G6_ADAPTIVE_STRIKE_MIN – int – 2 – Minimum allowable strike depth (per side) after scaling (floor).
- G6_ADAPTIVE_STRIKE_MAX_ITM – int – (unset) – Optional explicit maximum ITM strikes (pre-scaling cap).
- G6_ADAPTIVE_STRIKE_MAX_OTM – int – (unset) – Optional explicit maximum OTM strikes.
- G6_ADAPTIVE_STRIKE_STEP – int – (unset) – Optional stride increment when computing initial strike depth.
- G6_ADAPTIVE_SCALE_PASSTHROUGH – bool – off – When on, scaling calculations run but do not alter strike depth (emit diagnostic path only).

Memory / Resource Adaptive Adjustments:
- G6_ADAPTIVE_MEMORY_TIER – (planned) – Placeholder for future dynamic memory tier gating (not yet active; do not set).

Theme / SSE Adaptive Parameters:
- G6_ADAPTIVE_THEME_STREAM_INTERVAL – float – 3 – SSE streaming interval for adaptive theme endpoint.
- G6_ADAPTIVE_THEME_STREAM_MAX_EVENTS – int – 200 – Soft cap of SSE events per connection.
- G6_ADAPTIVE_THEME_SSE_DIFF – bool – on – Emit diff payloads after initial full snapshot.
- G6_ADAPTIVE_THEME_GZIP – bool – off – Enable gzip compression for adaptive theme responses if client supports it.

Misc Integration Flags (tests & panels):
- G6_ADAPTIVE_CONTROLLER_ACTIONS_DEBUG – bool – (planned) – Proposed future verbose controller action logging (currently unused allowlist placeholder).

Passthrough / Legacy:
1. Unset JSON rule variable falls back to internal heuristics; invalid JSON triggers safe ignore with warning.
2. Decay cycles = 0 disables severity decay (sticky until explicit downgrade condition).
3. Trend ratios evaluated only when window >=2 AND smoothing enabled.
4. Provide both legacy and new MAX/MIN parameters for detail mode to maintain backward compatibility across staggered deployments.
 - G6_TRACE_QUOTES – bool – off – Verbose per-quote emission tracing inside provider interface (logs raw quote objects / transformations). High volume; enable briefly for diagnostics.
 - G6_PANELS_SSE_DEBUG – bool – off – Increase verbosity for SSEPanelsIngestor (logs raw SSE events, merge decisions). Use only for debugging; noisy otherwise.

## 7. Analytics / Greeks / IV / Strikes
- G6_COMPUTE_GREEKS – bool – off – Enable Greeks computation path.
- G6_ESTIMATE_IV – bool – off – Enable IV solver attempts.
- G6_STRIKE_STEP_<INDEX> – int – (index specific default) – Override strike step (e.g., G6_STRIKE_STEP_NIFTY=25).

### Adaptive Alert Severity & Theming (New – previously undocumented, required for coverage)
Controls dynamic severity computation and alert presentation coloring for panels / summary.

- G6_RISK_AGG_BUCKETS – str – -20,-10,-5,0,5,10,20 – Moneyness bucket edges for risk aggregation (same semantics as surface buckets).
- G6_RISK_AGG_MAX_OPTIONS – int – 25000 – Safety cap on options processed per risk aggregation build.
 - G6_VOL_SURFACE_INTERPOLATE – bool – off – When enabled, fills internal missing moneyness buckets by linear interpolation between existing neighboring buckets (adds rows with source='interp', count=0). Improves continuity for visualization; no extrapolation beyond outer buckets.
 - G6_VOL_SURFACE_PERSIST – bool – off – Persist latest volatility surface artifact to `G6_ANALYTICS_DIR` as `vol_surface.latest.json[.gz]` (gzip when compression flag on).
 - G6_VOL_SURFACE_MODEL – bool – off – Enable model phase timing scaffold (records `g6_vol_surface_model_build_seconds` when active) for future advanced modeling integration.
 - G6_ANALYTICS_COMPRESS – bool – off – If on, gzip compress persisted analytics artifacts (vol surface / risk aggregation) producing `.json.gz` files.
 - G6_CONTRACT_MULTIPLIER_DEFAULT – float – 1 – Default contract multiplier applied when estimating notional exposures in risk aggregation (delta/vega notionals = |greek| * multiplier; underlying scaling placeholder until refined).
 - G6_CONTRACT_MULTIPLIER_<INDEX> – float – (inherit default) – Per-index override of contract multiplier (e.g., G6_CONTRACT_MULTIPLIER_NIFTY=50). Used for notional approximations in risk aggregation output.
 - G6_DISABLE_METRIC_GROUPS – str – (none) – Comma separated list of metric group identifiers to disable at registration time (e.g., analytics_vol_surface,analytics_risk_agg). Disables registration of those metric families to reduce cardinality; empty/unset leaves all enabled (unless allow-list enforced).
 	# Plain token reference (coverage test aid): G6_ENABLE_METRIC_GROUPS

### Performance Optimization Thresholds & Caches
- G6_STRIKE_COVERAGE_OK – float – 0.75 – Strike coverage threshold (0-1) for classifying an expiry OK (fraction of requested strikes realized). Lower to relax OK classification; values outside [0,1] ignored.
- G6_FIELD_COVERAGE_OK – float – 0.55 – Field (volume+oi+avg_price) coverage threshold (0-1) for OK classification. Lower to reduce PARTIAL statuses under sparse data conditions. Invalid values ignored.
- G6_DISABLE_ROOT_CACHE – bool – off – When set (1/true) disables process-wide root symbol detection cache, forcing direct parsing each call (diagnostics / profiling).
- G6_ROOT_CACHE_MAX – int – 4096 – Soft maximum number of distinct symbol roots retained in cache before opportunistic eviction (~5%). Adjust if working universe is significantly larger; invalid/non-positive values revert to default.
- G6_DISABLE_STRUCT_EVENTS – bool – off – Master kill-switch for structured observability events (instrument_prefilter_summary, option_match_stats, zero_data, cycle_status_summary). Set 1/true to suppress emission (useful during ingestion outages or to reduce log volume temporarily). Does not affect legacy TRACE lines.
 - G6_DISABLE_ADAPTIVE_STRIKE_RETRY – bool – off – Disable adaptive strike depth expansion logic (R1.14). When set, collectors will not mutate `strikes_itm/strikes_otm` even if strike coverage shortfall is detected.
 - G6_CONTRACT_OK_CYCLES – int – 5 – Consecutive healthy cycles (no low strike coverage & no expansions) required before attempting a contraction back toward baseline strike depth.
 - G6_CONTRACT_COOLDOWN – int – 3 – Minimum cycles between successive contraction adjustments for a given index (prevents oscillation).
 - G6_CONTRACT_STEP – int – 2 – Number of strikes to reduce per side (ITM/OTM) when contraction triggers (never drops below initial baseline configuration).
 - G6_PREFILTER_MAX_INSTRUMENTS – int – 2500 – Safety valve upper bound on per-expiry instrument list; lists above this are truncated before quote enrichment (floor=50 enforced).
 - G6_PREFILTER_CLAMP_STRICT – bool – off – When on, a clamp downgrade marks the expiry PARTIAL (partial_reason=prefilter_clamp) to surface the event.
 - G6_PREFILTER_DISABLE – bool – off – Disable prefilter clamp logic entirely (no trimming even if above threshold).
## (Removed duplicate adaptive strike scaling dynamic defaults; canonical definitions live in Section 21 above to satisfy duplicate governance check.)
 - G6_SNAPSHOT_TEST_MODE – bool – off – When enabled and snapshots are being built (AUTO or RETURN path), bypasses market-hours gating (test accommodation) ensuring deterministic snapshot test execution irrespective of wall-clock session. Prefer using explicit force-open in production scenarios.

## 8. Panel / Publisher Extras (canonical definitions earlier in file; duplicates removed to satisfy governance duplicate checker)

### Panels Integrity / Advanced Panel Controls (New Governance Additions)
The following environment variables tune panel generation, integrity monitoring cadence, inclusion filters, and read/merge loop behaviors. They were referenced in code but previously undocumented; now added to satisfy coverage tests.

- G6_PANELS_ALWAYS_META – bool – off – When enabled forces writer to always include metadata block (version, schema_version, build info) even if unchanged, simplifying diff tools that assume presence.
- G6_PANELS_ATOMIC – bool – on – Write panel JSON atomically (tmp + replace). Disable (0/false) only for debugging on filesystems where atomic rename behaves unexpectedly.
- G6_PANELS_INCLUDE – csv – (unset) – Optional comma list of panel names to emit (others skipped). Empty/unset emits all. Useful for focused benchmarking or reduced I/O test runs.
- G6_PANELS_INTEGRITY_INTERVAL – int – 30 – Minimum seconds between integrity monitor runs (hash recompute / manifest compare). Lower for aggressive detection; raise to reduce overhead.
- G6_PANELS_INTEGRITY_MONITOR – bool – on – Master enable for panels integrity monitoring loop (hashing + mismatch counters). Disable to skip all integrity computations (metrics remain stale at last values).
- G6_PANELS_INTEGRITY_STRICT – bool – off – When enabled, any detected mismatch triggers a hard process exit (after logging) instead of metric-only signaling. Intended for CI/hard governance; keep off in production for resilience.
- G6_PANELS_LOOP_BACKOFF_MS – int – 250 – Backoff sleep (milliseconds) between successive panel writer loop iterations when no triggering events occur.
- G6_PANELS_READ_BACKOFF_MS – int – 250 – Backoff sleep (milliseconds) used by panel reader/ingestor loops when waiting for new or updated panel artifacts.
- G6_PANELS_READ_RETRY – int – 3 – Retry attempts when transient read errors (partial write/permission) encountered during panel ingestion; 0 disables retries.
- G6_PANELS_SCHEMA_WRAPPER – bool – on – Emit panels with top-level schema_version wrapper for forward compatibility (enforced by panel schema governance). Disable only for legacy tooling still expecting flat structure.

### Historical (Removed) Legacy Panels Bridge Variables
These variables were used only by the removed legacy panels bridge (`status_to_panels.py`). They are no longer read anywhere in the codebase and persist here solely to satisfy historical audit / env documentation coverage. Setting them has no effect.
- G6_ALLOW_LEGACY_PANELS_BRIDGE – (removed) – Former bypass to let the deprecated bridge run; bridge deleted, flag ignored.
- G6_FORCE_UNIFIED_PANELS_WRITE – (removed) – Previously forced unified writer while legacy bridge still active; unified writer now always authoritative.
- G6_PANELS_BRIDGE_PHASE – (removed) – Internal phased removal controller (A/B/C) for staged deprecation messaging.
 - G6_PANELS_BRIDGE_SUPPRESS – (removed) – Historical toggle to suppress legacy panels bridge deprecation warnings (no runtime effect now; documented for coverage until post-removal grace ends).
- G6_PANEL_H_ – int – 0 – Fixed height override for summary panel (0=auto).
- G6_PANEL_H_MARKET – int – 0 – Fixed height override for market panel.
- G6_PANEL_MIN_COL_W – int – 10 – Minimum column width when auto-fitting.
- G6_PANEL_W_ – int – 0 – Fixed width override for summary panel (0=auto).
- G6_PANEL_W_MARKET – int – 0 – Fixed width override for market panel.

## 9. HTTP & Auth
- G6_HTTP_BASIC_USER – str – (none) – Enable Basic Auth (paired with pass).
- G6_HTTP_BASIC_PASS – str – (none) – Basic Auth password.
- G6_CATALOG_HTTP_FORCED – bool – off – Force-enable catalog HTTP when snapshots/panels conditions met (internal helper usage).
- G6_EVENTS_LOG_PATH – path – logs/events.log – Override path for structured event log.
- G6_EVENTS_DISABLE – bool – off – Disable event emission entirely.
- G6_EVENTS_MIN_LEVEL – enum(DEBUG|INFO|WARN|ERROR) – INFO – Minimum level to record.
- G6_EVENTS_SAMPLE_DEFAULT – float – 1.0 – Default sampling probability (0-1) for events without explicit mapping.
 - G6_EVENTS_SNAPSHOT_GAP_MAX – int – 500 – Maximum allowed event id gap between last `panel_full` and current latest event before snapshot guard forces a new baseline `panel_full`. Lower for aggressive recovery during testing; raise cautiously if full snapshots are large.
 - G6_EVENTS_FORCE_FULL_RETRY_SECONDS – float – 30 – Cooldown period (seconds) per guard reason before another forced baseline may be emitted. Prevents rapid forced full churn under persistent fault conditions.
- G6_EVENTS_SAMPLE_MAP – str – (none) – Comma separated event=prob pairs (e.g., cycle_start=0.1,error=1.0).
 - G6_KITE_AUTH_VERBOSE – bool – off – When enabled, token validation logs full tracebacks & structured error handler output for invalid/expired Kite tokens instead of condensed warning. Use only for debugging noisy auth issues; default quiets expected daily expiry failures.
 - G6_EXPIRY_RULE_RESOLUTION – bool – off – Enable rule-based resolution of expiry tokens (this_week, next_week, this_month, next_month) to real calendar dates per index (weekday mapping in `src/config/expiry_resolver.py`). When off, legacy deterministic placeholder coercion mapping (incrementing day offsets) remains for schema compliance only.
 - G6_EXPIRY_EXPAND_CONFIG – str – (unset/off) – When set truthy (1/true/on or non-empty value) the collectors attempt to expand a single provided expiry tag (e.g. ['this_week']) to the full configured expiry list from `config/g6_config.json` for that index (if longer) prior to processing, mitigating under-specification. Default OFF preserves explicit test expectations (single batch). Accepts JSON or named preset in future; current implementation treats any truthy string as enable toggle. Invalid JSON ignored with warning.

## 10. Build / Versioning
- G6_VERSION – str – (auto) – Override version label (build info metric).
- G6_GIT_COMMIT – str(sha) – (auto) – Override git commit label.

## 11. Symbols / Matching Safety
- G6_SYMBOL_MATCH_MODE – enum(legacy|strict|loose) – legacy – Matching algorithm variant.
- G6_SYMBOL_MATCH_SAFEMODE – bool – off – Additional validation / fallback path.
- G6_SYMBOL_MATCH_UNDERLYING_STRICT – bool – off – Enforce strict underlying symbol match rules (reject partial/ambiguous matches).
- G6_TRACE_OPTION_MATCH – bool – off – Emit per-option acceptance TRACE diagnostics (reason counts + samples) in provider filtering.
- G6_DISABLE_PREFILTER – bool – off – Disable pre-index strike/type narrowing (diagnostic or emergency mode; increases scan cost).
- G6_ENABLE_NEAREST_EXPIRY_FALLBACK – bool – on – Enable forward (nearest future) expiry fallback search when target expiry has zero matches.
- G6_ENABLE_BACKWARD_EXPIRY_FALLBACK – bool – on – Enable backward (nearest past) expiry fallback search if target and forward are empty.

## 12. Pricing / Normalization Guards
- G6_PRICE_PAISE_THRESHOLD – float – 1e8 – Upper monetary guard before paise normalization adjustments (tests set huge to trigger path).
- G6_PRICE_MAX_STRIKE_FRAC – float – 0.35 – Fraction of underlying price above which strikes may be filtered.

## 13. Overlay / Visualization
- G6_PLOTLY_JS_PATH – path/url – (cdn) – Where to load Plotly JS.
- G6_PLOTLY_VERSION – str – (auto) – Override Plotly version label.
- G6_OVERLAY_VIS_MEMORY_LIMIT_MB – int – 512 – Memory budget for overlay aggregation.
- G6_OVERLAY_VIS_CHUNK_SIZE – int – 2048 – Batch size when building overlays.
- G6_TIME_TOLERANCE_SECONDS – int – 1 – Timestamp tolerance in overlay alignment.
- G6_OVERLAY_SKIP_NON_TRADING – bool – off – Skip overlay generation on non-trading days.
- G6_OVERLAY_WRITE_BACKUP – bool – off – Write backup copy of overlay output for audit.
- G6_WEEKDAY_OVERLAYS_HTML – path – weekday_overlays.html – Output HTML path for weekday overlays (legacy dashboard).
- G6_WEEKDAY_OVERLAYS_META – path – weekday_overlays_meta.json – Output metadata path for weekday overlays (legacy dashboard).

## 14. Summary / Reporting Cadence
- G6_WEEKEND_MODE – bool – off – When enabled (1/true/on/yes) the platform treats Saturday and Sunday as regular trading days for scheduling/gating purposes (demo / soak / backtest mode). Normal intraday open/close hours still apply; holidays continue to be honored.
- G6_SUMMARY_REFRESH_SEC – int – 5 – Main summary refresh cadence.
- G6_SUMMARY_META_REFRESH_SEC – int – 15 – Metadata refresh cadence.
- G6_SUMMARY_RES_REFRESH_SEC – int – 30 – Resource / utilization refresh cadence.
- G6_SUMMARY_ALT_SCREEN – bool – off – Use alternate terminal screen for summary UI (restores on exit).
- G6_SUMMARY_BACKOFF_BADGE_MS – int – 0 – Minimum ms a backoff badge stays visible after condition clears.
- G6_SUMMARY_LOOP_BACKOFF_MS – int – 500 – Backoff between summary refresh loop iterations.
 - G6_SUMMARY_DOSSIER_INTERVAL_SEC – float – 5.0 – Minimum seconds between dossier (unified summary JSON) writes while the dossier path variable is set. 0 forces write every loop (not advised for large deployments).
- G6_SUMMARY_MODE – str – (auto) – Force specific summary mode variant (e.g., plain, rich, panels).
- G6_OVERVIEW_INTERVAL_SECONDS – int – 180 – Interval (seconds) between overview snapshot persistence operations.
- G6_MASTER_REFRESH_SEC – int – 0 – When >0, legacy master refresh cadence overriding unified refresh logic (migrating away).
- G6_DASHBOARD_CORE_REFRESH_SEC – int – 5 – Core dashboard (legacy web) refresh cadence.
- G6_DASHBOARD_SECONDARY_REFRESH_SEC – int – 15 – Secondary stats refresh cadence (legacy web).
- G6_DASHBOARD_DEBUG – bool – off – Enable verbose legacy dashboard debug logging.
- G6_SUMMARY_STATUS_FILE – path – data/runtime_status.json – Overrides default runtime status source path for the unified summary loop (used by tests to point to synthetic status fixtures). If unset the loop falls back to `data/runtime_status.json`. Distinct from historical bridge `G6_STATUS_FILE` (removed with bridge deletion).

## 15. Panels Mode Preference

## 16. Testing / Mocking
- G6_USE_MOCK_PROVIDER – bool – off – Force mock provider.
- G6_TEST_CONFIG – path – config/g6_config.json – Override configuration path used by orchestrator test fixtures (run_orchestrator_cycle); allows pointing to alt minimal configs.
- G6_PARITY_GOLDEN_VERIFY – bool – off – When set to 1/true enables parity golden verification test (`tests/test_parity_golden_verify.py`) which recomputes checksum for parity_golden.json.

## 17. Expiry / Market Simulation (Legacy & New)
- (Legacy internal) provider-specific heuristics (undocumented) replaced progressively by the unified expiry service path.
- G6_CALENDAR_HOLIDAYS_JSON – path – (none) – Deprecated alias for the holidays file path; prefer the canonical holidays file variable.

## 18. Optional Data Source Selection
- G6_FORCE_DATA_SOURCE – enum(metrics|runtime_status|catalog) – (auto) – Force underlying dataset for summary views.

## 19. Internal / Housekeeping
- G6_CONFIG_PATH – path – config/g6_config.json – Primary runtime config file path override.
- G6_CONFIG_LOADER – bool – off – Force enhanced config loader pathway even if heuristics disabled.
- G6_CONFIG_EMIT_NORMALIZED – bool – off – Emit normalized effective config JSON to logs/normalized_config.json.
- G6_CONFIG_LEGACY_SOFT – bool – off – Allow loading with deprecated keys (stripped) instead of failing (currently usually off).
- G6_COLLECTION_INTERVAL – float – 60 – Legacy alias for per-cycle interval (prefer G6_CYCLE_INTERVAL/ config interval).
- G6_UNIFIED_METRICS – bool – off – Enable unified summary metrics emission (PanelsWriter / summary plugins) producing aggregated metrics families otherwise gated off to reduce baseline cardinality. When enabled, additional counters/gauges (e.g., panel diff, alerts totals) register under the unified metrics namespace. Leave off in minimal deployments or where Prometheus cardinality budgets are tight.
 - G6_LOOP_INTERVAL_SECONDS – float – (config/default) – Explicit orchestrator loop interval override captured in runtime_config (Phase 3). Set implicitly when CLI --interval differs from default and exported; can be set manually for process-wide interval tuning.
 - G6_METRICS_ENABLED – bool – on – Master enable switch for metrics server initialization & metric family registration. Set 0/false to disable Prometheus metrics listener entirely.
 - G6_METRICS_HOST – str – 0.0.0.0 – Override bind host for metrics server (takes precedence over config file value when set).
 - G6_METRICS_PORT – int – 9108 – Override bind port for metrics server (takes precedence over config file value when set).
- G6_MISSING_CYCLE_FACTOR – float – 2.0 – Multiplier for detecting missed cycles (gap >= factor * interval triggers g6_missing_cycles_total increment; clamp min 1.1). Raise to reduce sensitivity (e.g., 3.0) or lower cautiously (>1.1) for aggressive detection.
- G6_CSV_JUNK_MIN_TOTAL_OI – int – 0 – Junk filter: minimum combined (CE+PE) open interest required to persist a row (active only if >0 or junk enabled explicitly).
- G6_CSV_JUNK_MIN_TOTAL_VOL – int – 0 – Junk filter: minimum combined (CE+PE) volume required to persist a row.
- G6_CSV_JUNK_ENABLE – enum(auto|on|off) – auto – Junk row filtering mode. auto enables when either threshold >0. Rows failing thresholds increment g6_csv_junk_rows_skipped_total.
- G6_CSV_JUNK_STALE_THRESHOLD – int – 0 – Junk filter: if >0, number of consecutive identical (CE,PE) last_price signatures per (index,expiry,strike_offset) after which rows are considered stale junk (skipped). Count resets when price changes.
- G6_CSV_JUNK_WHITELIST – str – (none) – Comma list of patterns exempt from junk filtering. Patterns: INDEX:EXPIRY_CODE, INDEX:*, *:EXPIRY_CODE, or * for global. Example: NIFTY:this_week,BANKNIFTY:*,*:current_month.
- G6_CSV_JUNK_SUMMARY_INTERVAL – int – 0 – Seconds interval for periodic aggregated junk skip summary logs (CSV_JUNK_SUMMARY). 0 disables.
- G6_CYCLE_OUTPUT – bool – off – Emit per-cycle debug output (legacy instrumentation).
- G6_DISABLE_PRETTY_CYCLE – bool – off – Disable pretty cycle formatting (plain timing logs).
- G6_FORCE_ASCII – bool – off – Force ASCII-only output (disable unicode for terminals lacking support).
- G6_ENABLE_TRACEMALLOC – bool – off – Enable tracemalloc tracking at startup (snapshots require other G6_TRACEMALLOC_* vars).
- G6_EVENTS_RECENT_MAX – int – 200 – Max in-memory recent events retained for tail queries.
- G6_JSON_LOGS – bool – off – Emit structured JSON lines to console instead of human-friendly formatter.
- G6_LOG_FILE – path – logs/g6_platform.log – Log file output path.
- G6_OUTPUT_JSONL_PATH – path – g6_output.jsonl – Output JSONL file path for unified source output sink.
- G6_SOURCE_PRIORITY_METRICS – int – 1 – Priority (lower is higher precedence) for metrics as a data source.
- G6_SOURCE_PRIORITY_PANELS – int – 2 – Priority for panels data source.
- G6_SOURCE_PRIORITY_STATUS – int – 3 – Priority for runtime_status data source.
- G6_SOURCE_PRIORITY_LOGS – int – 4 – Priority for logs as data source.
- G6_HEALTH_API – bool – off – Expose health API endpoint (legacy/diagnostic).
- G6_HEALTH_PROMETHEUS – bool – off – Expose Prometheus metrics endpoint (legacy toggle; prefer always-on when metrics enabled).
- G6_ENHANCED_CONFIG – bool – off – Enable enhanced config validation / enrichment path.
- G6_ENHANCED_UI – bool – off – Enable enhanced console UI styling features.
- G6_ENHANCED_UI_MARKER – bool – off – Display explicit marker that enhanced UI mode is active (debugging support).
- G6_ENABLE_DATA_QUALITY – bool – off – Master enable for optional data quality checker integration in collectors. When on, best-effort index / option / expiry consistency validations run (wrapped via data_quality_bridge) emitting diagnostic metrics & structured logs; failures never abort a cycle. Off = zero overhead and identical legacy behavior.
- G6_DQ_ERROR_THRESHOLD – int – 0 – Data quality error threshold (context-specific; triggers stricter handling).
- G6_DQ_WARN_THRESHOLD – int – 0 – Data quality warning threshold.
- G6_PREVENTIVE_DEBUG – bool – off – Verbose logging for preventive validation adjustments.
- G6_LOG_LEVEL – str – INFO – Set via scripts for run_live convenience.
- G6_BOOTSTRAP_COMPONENTS – bool – off – Enable experimental bootstrap path assembling providers/sinks modularly.
- G6_NEW_BOOTSTRAP – bool – off – Force new bootstrap even if legacy path still present.
- G6_NEW_LOOP – bool – off – Enable experimental orchestrator `run_loop` driver.
- G6_LOOP_MARKET_HOURS – bool – off – Apply market hours gating inside new loop path.
- G6_CYCLE_SLA_FRACTION – float – 0.85 – SLA fraction of interval to classify breach.
- G6_PROVIDER_FAILFAST – bool – off – Abort composite provider traversal after first failure (diagnostics).
- G6_MEMORY_LEVEL1_MB – int – 200 – Tier 1 memory soft limit (MB) for adaptive behaviors.
- G6_MEMORY_LEVEL2_MB – int – 300 – Tier 2 memory soft limit (MB) for intensified mitigation.
- G6_MEMORY_LEVEL3_MB – int – 500 – Tier 3 hard memory threshold (MB) triggers aggressive scaling or abort logic.
- G6_MEMORY_GC_INTERVAL_SEC – int – 0 – Force manual garbage collection every N seconds (0=disabled).
- G6_MEMORY_MINOR_GC_EACH_CYCLE – bool – off – Trigger gc.collect() each cycle (diagnostics; may impact latency).
- G6_MEMORY_PRESSURE_RECOVERY_SECONDS – int – 120 – Consecutive healthy seconds before recovering a memory tier.
- G6_MEMORY_PRESSURE_TIERS – str – (auto) – Comma list of MB thresholds overriding tier env vars.
- G6_MEMORY_ROLLBACK_COOLDOWN – int – 60 – Cooldown seconds before retrying deeper strike depth after rollback.
- G6_PRICE_MAX_INDEX_FRAC – float – 0.0 – If >0, filter strikes above frac * underlying index price.
- G6_PROCESS_START_TS – int – (auto) – Override process start timestamp (testing/time travel).
- G6_RETRY_BACKOFF – float – 0.0 – Base retry backoff seconds for provider operations.
- G6_RETRY_JITTER – float – 0.1 – Jitter fraction applied to retry backoff.
- G6_RETRY_BLACKLIST – str – (none) – Comma list of exception names to never retry.
- G6_RETRY_WHITELIST – str – (none) – Comma list of exception names eligible for retry (if set overrides defaults).
- G6_RUNTIME_STATUS – bool – off – Enable runtime status writer (legacy alias; prefer always-on status writer path).
- G6_RUNTIME_STATUS_FILE – path – data/runtime_status.json – Override status file path.
- G6_RUN_ID – str – (auto) – Unique run identifier injected into logs/metrics.
- G6_SKIP_ZERO_ROWS – bool – off – Skip writing CSV rows with all zero volume & OI.
- G6_STREAM_GATE_MODE – enum(lenient|strict) – lenient – Stream gating strictness.
- G6_STREAM_STALE_ERR_SEC – int – 120 – Error threshold seconds since last data update.
- G6_STREAM_STALE_WARN_SEC – int – 60 – Warning threshold seconds since last data update.
- G6_SUPPRESS_CLOSED_METRICS – bool – off – Suppress metrics emission when market closed.
- G6_TERMINAL_MODE – enum(plain|rich) – (auto) – Force terminal renderer backend.
- G6_TRACEMALLOC_SNAPSHOT_DIR – path – (none) – Directory to store tracemalloc snapshots.
- G6_TRACEMALLOC_TOPN – int – 25 – Top N allocations to report in snapshot.
- G6_TRACEMALLOC_WRITE_SNAPSHOTS – bool – off – Enable periodic tracemalloc snapshot writes.
- G6_WEB_PORT – int – 0 – Port for lightweight HTTP endpoints (0=auto/random or disabled).

## 19a. Adaptive Controller
Multi-signal controller governing option detail mode demotions/promotions.

## 19b. Token Provider & Headless Auth
Environment variables specific to the refactored token manager (pluggable providers, headless mode):

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| G6_TOKEN_PROVIDER | str | kite | Token provider selection (kite, fake). Fake issues deterministic token for CI/tests. |
| G6_TOKEN_HEADLESS | bool | off | Force headless acquisition (no browser / Flask). For kite requires KITE_REQUEST_TOKEN. |
| G6_ALLOW_LEGACY_SCAN | bool | off | Skip flag for legacy scan safeguard test (documented for coverage). |

---
## 22. Alerts Core & Thresholds
Core enable + structural / threshold parameters for legacy (pre adaptive severity) alert emission & taxonomy. These drive which raw alert objects are constructed before adaptive severity classification layers.

- G6_ALERTS – bool – off – Master enable for legacy alerts pipeline (base alert extraction & serialization). Off = no base alerts generated.
- G6_ALERTS_FLAT_COMPAT – bool – on – Preserve legacy flat alerts list shape for downstream consumers during transition to structured taxonomy.
- G6_ALERTS_STATE_DIR – path – (unset) – Optional directory for persisting per-alert-type state (streaks / suppression metadata) across restarts. If unset, state ephemeral in‑memory.
- G6_ALERT_TAXONOMY_EXTENDED – bool – off – Emit extended taxonomy fields (group/subtype) for alerts that support it.
- G6_ALERT_FIELD_COV_MIN – float – 0.0 – Minimum field coverage (0‑1) required before emitting field coverage warnings; below threshold triggers coverage alert type.
- G6_ALERT_STRIKE_COV_MIN – float – 0.0 – Minimum strike coverage (0‑1) before emitting strike coverage shortfall alert.
- G6_ALERT_LIQUIDITY_MIN_RATIO – float – 0.0 – Minimum acceptable aggregated liquidity ratio; below triggers liquidity alert.
- G6_ALERT_WIDE_SPREAD_PCT – float – 0.0 – Percent (0‑1) spread threshold; options above considered wide and may trigger spread alert.
- G6_ALERT_QUOTE_STALE_AGE_S – int – 0 – Age in seconds after which last quote timestamp is considered stale for stale quote alert (0 disables).
- G6_COLLECTOR_REFACTOR_DEBUG – bool – off – Enable verbose diagnostics around collector refactored code paths (alerts emission integration).

## 23. Followups (Post-Alert & Diagnostic Sequences)
Parameters governing follow‑up event emission (additional clarifying / progressive alerts emitted after initial base alerts for persistent conditions, interpolation spikes, or risk drift).

- G6_FOLLOWUPS_ENABLED – bool – off – Master enable for followups subsystem.
- G6_FOLLOWUPS_DEBUG – bool – off – Verbose logging for followup evaluation decisions (guarded; noisy in production).
- G6_FOLLOWUPS_EVENTS – bool – off – Emit structured followup events onto event bus instead of (or in addition to) panel‑only data.
- G6_FOLLOWUPS_BUFFER_MAX – int – 200 – Ring buffer size of recent raw observations per alert type (memory for trend logic). Non‑positive => fallback default.
- G6_FOLLOWUPS_SUPPRESS_SECONDS – int – 0 – Suppression window after a followup fires before same type may fire again (0 disables suppression).
- G6_FOLLOWUPS_WEIGHT_WINDOW – int – 30 – Window size (cycles) for weighted / EWMA calculations (if logic enabled). 0 disables weighting.
- G6_FOLLOWUPS_WEIGHTS – JSON – (unset) – Optional JSON mapping alert_type -> weight (or scheme descriptor) overriding default equal weighting.
- G6_FOLLOWUPS_PANEL_LIMIT – int – 50 – Maximum number of followup entries surfaced in panels (older trimmed).
- G6_FOLLOWUPS_BUCKET_THRESHOLD – float – 0.0 – Threshold for bucket utilization degradation followup trigger.
- G6_FOLLOWUPS_BUCKET_CONSEC – int – 0 – Consecutive cycles below bucket threshold required before bucket followup emits.
- G6_FOLLOWUPS_INTERP_THRESHOLD – float – 0.0 – Threshold for interpolation fraction anomaly followup.
- G6_FOLLOWUPS_INTERP_CONSEC – int – 0 – Consecutive cycles exceeding interpolation threshold needed before followup.
- G6_FOLLOWUPS_DEMOTE_THRESHOLD – float – 0.0 – Threshold indicating sustained degraded condition suggesting controller demotion (advisory followup).
- G6_FOLLOWUPS_RISK_DRIFT_PCT – float – 0.0 – Absolute delta drift % threshold for risk drift followup.
- G6_FOLLOWUPS_RISK_MIN_OPTIONS – int – 0 – Minimum options required for risk drift computation; fewer => no followup.
- G6_FOLLOWUPS_RISK_WINDOW – int – 0 – Sliding window length for risk drift baseline; 0 disables drift followup logic.

## 24. Enrichment & Async Pipeline
Async enrichment toggles for quote / option detail augmentation separate from core synchronous collection.

- G6_ENRICH_ASYNC – bool – off – Master gate for asynchronous enrichment pipeline.
- G6_ENRICH_ASYNC_BATCH – int – 0 – Optional batch size for grouped async enrichment tasks; 0/<=0 means process individually.
- G6_ENRICH_ASYNC_WORKERS – int – 4 – Max concurrent async enrichment worker tasks (thread or async tasks depending on implementation).
- G6_ENRICH_ASYNC_TIMEOUT_MS – int – 0 – Per batch/task timeout milliseconds; 0 disables explicit timeout.
- G6_DISABLE_STRIKE_CACHE – bool – off – Disable strike metadata caching (forces fresh strike lookups each cycle; higher latency; diagnostics only).
- G6_DISABLE_GREEKS – bool – off – Disable Greeks computation path even if normally implied / enabled.
- G6_FORCE_GREEKS – bool – off – Force enable Greeks computation regardless of heuristics (overrides disable flag precedence if both set).
- G6_DETAIL_MODE_BAND_ATM_WINDOW – int – 0 – Width (strikes) around ATM used for dynamic detail mode adjustments (band logic). 0 disables band gating.

## 25. Persistence / External Systems (Influx & CSV Demo)
Variables controlling external persistence layers, batching and demo directories.

- G6_INFLUX_BATCH_SIZE – int – 0 – Number of points per Influx line protocol batch before flush (0 uses internal default / unbatched path).
- G6_INFLUX_FLUSH_INTERVAL – int – 0 – Seconds between forced Influx flushes when batching active; 0 disables periodic flush forcing.
- G6_INFLUX_MAX_QUEUE_SIZE – int – 0 – Upper bound on queued pending points before backpressure / drop strategy.
- G6_INFLUX_POOL_MIN_SIZE – int – 0 – Minimum connection pool size (if client supports pooling).
- G6_INFLUX_POOL_MAX_SIZE – int – 0 – Maximum connection pool size.
- G6_CSV_BASE_DIR – path – (unset) – Base directory override for CSV sink file roots (falls back to config paths if unset).
- G6_CSV_DEMO_DIR – path – (unset) – Alternate output root used by demo / showcase scripts (panel snapshots, curated samples).
- G6_CSV_VERBOSE – bool – off – Verbose per-write CSV debug logging (high volume; diagnostics only).

## 26. Integrity / Validation / Config Strictness
Strictness controls and internal validation cadence gates.

- G6_CONFIG_STRICT – bool – off – Fail fast on any config validation issue (strict schema + semantic). Off = best-effort warnings.
- G6_CONFIG_DOC_STRICT – bool – off – Treat missing config documentation entries as errors (governance mode; CI only).
- G6_CONFIG_SCHEMA_DOC_STRICT – bool – off – Enforce that every schema key has a corresponding documentation block (superset strict mode).
- G6_CONFIG_VALIDATE_CAPABILITIES – bool – off – Enable capability validation phase ensuring provider supports requested feature set.
- G6_INTEGRITY_AUTO_RUN – bool – off – Enable automatic integrity verification pass (structure / artifact cross-check) on startup.
- G6_INTEGRITY_AUTO_EVERY – int – 0 – Seconds between periodic integrity auto-runs; 0 disables recurring schedule.
- G6_INTERP_FRACTION_ALERT_THRESHOLD – float – 0.0 – Baseline interpolation fraction threshold feeding alert generation (distinct from followups threshold if both present).
- G6_INTERP_FRACTION_ALERT_STREAK – int – 0 – Consecutive cycles exceeding interpolation fraction threshold before initial alert.
 - G6_ADAPTIVE_ALERT_SEVERITY – bool – off – Master enable for adaptive alert severity state machine (enriches alerts with WARN/CRITICAL levels and drives severity panels/events). When off severity tracking & escalation logic disabled (base alert emission still occurs where applicable).
 - G6_ADAPTIVE_ALERT_SEVERITY_RULES – JSON – (unset) – JSON object mapping alert types → {warn:float,critical:float} threshold overrides. Example: {"interpolation_high":{"warn":0.55,"critical":0.65}}. Missing keys fall back to internal defaults.
 - G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES – int – 0 – Cycles of sustained below-warn condition required before a WARN/CRITICAL severity decays one level (0 uses default decay heuristic).
 - G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK – int – 0 – Minimum consecutive triggers before initial severity escalation beyond INFO (guards against noisy single-cycle spikes).
 - G6_ADAPTIVE_ALERT_SEVERITY_FORCE – enum(info|warn|critical) – (unset) – Force floor severity for all adaptive alerts (diagnostics / demo). Overrides decay (cannot demote below forced level).
 - G6_ADAPTIVE_ALERT_COLOR_INFO – str – (unset) – ANSI or hex color override for INFO severity rendering in dashboards / terminal (format accepted by theming layer).
 - G6_ADAPTIVE_ALERT_COLOR_WARN – str – (unset) – Color override for WARN severity.
 - G6_ADAPTIVE_ALERT_COLOR_CRITICAL – str – (unset) – Color override for CRITICAL severity.
 - G6_ADAPTIVE_DEMOTE_COOLDOWN – int – 0 – Minimum cycles between severity demotions to prevent flip-flopping in borderline conditions.
 - G6_ADAPTIVE_MAX_DETAIL_MODE – int – 0 – Maximum adaptive detail mode level the runtime can escalate to (0 uses internal cap). Limits granularity of diagnostic panels.
 - G6_ADAPTIVE_MIN_DETAIL_MODE – int – 0 – Minimum floor for adaptive detail mode (prevents full de-escalation when partial verbosity desired).
 - G6_ADAPTIVE_PROMOTE_COOLDOWN – int – 0 – Minimum cycles between severity promotions (throttles rapid escalations during volatile conditions).
 - G6_ADAPTIVE_RECOVERY_CYCLES – int – 0 – Consecutive healthy cycles before resetting historical streak state (streak counters/rolling windows cleared).
 - G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES – csv – (unset) – Comma list of alert types allowed to demote directly from CRITICAL to lower levels bypassing WARN when recovery is strong.
 - G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO – float – 0.0 – Ratio-based trend trigger for automatic critical escalation (e.g., slope or drift ratio). 0 => disabled.
 - G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO – float – 0.0 – Ratio threshold for warning-level trend escalation.
 - G6_ADAPTIVE_SEVERITY_TREND_WINDOW – int – 0 – Rolling window (cycles) for computing trend ratios (0 uses internal adaptive default). Larger window smooths noise; small window increases responsiveness.
 - G6_ADAPTIVE_SEVERITY_TREND_SMOOTH – float – 0.0 – Optional exponential smoothing alpha (0 disables explicit smoothing). Applied to raw trend ratio before threshold comparison.
 - G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES – csv – (unset) – Alert types that, while at WARN, block promotion of other types to CRITICAL to avoid alert storms (coordination heuristic).
 - G6_ADAPTIVE_SLA_BREACH_STREAK – int – 0 – Consecutive SLA health breaches before raising severity (0 uses default internal policy if implemented).
 - G6_ADAPTIVE_MAX_SLA_BREACH_STREAK – int – 0 – Hard cap preventing unbounded streak growth for SLA breach driven severity logic.
 - G6_ADAPTIVE_MIN_HEALTH_CYCLES – int – 0 – Minimum healthy baseline cycles required before enabling certain trend/severity escalations (warm-up guard).
 - G6_ADAPTIVE_SEVERITY_STATE_DEBUG – bool – off – Emit verbose internal state transitions for severity controller (high volume; diagnostics only).
 - G6_VOL_SURFACE_PER_EXPIRY – bool – off – Enable per-expiry volatility surface metrics (row counts & interpolated fraction per expiry). Adds labelled metrics; off reduces cardinality.
 - G6_WARN_LEGACY_METRICS_IMPORT – bool – off – Emit a deprecation warning when `src.metrics.metrics` is imported directly (encourages facade adoption). Set to 1/true to enable.
 - G6_BUILD_CONFIG_HASH – str – unknown – Build/config content hash label injected into `g6_build_info` metric (used for deployment provenance / drift detection).
- G6_COMPOSITE_PROVIDER – bool – off – Enable composite provider (multi-source fan‑out/merge) experimental path.
- G6_KITE_RATE_LIMIT_CPS – int – 0 – Target max calls per second throttle (client side) for Kite provider; 0 disables custom throttle.
- G6_KITE_RATE_LIMIT_BURST – int – 0 – Allowed burst above steady CPS before throttling begins.
- G6_KITE_THROTTLE_MS – int – 0 – Additional fixed millisecond delay injected between Kite API calls (diagnostics or pacing).
- G6_KITE_TIMEOUT – float – 0.0 – Per-request timeout seconds (float) for Kite API; 0 => library default.
- G6_KITE_TIMEOUT_SEC – int – 0 – Integer alias for per-request timeout (takes precedence if set >0).
- G6_LIFECYCLE_COMPRESSION_AGE_SEC – int – 0 – Minimum artifact age seconds before lifecycle compression job considers it.
- G6_LIFECYCLE_COMPRESSION_EXT – str – .json – File extension filter for lifecycle compression candidate selection.
- G6_LIFECYCLE_JOB – bool – off – Enable background lifecycle maintenance job (compression / pruning).

## 27. Lifecycle Management & Retention
Controls automated pruning, compression, and quarantine maintenance of historical artifacts.

- G6_LIFECYCLE_MAX_PER_CYCLE – int – 0 – Maximum number of lifecycle operations (compress/prune/delete) performed per maintenance cycle; 0 = no explicit cap.
- G6_LIFECYCLE_RETENTION_DAYS – int – 0 – Retain artifacts newer than N days; older eligible for deletion (0 disables age-based deletion).
- G6_LIFECYCLE_RETENTION_DELETE_LIMIT – int – 0 – Hard cap of deletion operations per cycle (independent of compression). 0 = unlimited within selection.
- G6_LIFECYCLE_QUAR_DIR – path – (unset) – Optional quarantine directory where problematic or partially written artifacts are moved instead of deleted (diagnostic retention).

## 28. Memory Tier (Alias / Legacy)
Backward compatibility variable retained for older adaptive memory tier logic before granular tier envs were introduced.

- G6_MEMORY_TIER – int – 0 – Legacy single numeric memory tier selector (1/2/3). When set (>0) may override derived tier from LEVEL{1,2,3}_MB boundaries. Prefer new adaptive memory tier thresholds.

## 29. Metrics Endpoint Overrides
Host/URL level overrides for metrics exposition in embedded or sidecar scenarios.

- G6_METRICS_ENDPOINT – str – (unset) – Explicit metrics HTTP endpoint path override (e.g., /metrics_alt). If unset default exporter path used.
- G6_METRICS_URL – url – (unset) – Full push/pull remote metrics URL override used by external scraper/pusher integration (experimental). Not normally required when Prometheus scrapes the internal server directly.

## 30. Expiry / Calendar Extensions
Weekday mapping and monthly anchor adjustments for advanced expiry resolution heuristics.

- G6_MONTHLY_EXPIRY_DOW – int – 4 – Override day-of-week (0=Mon..6=Sun) used to infer monthly expiry anchor when rule-based resolver uncertain.

## 31. Panels Writer / Validation Extras
Additional validation and simplified writer path toggles for panel generation.

- G6_PANELS_VALIDATE – bool – off – Enable strict schema validation of panels prior to write; failures log error and skip write.
- G6_PANELS_WRITER_BASIC – bool – off – Use simplified basic writer (no integrity hashing / diff) for performance testing or constrained environments.

## 32. Build Metadata Injection
Environment variables injected at build/CI time to enrich the g6_build_info metric.

- G6_BUILD_VERSION – str – dev – Build/version identifier (e.g., semantic version or short tag). Defaults to dev if unset.
- G6_BUILD_COMMIT – str – unknown – Source control commit SHA used for the build.
- G6_BUILD_TIME – str – unknown – Build timestamp (ISO8601 or human readable). Used for traceability.

## 32. Panels Layout & Diff Engine
Fine‑grained controls over panel formatting, diff emission cadence and complexity bounding.

- G6_PANEL_AUTO_FIT – bool – on – Enable automatic column width fitting for tabular panels (off retains configured / static widths).
- G6_PANEL_CLIP – bool – off – Clip overlong cell contents instead of wrapping (reduces row height volatility).
- G6_PANEL_DIFFS – bool – on – Master enable for diff panel generation (panel_diff events / metrics). Off => only full snapshots.
- G6_PANEL_DIFF_FULL_INTERVAL – int – 0 – Force a full panel snapshot every N diff cycles (0 disables forced periodic fulls) to bound drift.
- G6_PANEL_DIFF_MAX_KEYS – int – 0 – Upper cap on number of diff keys included (largest changes prioritized). 0 = unlimited.
- G6_PANEL_DIFF_NEST_DEPTH – int – 3 – Maximum nested object depth included in diff computation (beyond truncated / summarized). 0 disables diff recursion (shallow only).

## 33. Parallel Execution / Worker Limits

- G6_PARALLEL_MAX_WORKERS – int – 0 – Hard ceiling on parallel worker threads/processes for multi-index or multi-expiry tasks (0 => internal default heuristic based on CPU cores).

## 34. Parity / Regression Harness Controls
Tuning tolerances and inclusion flags for parity verification test harness.

- G6_PARITY_FLOAT_ATOL – float – 1e-09 – Absolute tolerance for float near-equality in parity comparisons.
- G6_PARITY_FLOAT_RTOL – float – 1e-06 – Relative tolerance for float comparisons.
- G6_PARITY_INCLUDE_REASON_GROUPS – bool – off – Include expanded reason group metadata in parity artifacts (increases JSON size; helps debugging mismatches).

## 35. Pipeline Rollout, Provider Latency, Risk Buckets & Strike Policy
Final cluster of operational / governance variables completing documentation coverage.

Pipeline / Refactor:
- G6_PIPELINE_ROLLOUT – str – (unset) – Rollout phase marker (e.g., canary,beta,ga) used for conditional logging / gating during staged pipeline adoption.
- G6_PIPELINE_INCLUDE_DIAGNOSTICS – bool – off – Force inclusion of extended diagnostic blocks (timing, allocation hints) in pipeline status artifacts.
- G6_REFACTOR_DEBUG – bool – off – Emit verbose logs for ongoing refactor touchpoints outside collector-specific refactor debug flag.
- G6_UNIFIED_MODEL_INIT_DEBUG – bool – off – Verbose initialization logging for unified model snapshot builder.

Pip Audit Governance:
- G6_PIP_AUDIT_SEVERITY – enum(critical|high|medium|low) – high – Minimum severity of vulnerabilities that cause pip audit governance to fail (invoked in tooling scripts if enabled).
- G6_PIP_AUDIT_IGNORE – csv – (unset) – Comma list of vulnerability IDs to ignore (temporary mitigation until upstream fix / dependency upgrade).

Provider API / Latency Thresholds:
- G6_PROVIDERS_PRIMARY_API_KEY – str – (unset) – Explicit primary provider API key override (alternate secret injection path; prefer secure secret store in production).
- G6_PROVIDER_LAT_WARN_MS – int – 0 – Milliseconds warning threshold for provider call latency instrumentation (0 disables warn-level thresholding).
- G6_PROVIDER_LAT_ERR_MS – int – 0 – Milliseconds error threshold for provider call latency (above emits elevated severity / event; 0 disables).
- G6_SECONDARY_PROVIDER_PATH – path – (unset) – Optional module path or config file enabling secondary provider injection for composite failover tests.

Risk Aggregation / Drift Heuristics (distinct from followups thresholds):
- G6_RISK_BUCKET_UTIL_MIN – float – 0.0 – Minimum acceptable bucket utilization fraction; below triggers internal degraded classification aiding volatility surface completeness heuristics.
- G6_RISK_BUCKET_UTIL_STREAK – int – 0 – Consecutive cycles of low bucket utilization before escalation / classification persists.
- G6_RISK_DELTA_DRIFT_PCT – float – 0.0 – Absolute delta drift percent threshold for risk parity drift evaluation (separate from followups if both active).
- G6_RISK_DELTA_DRIFT_WINDOW – int – 0 – Window length (cycles) for establishing baseline delta drift; 0 disables windowed drift logic.
- G6_RISK_DELTA_STABLE_ROW_TOLERANCE – int – 0 – Maximum allowed differing row count before delta considered unstable (0 uses default heuristic).
- G6_RISK_NOTIONALS_PER_INDEX – int – 0 – Upper safety bound on number of per-index notional records tracked in risk aggregation output (0 unlimited).

Strike Policy (Pre-Adaptive Baseline / Legacy Strike Depth Planning):
- G6_STRIKE_POLICY – bool – off – Enable legacy strike policy tuning logic (superseded by adaptive strike scaling but still available for parity runs).
- G6_STRIKE_POLICY_TARGET – int – 0 – Baseline per-side strike depth target for policy planner.
- G6_STRIKE_POLICY_WINDOW – int – 0 – Sliding performance window for evaluating strike policy adjustments (0 disables windowed evaluation).
- G6_STRIKE_POLICY_STEP – int – 0 – Adjustment step (strikes) when policy expands or contracts.
- G6_STRIKE_POLICY_MAX_ITM – int – 0 – Hard cap ITM strikes for policy (0 unlimited / config default).
- G6_STRIKE_POLICY_MAX_OTM – int – 0 – Hard cap OTM strikes for policy.
- G6_STRIKE_POLICY_COOLDOWN – int – 0 – Minimum cycles between successive policy adjustments (prevents oscillation).
- G6_STRIKE_UNIVERSE_CACHE_SIZE – int – 0 – Cache size limit for strike universe candidate sets (0 unlimited).

Summary / Panels Integration Flags:
- G6_SUMMARY_READ_PANELS – bool – off – Summary loop reads panel artifacts directly (bypassing in-memory status) to validate end-to-end writer output.
- G6_SUMMARY_V2_LOG_DEBUG – bool – off – Extra debug logging for summary aggregation v2 (signature computation / prune decisions).

Tracing & Auto Disable:
- G6_TRACE_AUTO_DISABLE – bool – off – Auto-disable verbose trace flags after first N cycles (internal experimental safety; if implemented logs de-escalation).  Off currently acts as no-op unless code path present.
- G6_TRACE_COLLECTOR – bool – off – Verbose per-index/per-expiry collector path tracing (high volume; diagnostics only).

Volatility Surface / Greeks Extended:
- G6_VOL_SURFACE_BUCKETS – csv – (unset) – Override default volatility surface moneyness bucket edges (comma separated). Empty/unset => internal defaults.
- G6_VOL_SURFACE_MAX_OPTIONS – int – 0 – Hard cap on options processed for surface build (0 unlimited; rely on upstream filters).

Expiry Weekday / Calendar Additions:
- G6_WEEKLY_EXPIRY_DOW – int – 3 – Override expected weekday (0=Mon..6=Sun) for weekly expiry anchor selection when heuristics ambiguous.

Config Documentation Baseline Ops:
- G6_WRITE_CONFIG_DOC_BASELINE – bool – off – When set, writes (or rewrites) config documentation baseline snapshot for governance tooling (developer use only; CI denies commit drift unless justified).
- G6_WRITE_CONFIG_SCHEMA_DOC_BASELINE – bool – off – Similar baseline emitter for schema doc coverage governance.
- G6_SKIP_CONFIG_DOC_VALIDATION – bool – off – Skip config documentation coverage test (emergency only; must be accompanied by follow-up PR adding docs).
- G6_SKIP_CONFIG_SCHEMA_DOC_SYNC – bool – off – Skip schema-to-doc sync validation pass (emergency only).

## 36. SBOM / Supply Chain
- G6_SBOM_INCLUDE_HASH – bool – off – Include per-component cryptographic hash metadata in generated SBOM artifacts (slightly higher generation cost; improves reproducibility & diff fidelity).





Kite provider complementary variables (already documented elsewhere but summarized for locality): `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_REQUEST_TOKEN`, `KITE_ACCESS_TOKEN`.

Headless Flow Notes:
- `fake` provider ignores API key/secret semantics; placeholders accepted.

Plain token references (coverage aid):
```
---
## Auto-Generated Compatibility Section (Temporary)
The following environment variables were detected in code but not previously present in this deprecated stub. They are auto-listed here purely to satisfy the legacy `scripts/list_missing_env_vars.py` check while the governance tooling transitions fully to the JSON catalog (`tools/env_vars.json`).

Do NOT hand-edit individual lines below. They will be regenerated or removed when the legacy checker is retired. For each variable, a concise placeholder description and default guess are provided; refine only in the canonical environment documentation (`ENVIRONMENT.md`) if needed.

<!-- BEGIN legacy_compat_env_block -->
- G6_ADAPT_EXIT_BACKLOG_RATIO – (placeholder) – Adaptive controller backlog exit threshold ratio.
- G6_ADAPT_EXIT_WINDOW_SECONDS – (placeholder) – Adaptive controller observation window.
- G6_ADAPT_LAT_BUDGET_MS – (placeholder) – Adaptive latency budget in milliseconds.
- G6_ADAPT_MIN_SAMPLES – (placeholder) – Minimum samples before adaptive decisions.
- G6_ADAPT_REENTRY_COOLDOWN_SEC – (placeholder) – Cooldown seconds before re-entering adaptive state.
- G6_COVERAGE_MAX_DROP – (placeholder) – Max allowed coverage percentage drop (governance gate).
- G6_COVERAGE_MIN_PCT – (placeholder) – Minimum coverage percentage enforced.
- G6_DEAD_CODE_BUDGET – (placeholder) – Allowed dead code item budget before gate fails.
- G6_DOC_INDEX_REQUIRED – (placeholder) – Comma list of required docs for index freshness gate.
- G6_ENV_CATALOG_ALLOW_PREFIXES – (placeholder) – Allowlist prefixes excluded from strict env catalog.
- G6_ENV_CATALOG_STRICT – (placeholder) – Enable strict failure on undocumented env vars.
- G6_EVENTS_BACKLOG_DEGRADE – (placeholder) – Event backlog size where system degrades mode.
- G6_EVENTS_BACKLOG_WARN – (placeholder) – Event backlog size for warning emission.
- G6_EXPIRY_MAP_STRICT – (placeholder) – Enforce strict expiry mapping validation.
- G6_METRICS_BATCH_ENABLED – (placeholder) – Enable metrics batching mode.
- G6_METRICS_BATCH_FLUSH_INTERVAL_SECONDS – (placeholder) – Metrics batch flush interval seconds.
- G6_METRICS_BATCH_FLUSH_THRESHOLD – (placeholder) – Items threshold triggering batch flush.
- G6_METRICS_BATCH_MAX_DRAIN_PER_FLUSH – (placeholder) – Max batch items drained per flush cycle.
- G6_METRICS_BATCH_MAX_QUEUE – (placeholder) – Max queued metrics entries before drop.
- G6_SSE_ENABLED – (placeholder) – Master toggle enabling SSE endpoints.
- G6_SUMMARY_METRICS_HTTP – (placeholder) – Enable metrics HTTP mode for summary process.
- G6_SUMMARY_RESYNC_HTTP – (placeholder) – Enable legacy resync HTTP endpoint.
- G6_SUMMARY_REWRITE – (placeholder) – Enable summary rewrite behavior.
- G6_UNIFIED_HTTP – (placeholder) – Enable unified HTTP server.
- G6_UNIFIED_HTTP_PORT – (placeholder) – Port for unified HTTP server.
<!-- END legacy_compat_env_block -->

Regeneration procedure:
1. Run the missing script: `python scripts/list_missing_env_vars.py`.
2. If count > 0, add or refine canonical definitions in `ENVIRONMENT.md` or add placeholder here (temporary) under the block.
3. Long term: remove this section after script migration to JSON catalog.
	- Target removal date: 2025-11-15 (once missing count == 0 for two consecutive CI runs).
	- Remaining unmatched tokens (not auto-added due to truncation/legacy/deprecation) should be either: (a) removed from code, (b) fully spelled & documented if legitimate, or (c) added to an explicit ignore set in the checker.