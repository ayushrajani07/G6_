# Changelog

All notable changes to this project will be documented in this file. Dates use ISO format (YYYY-MM-DD).

## [Unreleased]
### Cleanup
- Pruned deprecated `scripts/run_live.py` (fully removed) and consolidated logging env var documentation block to eliminate duplicate governance warnings.
- Tombstoned legacy README variants (`README_COMPREHENSIVE.md`, `README_CONSOLIDATED_DRAFT.md`, `README_web_dashboard.md`) pending final deletion after external reference audit.
 - Removed legacy README variants (2025-10-03) after confirming no test/external references.
### Maintenance
- Squashed prior documentation/cleanup commits (run_live.py removal, legacy README tombstone + deletion, env var docs consolidation) into single commit `d5ebb30` for history hygiene (no functional changes). Original hashes consolidated: d049712, 7285c74, 01e0988.
### Added
- ANSI colorized logging (non-Rich) via new env vars: G6_LOG_COLOR_MODE (auto|on|off) and G6_LOG_COLOR_FORCE for CI/Windows forcing. Includes keyword highlighting for success/pass/fail/warning tokens.
- G6_STRUCT_EVENTS_FORMAT env flag (json|human|both) enabling concise human-readable summaries for structured collector events alongside or instead of raw JSON lines.
- G6_SUPPRESS_GROUPED_METRICS_BANNER to fully silence grouped metrics registration banner.
- G6_SUPPRESS_DUPLICATE_METRICS_WARN and G6_DUPLICATES_LOG_LEVEL for fine-grained duplicate metrics warning control.
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

