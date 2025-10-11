 - Further archival (Wave A prune): demo/static & helper artifacts `sample_by_index.html`, `sample_grid.html`, `overlays_demo.html`, `list_lines*.py`, `inspect_indent.py`, `walk1.py` moved to `archive/` with stubs.
# Changelog

All notable changes to this project will be documented in this file. Dates use ISO format (YYYY-MM-DD).

## [Unreleased]
### Removed
- Synthetic fallback system fully excised: phase (`synthetic_fallback`), helper module (`modules/synthetic_fallback.py` logic), status code path (`SYNTH`), settings flag (`disable_synthetic_fallback` / env `G6_DISABLE_SYNTHETIC_FALLBACK`), metrics counter & recording helper, parity harness & structured event synthetic fields, provider capability advertisement. Inert import-safe stubs retained (`collectors.helpers.synthetic`, `collectors.modules.synthetic_fallback`) emitting deprecation warnings if invoked. All tests referencing synthetic behavior either removed or converted to assert absence.
 - Legacy parity harness (W4-11): removed `src/orchestrator/parity_harness.py`, `src/collectors/parity_harness.py`, legacy orchestrator parity tests (`test_orchestrator_parity*`, `test_parity_golden_verify.py`) and deprecated snapshot generator scripts now exit early. Parity validation now exercised via `compute_parity_score` tests and parity signature logic. Guidance: use pipeline parity score logging & metrics (`pipeline_parity_score`, rolling avg gauge) for ongoing parity observability.

### Changed
- Pipeline & expiry processor no longer branch on synthetic fallback; empty quote scenarios now surface directly to coverage / alert logic (simpler reasoning, fewer silent data fabrications). Documentation updated to reflect direct empties (operators should rely on coverage + alert metrics rather than synthetic presence).

### Added
- (Historical reference only) Prior consolidation work: CollectorSettings previously extended with heartbeat/outage/synthetic/salvage/recovery/quiet trace flags; with synthetic removal the synthetic flag is now legacy and omitted from summaries.
- Immutability tests for CollectorSettings.
- `kite_provider_factory()` convenience helper wrapping ProviderConfig snapshot + optional overrides; avoids direct constructor credential usage (suppresses deprecation warning for normal instantiation paths).
- Structured provider event instrumentation (`provider_events` module) with gated JSON line emission via `G6_PROVIDER_EVENTS` / `G6_STRUCT_LOG`; context manager API `provider_event(domain, action)` added.
- Provider structured event tests (`tests/test_provider_structured_events.py`) asserting success + error outcome emission and error_class taxonomy mapping.
- Internal error taxonomy raise helper `_raise_classified` reducing duplication across provider methods.
- Auth wrapper helpers `ensure_client_auth` / `update_credentials_auth` added to `src/broker/kite/auth.py` (facade slimming for Phase A7).

### Changed
- Unified collectors & expiry processor refactored to use consolidated settings (reduced env lookups on hot path).
- Partial Provider modularization (A7): extracted rate limiter + startup summary logic into `src/broker/kite/provider_core.py`; `kite_provider.py` now delegates to helpers reducing inline orchestration LOC and clarifying future split boundaries.
- Provider further modularized (A7 continuation): migrated credential ensure/update logic to auth module; instruments/expiries/options remain separate; facade now primarily orchestration + deprecation shims.
- Provider methods (`get_instruments`, `get_ltp`, `get_quote`, expiry + options accessors, health) instrumented with structured events (no behavior change; gating defaults to disabled for zero overhead).
- Exception classification & re-raise in provider consolidated (taxonomy applied consistently: Auth/Timeout/Recoverable/Fatal).

### Removed
- Deprecated provider shim `src.providers.kite_provider` (A24) – import from `src.broker.kite_provider`.
- Direct hot-path parsing of multiple env flags (heartbeat, outage, synthetic fallback, salvage, recovery, quiet/trace) now centralized; legacy fallback branches slated for removal 2025-10-20.
 - Legacy implicit credential discovery inside `KiteProvider` (direct `os.environ` reads for `KITE_API_KEY` / `KITE_ACCESS_TOKEN`) removed; construction now exclusively uses `ProviderConfig` snapshot (`get_provider_config()` + `from_provider_config`). `KiteProvider.from_env()` now only returns a snapshot-backed instance and emits a deprecation warning (no env scanning logic retained). Update any out-of-repo scripts accordingly.
### Added
- Cleanup scaffolding: inventory generator (`scripts/cleanup/gen_inventory.py`), env var scanner (`scripts/cleanup/env_scan.py`), initial validation stub (`scripts/cleanup/validate_cleanup.py`), documentation index (`docs/INDEX.md`), and consolidated cleanup plan (`docs/clean.md`).
 - Shared SSE security & connection governance helper module `scripts/summary/sse_shared.py` (Phase 1 extraction: auth, IP allow, UA allow, per-IP connection rate limiting, rate spec parsing).
 - Phase 2 SSE extraction: event framing (`write_sse_event`) and per-connection token bucket limiter (`allow_event_token_bucket`) centralized; legacy `sse_http` and `unified_http` now delegate for zero drift.
 - Grafana modular generator Phase D/E/F: new dashboard plans (`bus_health`, `system_overview_minimal`), enriched panel metadata (`g6_meta.metric`, `family`, `kind`, `source`, `split_label`), cross-metric efficiency panels tagged with `source=cross_metric`, verbose drift detection via `G6_DASHBOARD_DIFF_VERBOSE=1` (JSON title lists), generator version bump to `phaseDEF-1`, and new doc `GRAFANA_GENERATION.md` plus README section 7.7.1.
### Changed
- Archived debug & temp scripts: `debug_catalog_http*.py`, `temp_trend_check.py`, `temp_event_debug.py`, `temp_debug_unified_http.py` moved to `archive/` with stubs left in place.
- Additional archival: `temp_http_trend_check.py`, `temp_sse_diag.py`, `temp_repro_health_test.py`, `temp_debug2.py` migrated to `archive/` with explanatory preserved copies. Originals replaced by inert stubs.
 - `unified_http` now delegates all auth / ACL / rate limiting to `sse_shared.enforce_auth_and_rate` reducing duplication and flake surface for per-IP rate limit tests.
 - `sse_http.SSEHandler` now delegates `_write_event` and `_allow_event` to shared helpers (metrics + truncation semantics preserved; fallback minimal framing retained for defensive import races).

### Notes
- No functional runtime changes; all additions are tooling / documentation groundwork for Wave A cleanup.
 - SSE refactor intentionally preserved ordering of rejection codes (401 -> 403 -> 429) and UA precedence; full SSE & unified HTTP test matrix remained green after both extraction phases.
### Stability (2025-10-05)
- Test suite stabilization for order-dependent flakes:
  - Panel transactions: resilient multi-path commit (copy + rescue) with optional fallback verification; added opt-in diagnostics (`G6_PANELS_TXN_AUTO_DEBUG=1`).
  - SSE per-IP connect rate: cleared `_ip_conn_window` each test to prevent cross-test 429 leakage.
  - Summary diff metrics: deterministic zero-inc label seeding + reseed on registry reset; env override forces diff enable when `G6_SUMMARY_RICH_DIFF` truthy.
  - Rate limiter tests: replaced event loop time dependency with `perf_counter`.
  - Added stabilization doc `CHANGELOG_STABILIZATION.md` with deeper rationale & follow-ups.
  - New env: `G6_PANELS_TXN_AUTO_DEBUG` (previous implicit auto-on during pytest now gated).
### Cleanup
- Pruned deprecated `scripts/run_live.py` (fully removed) and consolidated logging env var documentation block to eliminate duplicate governance warnings.
- Tombstoned legacy README variants (`README_COMPREHENSIVE.md`, `README_CONSOLIDATED_DRAFT.md`, `README_web_dashboard.md`) pending final deletion after external reference audit.
 - Removed legacy README variants (2025-10-03) after confirming no test/external references.
- Removed summary legacy fallback & `--no-unified` flag; unified loop is now sole execution path. Deleted `StatusCache` and `plain_fallback` shims (plain mode now uses `PlainRenderer` or minimal key listing). Added failure return code (1) when unified loop aborts instead of silent fallback.
### Maintenance
- Squashed prior documentation/cleanup commits (run_live.py removal, legacy README tombstone + deletion, env var docs consolidation) into single commit `d5ebb30` for history hygiene (no functional changes). Original hashes consolidated: d049712, 7285c74, 01e0988.
### Added
- ANSI colorized logging (non-Rich) via new env vars: G6_LOG_COLOR_MODE (auto|on|off) and G6_LOG_COLOR_FORCE for CI/Windows forcing. Includes keyword highlighting for success/pass/fail/warning tokens.
- G6_STRUCT_EVENTS_FORMAT env flag (json|human|both) enabling concise human-readable summaries for structured collector events alongside or instead of raw JSON lines.
- G6_SUPPRESS_GROUPED_METRICS_BANNER to fully silence grouped metrics registration banner.
- G6_SUPPRESS_DUPLICATE_METRICS_WARN and G6_DUPLICATES_LOG_LEVEL for fine-grained duplicate metrics warning control.
- Metrics: Optional initialization profiling (`G6_METRICS_PROFILE_INIT=1`) recording per-phase timings (group_gating, spec_registration, provider_mode_seed, aliases_canonicalize) in `registry._init_profile` with total.
### Documentation / Governance
- Documentation consolidation: unified environment variable reference now exclusively in `docs/env_dict.md`; converted `docs/ENVIRONMENT.md` into archival stub to eliminate duplication.
- Added metrics facade modularization note to `docs/METRICS.md` (Phase 3.x) and config duplication policy update in `docs/config_dict.md`.
- Inserted logging & structured events formatting variable consolidation note in `env_dict.md`; added duplication policy (single authoritative source for env vars).
- Added Module & Workflow Status Matrix (Section 3.1) to `README.md` with status markers [C]/[IP]/[P]/[E]/[D].
### Removed / Deprecated
- Removed deprecated script `scripts/run_live.py` (test assertion now passes); update any external automation to invoke orchestrator or `g6 summary`.
### CLI
- Added `retention-scan` subcommand to `scripts/g6.py` providing basic CSV storage footprint metrics (pre-retention engine observability). See README Section 17.1.
### Added (Provider Efficiency & Resilience Phase 1)
- Kite quote path Phase 1 rate limiting: introduced lightweight token-bucket + cooldown limiter (`src/broker/kite/rate_limit.py`). Env flags:
  - `G6_KITE_LIMITER=1` enables limiter (opt-in)
  - `G6_KITE_QPS` sustained tokens/sec (default 3)
  - `G6_KITE_RATE_MAX_BURST` bucket capacity (default 2x QPS)
  - `G6_KITE_RATE_CONSECUTIVE_THRESHOLD` consecutive 429/"Too many requests" errors to trigger cooldown (default 5)
  - `G6_KITE_RATE_COOLDOWN_SECONDS` cooldown duration (default 20)
  Limiter integrates into `get_quote` prior to network call; upon detected provider rate-limit responses tokens are not refunded and cooldown opens after threshold.
- In‑memory per‑symbol quote cache (TTL, default 1s via `G6_KITE_QUOTE_CACHE_SECONDS`) collapsing back‑to‑back duplicate quote requests, reducing outbound provider calls and smoothing burst pressure before batching (Phase 2) is implemented.

### Changed (Logging Noise Reduction)
- Suppressed duplicate grouped metrics registration banner: now logs only once per process, avoiding repetitive console noise in long-lived tasks.
- Added once‑per‑day emission guard for the `DAILY OPTIONS COLLECTION LOG` header (respects local date roll). Subsequent cycles the same day suppress header to maintain concise loop output.
- Reduced incidental verbosity around repeated provider rate limit errors; limiter now centralizes these events without spamming identical exception traces.

### Tests
- Added regression tests for Phase 1 limiter cooldown & token refill behavior (`tests/test_rate_limiter.py` new test cases `test_phase1_rate_limiter_cooldown_blocking`, `test_phase1_rate_limiter_token_refill_behavior`).
- Added placeholder daily header suppression test (`tests/test_daily_header.py`) asserting single header emission simulation (lightweight until full cycle harness exposure is refactored).

### Upcoming (Planned – Not Yet Implemented)
- Phase 2 micro‑batching IMPLEMENTED (see Added above for batcher module) — future enhancement: add metrics & early-fire optimization.
- Loop heartbeat logging implemented (`G6_LOOP_HEARTBEAT_INTERVAL` seconds) emitting concise `hb.loop.heartbeat` line with cycles & last options processed; future: include avg latency & rate limiter stats.
- Extended tests to exercise real cycle invocation for daily header gating & integrated batching effectiveness metrics once implemented.

## [2025-10-08]
### Deprecation / Hygiene
- Metrics deep import deprecation enforcement refined: facade sets sentinel to suppress redundant warning; genuine direct `import src.metrics.metrics` still emits unless `G6_SUPPRESS_LEGACY_WARNINGS=1`.
- Replaced remaining runtime deep import usage in `analytics.risk_agg` with facade `from src.metrics import get_metrics`.
- Added facade helper `_reset_metrics_summary_state()` eliminating need for tests to deep import metrics module to clear one-shot summary sentinel.
- Gated legacy `_register` shim deprecation noise behind opt-in env `G6_ENABLE_REGISTER_SHIM_WARN=1` (default silent for cleaner baseline runs) while preserving functionality.
- Introduced `test_deprecation_hygiene.py` ensuring no unexpected `DeprecationWarning` emissions under representative import sequence; supports verbose mode via `G6_DEPRECATION_HYGIENE_VERBOSE=1`.
- Tombstoned obsolete CollectorSettings immutability assertions (synthetic fallback flag removed) retaining minimal singleton stability test; stale attribute references purged.
- Orchestrator pipeline flag deprecation remains validated in dedicated test; additional suite runs avoid emitting its warning by not setting deprecated flag.

### Added (Dashboard Envelope Completion – W4-13)
- Finalized panel envelope schema (`panel-envelope-v1`) introducing explicit fields: `version`, `generated_at`, `meta.source`, `meta.schema`, and truncated data hash `meta.hash` (12 hex) alongside existing `panel`, `updated_at`, `data`.
- All dashboard panels now emitted exclusively as `<name>_enveloped.json` by default (indices_panel, alerts, system, performance, analytics, links, etc.).
- Introduced environment flag `G6_PANELS_LEGACY_COMPAT=1` enabling temporary dual-write of legacy plain `<name>.json` files for rollback / consumer migration validation.
- Added tests `test_panels_enveloped_only.py` asserting envelope-only default and parity under compatibility mode; updated runtime validation tests to accept new fields.

### Changed (Panels Emission)
- Legacy plain panel filenames no longer written unless compatibility flag is set (previous duplication removed to reduce IO + confusion and eliminate drift risk).
- README panel schema section rewritten to reflect envelope (`panel`, `version`, `generated_at`, `updated_at`, `data`, `meta{source,schema,hash}`).
### Added (Fatal Ratio Alert Validation – W4-02)
- Formalized fatal ratio alert coverage: existing recording rule `g6:pipeline_fatal_ratio_15m` and alerts `G6PipelineFatalSpike` (0.05 > 10m), `G6PipelineFatalSustained` (0.10 > 5m), and `G6PipelineParityFatalCombo` (parity < 0.985 & fatal ratio > 0.05 > 5m) now guarded by dedicated test `tests/test_fatal_ratio_alert_rule.py` asserting expression thresholds and `for:` durations. Tracking updated in `WAVE4_TRACKING.md` (status Done). No runtime changes; codifies acceptance & prevents silent drift.
### Added (Bench P95 Regression Alert – W4-10)
- Introduced Prometheus alert `BenchP95RegressionHigh` (warning, 5m) firing when `g6_bench_delta_p95_pct > g6_bench_p95_regression_threshold_pct` and threshold gauge non-negative. Supports configurable regression sensitivity via env `G6_BENCH_P95_ALERT_THRESHOLD` (exported gauge `g6_bench_p95_regression_threshold_pct`). Test `tests/test_bench_p95_regression_alert_rule.py` validates alert presence, expression shape, and duration. README section updated (Runtime Benchmark) and tracking marked Done.
### Added (Parity Snapshot CLI – W4-14)
- New operator tool `scripts/parity_snapshot_cli.py` producing JSON snapshot with parity score (components, weights, missing, details), rolling window simulation (optional), and alert category deltas + symmetric diff tokens. Supports flags: `--legacy/--pipeline` JSON inputs, `--weights`, `--extended/--shape/--cov-var` feature toggles, `--rolling-window`, `--version-only`, and `--pretty`. Test `tests/test_parity_snapshot_cli.py` validates schema integrity and component presence. Tracking & README updated.
### Added (Alert Parity Anomaly Event – W4-15)
### Added (Parity Weight Tuning Study – W4-18)
- Introduced parity weight study utility `scripts/parity_weight_study.py` producing empirical component dispersion artifact to guide non-equal weight adoption.
- Modes: explicit `--pairs`, directory heuristic `--dir`, synthetic `--synthetic N` (noise & missing probability configurable). Methods: `signal_scaled` (default), `inverse-var`, `variance`.
- Output schema includes per-component statistics (count, mean, std, p50/p90/p95, mean_miss, signal_strength) and normalized weight recommendations (`weight_plan.normalized`).
- Added design documentation Section 4.7 detailing methodology, schema, adoption workflow, guardrails, and future enhancements.
- Sample artifact `data/parity_weight_study_sample.json` (synthetic) checked in for reference.
- Tracking W4-18 marked Done; README pointer pending (optional).

- Introduced structured event emission `pipeline.alert_parity.anomaly` when weighted alert parity difference exceeds `G6_PARITY_ALERT_ANOMALY_THRESHOLD` (disabled by default with -1). Minimum category union gate via `G6_PARITY_ALERT_ANOMALY_MIN_TOTAL` (default 3) reduces noise. Implemented in `src/collectors/pipeline/anomaly.py` and invoked post parity score computation in pipeline loop. Test `tests/test_parity_anomaly_event.py` covers emission, non-emission below threshold, and disabled mode.
- Manifest hashing logic concept unchanged (hash still computed over canonical `data` only) but documentation clarified alignment with `meta.hash` field.

### Added (Retry Policy Documentation – W4-17)
- Added Pipeline Design Section 4.6 detailing per-phase retry & backoff strategy: principles, metrics (`g6_pipeline_phase_attempts`, `g6_pipeline_phase_retries`, `g6_pipeline_phase_retry_backoff_seconds`, `g6_pipeline_phase_last_attempts`, `g6_pipeline_phase_outcomes`), environment knob `G6_RETRY_BACKOFF` (base delay), phase matrix (deterministic vs guarded vs whole-phase retries), backoff formula (exponential + jitter capped at 5s), taxonomy interaction (Fatal vs Recoverable vs Abort), operator guidance (monitor fetch retry density & p95 backoff), and future enhancements (adaptive scaling, configurable jitter/cap, anomaly on retry density). Tracking W4-17 marked Done.

### Deprecation
- Legacy plain panel format slated for removal of dual-write flag after deprecation window (target: remove `G6_PANELS_LEGACY_COMPAT` no earlier than 2025-11-01 pending external dashboard confirmation). Consumers should switch to enveloped files immediately.

### Rationale
- Provides forward-compatible space (version + meta schema tag) for compression, signatures, or delta streaming without schema ambiguity.
- Stabilizes integrity & diff tooling (hash unaffected by timestamp churn) while reducing duplication overhead.

### Follow-ups
- Evaluate adding optional `meta.encoding` for large payload compression.
- Potential removal of duplicated `updated_at` once all downstream consumers rely solely on envelope semantics (track in WAVE4_TRACKING.md follow-ups section).

### Added (Benchmark P95 Regression Alert – W4-10 Finalization)
### Added (Panel Performance Benchmark – W4-19)
- New script `scripts/bench_panels.py` measuring JSON read + parse latency for all `*_enveloped.json` panel files. Reports per-panel distribution stats (mean, p95, min, max, count) plus aggregate summary.
- Test `tests/test_panels_perf_benchmark.py` validates schema & basic invariants (non-negative, count per iteration, aggregate totals).
- Supports quick regression detection after schema or payload size changes; intended for CI smoke or local performance tracking. Usage: `python scripts/bench_panels.py --panels-dir data/panels --iterations 50 --json`.

- Prometheus alert `BenchP95RegressionHigh` comparing `g6_bench_delta_p95_pct` against configured threshold gauge `g6_bench_p95_regression_threshold_pct` (env `G6_BENCH_P95_ALERT_THRESHOLD`). Fires after 5m sustained breach.
- Early gauge creation in `_maybe_run_benchmark_cycle` ensures rule evaluates even if a new benchmark run is skipped due to interval gating.
- Documentation: Operator Manual section 13.7, README runtime benchmark section, Pipeline Design 8.3.2.
- Tests: `test_bench_threshold_gauge.py`, `test_bench_alert_rule_present.py` validate gauge emission & alert rule presence.

### Added (CI Gate: Parity & Fatal Guard – W4-20)
- New script `scripts/ci_gate.py` enforcing minimum rolling parity (`g6_pipeline_parity_rolling_avg`) and maximum fatal ratio (`g6:pipeline_fatal_ratio_15m`) thresholds in CI.
- Exit codes: 0 (pass), 1 (failure: threshold breach or fetch/parse error in strict mode), 2 (soft-missing when metrics absent and `--allow-missing` supplied).
- Supports scraping via `--metrics-url` or offline evaluation with `--metrics-file`; emits structured JSON with `--json` for machine parsing / annotations.
- Test `tests/test_ci_gate.py` covers evaluation branches (pass, parity fail, fatal fail, missing metrics) and subprocess CLI contract.
- README: new section under Metrics & Observability describing usage and sample GitHub Actions workflow snippet.
- Intended to run after a brief warm-up (ensure rolling parity gauge populated) before merge/deploy to guard parity regressions and surfacing elevated fatal error ratios early.

### Internal
- Added environment flag `G6_FORCE_METRICS_DEEP_IMPORT_WARN=1` to re‑enable deep import warning even when imported through facade (diagnostic).
- Clarified deprecation gating guidance in metrics module docstring (future removal window unaffected).

## [2025-09-30]
### Refactor (Metrics Modularization Phase – Cache & Panels Integrity Extraction)
- Extracted remaining inline grouped metric families from `group_registry.py`:
	- `cache` metrics moved to `src/metrics/cache_metrics.py` (registered under existing alias group `perf_cache` which resolves to `cache` preserving group filtering semantics and spec alignment). Metrics retained: `root_cache_hits`, `root_cache_misses`, `root_cache_evictions`, `root_cache_size`, `root_cache_hit_ratio` (unchanged names & help text).
	- `panels_integrity` metrics moved to `src/metrics/panels_integrity.py`. Original spec / legacy metrics (`panels_integrity_ok`, `panels_integrity_mismatches`) preserved verbatim. Added optional extended observability gauges/counters (`panels_integrity_checks`, `panels_integrity_failures`, `panels_integrity_last_elapsed`, `panels_integrity_last_gap`, `panels_integrity_last_success_age`) as additive (no spec dependency, safe expansion).
- Updated `group_registry.register_group_metrics` to delegate to the new modules; removed now‑redundant inline registration blocks.
- Ensured spec minimum safeguard (`spec_fallback.ensure_spec_minimum`) still covers required cache & panels_integrity metrics; synthetic fallback unaffected.
- All gating & enable/disable environment variable flows unchanged (alias map `perf_cache` -> `cache` still honored for filtering & documentation).
- Full test suite remained green after extraction (baseline 568 passed / 26 skipped, 2 warnings) confirming no behavioral drift.

### Cleanup / Deprecations (2025-10-02)
- Added backward compatibility shim `src/metrics/cache.py` delegating to canonical `cache_metrics.init_cache_metrics` (no behavior change; deprecation table updated).
- Marked legacy duplicate gauge `g6_vol_surface_quality_score_legacy` for removal (see `DEPRECATIONS.md`). Dashboards should migrate to `g6_vol_surface_quality_score`.

### Refactor (Collectors Modularization Phase 9 – Strike Universe, Async Enrichment, Alerts, Status Finalization)
- Extracted strike discovery into dedicated module `src/collectors/modules/strike_universe.py` providing `build_strike_universe` (policy + metadata + adaptive caching). Replaces scattered `compute_strike_universe` / ad‑hoc strike loops with a single, testable abstraction.
- Introduced optional asynchronous quote enrichment scaffold `src/collectors/modules/enrichment_async.py` offering thread‑pooled batch provider calls when `G6_ENRICH_ASYNC=1` (graceful fallback to synchronous path on errors or when flag unset).
- Added alert aggregation module `src/collectors/modules/alerts_core.py` computing consolidated alert summary fields (e.g. `alert_index_failure`, `alert_low_strike_coverage`, `alerts_total`) from per-index / per-expiry coverage & structural signals; integrated into both legacy (`unified_collectors`) and pipeline paths for parity.
- Consolidated final status & partial reason tally logic behind facade `src/collectors/modules/status_finalize_core.py` (re‑exports `finalize_expiry` & helpers) ensuring stable import surface for downstream modules and reducing churn in `expiry_processor` & pipeline.
- Pipeline (`pipeline.run_pipeline`) now sequences: expiry map → strike universe (cached) → (async) enrichment → synthetic fallback → preventive validation → coverage + status finalize → alerts aggregation → snapshot summary build.

### Added
- Strike universe metadata: each call returns structured fields (`step`, `atm_bucket`, `cache_hit`, `source`) enabling observability and future policy evolution without changing call sites.
- LRU caching for strike universes (capacity via `G6_STRIKE_UNIVERSE_CACHE_SIZE`, default 256) with optional Prometheus counters (`strike_universe_cache_hits` / `strike_universe_cache_miss` when metrics namespace present).
- Alert categories (initial set): `index_failure`, `index_empty`, `expiry_empty`, `low_strike_coverage`, `low_field_coverage`, `low_both_coverage` with thresholds tunable: `G6_ALERT_STRIKE_COV_MIN` & `G6_ALERT_FIELD_COV_MIN` (defaults chosen conservatively; documented in module docstring).
- Parity harness v2 extended to capture: alert summary fields, `partial_reason_totals`, average strike & field coverage aggregates; updated diff logic treats absent alert block on legacy path as additive (no regression) until full rollout.
- Performance smoke benchmark script `scripts/bench_perf_smoke.py` comparing legacy vs pipeline (sync & async) collectors for micro (synthetic) cycles; outputs JSON including per-mode distribution stats & relative speedups.

### Environment / Flags
- `G6_ENRICH_ASYNC=1`: Enable threaded enrichment (safe fallback on exception; failures logged at debug and revert to sync for that cycle only).
- `G6_STRIKE_UNIVERSE_CACHE_SIZE`: Integer capacity (entries) for strike LRU; set to 0 or 1 to effectively disable caching for diagnostics.
- `G6_ALERT_STRIKE_COV_MIN` / `G6_ALERT_FIELD_COV_MIN`: Float thresholds (0..1) defining alert triggers for low coverage categories.

### Tests
- `tests/test_strike_universe.py`: Validates caching behavior, scale/step overrides, zero ATM handling, deterministic metadata.
- `tests/test_enrichment_async.py`: Ensures async path produces identical enriched quote set & falls back cleanly when executor disabled.
- `tests/test_alerts_core.py`: Verifies alert aggregation across mixed normal / edge scenarios and no‑alert path stability.
- `tests/test_parity_alerts_and_strike_meta.py`: Asserts structural parity (alerts + strike/field coverage aggregates + partial reasons) between legacy and pipeline collectors.

### Performance (Synthetic Smoke – Informational Only)
- Benchmark (`scripts/bench_perf_smoke.py --indices NIFTY,BANKNIFTY --cycles 3`) on synthetic provider produced approximate mean cycle durations:
	- legacy: ~0.02139 s
	- pipeline_sync: ~0.000207 s (≈103× faster)
	- pipeline_async: ~0.000159 s (≈135× faster overall; ≈1.3× over pipeline_sync)
- Figures are micro / synthetic (in‑process, deterministic data); real market IO & provider latency will reduce absolute speedup but relative improvements driven by extraction + reduced redundant computation expected to persist.

### Migration Notes
- Existing callers need no changes; legacy path remains default. Opt into pipeline via `G6_PIPELINE_COLLECTOR=1`; optionally layer async enrichment with `G6_ENRICH_ASYNC=1` after observing baseline parity & metrics.
- Alert fields and `alerts_total` are additive; downstream consumers should treat absence as "no alerts enumerated" (backward compatible). Once stabilized, alert fields may move inside `snapshot_summary` canonical schema (tracked for Phase 10 decision).
- Strike universe abstraction is drop‑in: older internal helpers (`compute_strike_universe` in `strike_depth`) still accessible but now considered internal; future phases may deprecate direct use in favor of `build_strike_universe` exclusively.

### Observability / Metrics
- Cache hit/miss counters (when metrics registry present) provide early signal for mis‑sized strike universe caching or atypical ATM volatility causing frequent misses.
- Alert summary enables dashboards to surface coverage regression without parsing deep per-expiry structures.

### Notes
- All changes are additive; no existing public API removals in this phase. Full test suite remained green throughout (452 passed / 23 skipped after final Phase 9 commit). Parity harness v2 ensures regression visibility before promoting pipeline+async to default path in a later phase.

## 2025-09-29
### Refactor (Collectors Modularization Phase 6 – Staged Pipeline)
- Implemented real staged pipeline execution (`src/collectors/modules/pipeline.py`) sequencing: expiry map → strike discovery → enrichment (quote merge) → synthetic quote fallback → preventive validation → coverage & adaptive strike refinement → benchmark artifact bridge & anomaly annotation. The legacy `run_unified_collectors` now delegates when `G6_PIPELINE_COLLECTOR=1` (guarded by `G6_PIPELINE_REENTRY` sentinel to avoid recursion).
- Extracted enrichment logic into `src/collectors/modules/enrichment.py` (quote merge & normalization) detaching ~180 lines from the monolith.
- Extracted synthetic quote generation + fallback pathway into `src/collectors/modules/synthetic_quotes.py` (deterministic placeholder pricing & volume heuristics).
- Extracted preventive validation (structural sanity checks, partial_reason seeding, zero-option expiry pruning) into `src/collectors/modules/preventive_validate.py`.
- Incremental parity instrumentation: lightweight `parity_accum` retained (debug mode) for future snapshot diffing without affecting hot path.

### Added
- Introduced deterministic pipeline parity test `tests/test_pipeline_parity_basic.py` comparing legacy vs pipeline structural fields (counts, core metrics) while normalizing zero-option expiries.
- Environment flags documented/recognized: `G6_PIPELINE_COLLECTOR`, `G6_PIPELINE_REENTRY`, `G6_PREVENTIVE_DEBUG` (verbose preventive validation), plus existing clamp & benchmark tunables referenced in new modules.

### Fixed
- Resolved anomaly test failures by updating `benchmark_bridge` anomaly detector callable signature to accept `(series, threshold)` explicitly (previous implicit threshold caused mismatched invocation during artifact annotation).
- Addressed intermittent prefilter clamp test failures (market hours gating produced empty expiries) by forcing deterministic open-market condition within `tests/test_prefilter_clamp.py` via `G6_FORCE_MARKET_OPEN=1`.
- Parity instability (zero-option expiry count divergence) resolved through normalization logic in parity test (counts only expiries with >0 options) ensuring stable comparison under varied provider scenarios.

### Tests
- New targeted unit coverage for extracted modules implicitly exercised through existing benchmark/anomaly, clamp, and parity suites (no behavior drift—full suite now at 417 passed / 23 skipped on internal validation at date of entry).

### Notes
- Further extraction (partial_reason life-cycle consolidation, snapshot migration to pipeline, and field coverage parity expansion) scheduled for a subsequent phase.
- Legacy monolith retains fallback paths; enabling `G6_PIPELINE_COLLECTOR=1` is presently optional and intended for progressive rollout & monitoring.

## 2025-09-28
### Added
- Pluggable token provider abstraction (`src/tools/token_providers/`) with `kite` (real) and `fake` (deterministic) implementations.
- Headless token acquisition mode (`--headless` / `G6_TOKEN_HEADLESS=1`).
- Fast-exit behavior: when a valid token exists and autorun is disabled (`--no-autorun`), headless or non-`kite` providers exit cleanly without an interactive prompt.

### Changed
- `src/tools/token_manager.py` refactored to delegate validation/acquisition to provider objects.

### Documentation
- Updated consolidated `README.md` (Tokens & Auth section) with provider selection, headless mode, and fast-exit semantics.

## 2025-09-16
### Added
- Initial comprehensive architecture & operations guide (`README_COMPREHENSIVE.md`) later merged into unified `README.md` (2025-10-01).

## Unreleased
### Improved
- Metrics: Enhanced duplicate guard suppression to ignore benign alias families (legacy_*, *_total, *_alias) and removed need for *_total_total fallback by preventing creation of redundant double-suffixed attributes in `aliases.ensure_canonical_counters`.
- Added regression tests (`tests/test_metrics_duplicates.py`) ensuring benign alias sets produce no duplicate summary while true collisions are still detected.
- Provider mode seeding hardened. Removed recursive call to set_provider_mode during registry init; direct seeding with a micro-timeout (`G6_PROVIDER_MODE_SEED_TIMEOUT`, default 0.25s) and optional force/skip env (`G6_METRICS_FORCE_PROVIDER_MODE_SEED`). Added regression test `test_provider_mode_seed`.
- Stale gating: moved consecutive stale cycle counter from process-global os module state to registry-scoped attribute (`_consec_stale_cycles`) improving test isolation and eliminating cross-test leakage; added `test_stale_gating_isolated`.
 - Panels hashing: hardened canonical hashing via `_canonical` normalization (float normalization including -0.0 -> 0.0, NaN/Inf sentinels `__NaN__` / `__Inf__` / `__-Inf__`, deterministic set ordering, dict key coercion to str, stable nested ordering). Added robustness tests (`test_panel_hash_hardening.py`) covering key order independence, float equivalence (1 vs 1.0), -0.0 handling, Inf/-Inf, NaN length sensitivity, and set ordering determinism. Ensures downstream diff, SSE, and resync logic remain stable across platform JSON float quirks.

### Internal
- Pruned obsolete duplicate suppression branch for `_total_total` patterns after source prevention.

