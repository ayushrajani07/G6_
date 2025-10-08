# G6 Deprecations Register

_Last updated: 2025-10-03 (reinstated legacy section headers for governance tests)_

This document tracks features, flags, and modules scheduled for removal along with their migration guidance and timelines. All deprecations follow the governance process:

1. Introduce alternative implementation (feature-flagged or side-by-side).
2. Add parity / confidence instrumentation (tests, harness, metrics).
3. Emit one-time deprecation warning on legacy path invocation.
4. Document here with earliest removal release (N+2 policy by default).
5. After two green release cycles with no blocker regressions, remove legacy code & update docs.

## Deprecated Execution Paths

The following execution paths or scripts are deprecated or have been removed. Historical entries retain the original identifier for auditability (tests assert presence until governance window fully closes).

## Active Deprecations

| Item | Replacement | First Warn Release | Earliest Removal* | Migration Guidance | Notes |
|------|-------------|--------------------|-------------------|--------------------|-------|
| `unified_main.collection_loop` (legacy orchestration loop) | `src.orchestrator.loop.run_loop` + `run_cycle` | 2025-09-26 (post parity harness) | GATED (R+1 removal target) | Use orchestrator bootstrap; set `G6_ENABLE_LEGACY_LOOP=1` only for transitional tests. | Disabled by default; temporary enable: `G6_ENABLE_LEGACY_LOOP=1`; suppress warn: `G6_SUPPRESS_LEGACY_LOOP_WARN=1`. Max cycles env alias resolved (`G6_LOOP_MAX_CYCLES` prefers, `G6_MAX_CYCLES` still honored). |
| (REMOVED) `scripts/run_live.py` | `scripts/run_orchestrator_loop.py` | 2025-09-26 | REMOVED 2025-10-01 | Use orchestrator runner: `python scripts/run_orchestrator_loop.py --config ... --interval 30 --cycles 5` | Removed; fully replaced. |
| (REMOVED) `scripts/terminal_dashboard.py` | `scripts/summary_view.py` | 2025-09-30 | REMOVED 2025-10-01 | Use summary view: `python scripts/summary_view.py --refresh 1` | Removed; unified summary preferred. |
| (REMOVED) `scripts/summary_view.py` | `scripts/summary/app.py` (unified) | 2025-10-01 | REMOVED 2025-10-03 | Use unified summary application: `python -m scripts.summary.app --refresh 1`; legacy plain fallback consolidated (StatusCache + plain_fallback now in app). | File deleted; launcher scripts updated (g6, dev_tools, launch_platform). |
| (REMOVED) `--no-unified` flag & summary legacy fallback (StatusCache/plain_fallback) | Always-on unified loop + PlainRenderer for --no-rich | 2025-10-03 (post consolidation) | REMOVED 2025-10-03 | Remove flag usage; call `python -m scripts.summary.app` directly. Non-rich mode auto-selects PlainRenderer; failures return exit code 1. | Fast-path removal (N+0) justified: zero external test references; parity harness green; improves failure visibility. |
| `start_live_dashboard_v2.ps1` (deprecated launcher) | `scripts/start_live_dashboard.ps1` | 2025-10-01 | R+1 | Use canonical launcher: `powershell -File scripts/start_live_dashboard.ps1` | Shim prints deprecation banner; scheduled removal next release. |
| `scripts/benchmark_cycles.py` (cycle timing script) | `scripts/bench_tools.py` / `profile_unified_cycle.py` | 2025-09-30 (Phase 1 cleanup) | 2025-10-31 | Use bench_tools aggregate/diff/verify or profile_unified_cycle for timing | Stub emits deprecation; removal after 2025-10-31. |
| (REMOVED) `G6_SUMMARY_REWRITE` (enable new summary path) | Always-on unified summary | 2025-10-03 | REMOVED 2025-10-03 | Remove env export; no effect | Path permanently enabled. |
| (REMOVED) `G6_SUMMARY_PLAIN_DIFF` (suppress unchanged plain frames) | Always-on diff suppression (hash reuse) | 2025-10-03 | REMOVED 2025-10-03 | Remove env; behavior default; no opt-out implemented | Stable hashing validated; revisit only if operational issue arises. |
| (REMOVED) `G6_SSE_ENABLED` (enable SSE publisher) | Auto activation when SSE HTTP/panels active | 2025-10-03 | REMOVED 2025-10-03 | Remove env; publisher constructed automatically via unified app when `G6_SSE_HTTP=1` | Env gate eliminated; code path unconditional on instantiation. |
| (REMOVED) `G6_SUMMARY_RESYNC_HTTP` (enable resync HTTP server) | Auto-on with SSE (opt-out via `G6_DISABLE_RESYNC_HTTP=1`) | 2025-10-03 | REMOVED 2025-10-03 | Remove env; use opt-out variable if needed | Simplifies enablement surface. |
| (REMOVED) `scripts/summary_view.py` (legacy summary shim) | `scripts/summary/app.py` unified modular summary | 2025-10-03 | REMOVED 2025-10-03 | Replace panel & derive imports with modular equivalents (`scripts.summary.panels.*`, `scripts.summary.derive`) | Completed early after consolidation; zero external import telemetry. |
| `G6_DISABLE_RESYNC_HTTP` (new) | (Opt-out only) | 2025-10-03 | — | Set `G6_DISABLE_RESYNC_HTTP=1` to suppress resync server when SSE active | Not a deprecation; governance listing for discoverability. |
| `g6_vol_surface_quality_score_legacy` (duplicate gauge) | `g6_vol_surface_quality_score` | 2025-10-02 (metrics modularization cleanup) | R+1 | Dashboards should reference canonical `g6_vol_surface_quality_score`; update panels/alerts. | Duplicate maintained for one release window; removal planned after confirming no external scrapes rely on legacy name. |
| (REMOVED) `src.providers.kite_provider` shim | `src.broker.kite_provider` | 2025-10-01 (warning via docs) | REMOVED 2025-10-07 (A24) | Update imports to broker namespace; shim now raises ImportError | Hard removal part of A24 cleanup. |
| (UPDATED – synthetic removed) Consolidated env flags (`G6_LOOP_HEARTBEAT_INTERVAL`, outage, salvage, recovery, quiet/trace; former synthetic) direct hot-path parsing | `CollectorSettings` hydrated once | 2025-10-06 (post consolidation) | REMOVED synthetic flag 2025-10-08 | Remove synthetic fallback related exports; other flags unchanged | Synthetic fallback flag eliminated; no further action for remaining flags. |
| `src/metrics/cache.py` direct registrations | `src/metrics/cache_metrics.py` (`init_cache_metrics`) | 2025-10-02 | R+1 | Import stays valid; no action unless depending on internal implementation details. | File now a thin shim delegating to new module (no behavior change). |
| (REMOVED) Cycle tables output (Prefilter / Option Match) | Structured events only | 2025-10-07 | REMOVED 2025-10-07 | Remove table-related env vars; rely on STRUCT lines & metrics | Human tables deleted; stub module retained temporarily. |
| G6_DISABLE_CYCLE_TABLES (no-op) | (None – removed feature) | 2025-10-07 | 2025-11 (final removal) | Remove from environments; has no effect | Marked deprecated; scheduled purge after one release if unset in telemetry. |
| G6_DEFER_CYCLE_TABLES (no-op) | (None) | 2025-10-07 | 2025-11 | Remove env/export | Deferral logic removed. |
| G6_CYCLE_TABLE_GRACE_MS / G6_CYCLE_TABLE_GRACE_MAX_MS (no-op) | (None) | 2025-10-07 | 2025-11 | Remove env/export | Grace delay logic removed. |
| (REMOVED) `scripts/bench_aggregate.py` / `bench_diff.py` / `bench_verify.py` | `scripts/bench_tools.py` | 2025-09-30 (Phase 2) | REMOVED 2025-10-05 | Use unified subcommands (aggregate, diff, verify) | Early removal (no direct test imports; consolidation complete). |
| `--enhanced` flag (run_orchestrator_loop) | Unified collectors default | 2025-09-30 (Phase 2) | R+0 (removed) | Remove flag usage; no action required | CLI arg removed; tests adjusted if any. |
| (REMOVED) `G6_SUMMARY_PANELS_MODE` (env toggle) | Auto-detect panels presence | 2025-09-30 (Phase 3) | REMOVED 2025-10-02 | Remove env; summarizer ignores it (auto-detect only) | Purged from code & docs; no runtime warning path remains. |
| (REMOVED) `G6_SUMMARY_READ_PANELS` (legacy alias) | Auto-detect panels presence | 2025-09-30 (Phase 3) | REMOVED 2025-10-02 | Remove env; summarizer ignores alias | Purged from code & docs. |
| `perf_cache` metrics group alias | `cache` metrics group | 2025-10-02 (post modularization) | R+1 | Switch dashboards / alerts to `cache` group naming if referencing alias | Alias internally mapped; removal after one release if no external dependency signals. |
| (REMOVED) `scripts/quick_import_test.py` | `scripts/dev_smoke.py import-check` | 2025-09-30 (Phase 3) | REMOVED 2025-10-05 | Invoke consolidated multi-tool | Wrapper deleted after grace decision (early removal). |
| (REMOVED) `scripts/quick_provider_check.py` | `scripts/dev_smoke.py provider-check` | 2025-09-30 (Phase 3) | REMOVED 2025-10-05 | Use dev_smoke subcommand | Wrapper deleted after grace decision (early removal). |
| (REMOVED) `scripts/quick_cycle.py` | `scripts/dev_smoke.py one-cycle` | 2025-09-30 (Phase 3) | REMOVED 2025-10-05 | Use dev_smoke one-cycle | Wrapper deleted after grace decision (early removal). |
| (REMOVED) `scripts/status_to_panels.py` (legacy panels bridge) | Unified loop `PanelsWriter` + `StreamGaterPlugin` | 2025-10-05 (Phase 1 stream gater) | REMOVED 2025-10-05 (Phase 3 accelerated) | Use unified summary: `python -m scripts.summary.app --refresh 1` | Tombstone stub exits(2); opt-out flag cleanup pending (Phase 4). |
| Legacy unified snapshot adapter (`from_legacy_unified_snapshot`) | Native `assemble_model_snapshot` | 2025-09-30 (native builder intro) | REMOVED 2025-10-01 | Remove any internal reliance; always call `assemble_model_snapshot` | Adapter & fallback path deleted; failures now return minimal snapshot with `native_fail` warning. |
| `assemble_unified_snapshot` (legacy assembler) | `assemble_model_snapshot` | 2025-10-01 (post adapter removal) | REMOVED 2025-10-01 | Use `assemble_model_snapshot`; file & tests deleted | Final removal completed (no runtime fallback). |
| Legacy snapshot internal fields (`panels_generation`, `rolling`) | N/A (removed) | 2025-10-01 | REMOVED 2025-10-01 | No action required; fields were never part of stable surface. | Pruned from `UnifiedSnapshot` dataclass to reduce surface area before full removal. |
| `G6_SUMMARY_UNIFIED_SNAPSHOT` (env gate) | (None) | 2025-10-01 | REMOVED 2025-10-01 | Remove from environments; unified model always active. Use `G6_UNIFIED_MODEL_INIT_DEBUG` for optional startup debug payload. | Gate redundant after full model adoption. |
* Parity harness & hash helpers: REMOVED (Phase 2).
	- Removed modules/tests: `src/collectors/parity_harness.py`, orchestrator parity harness tests.
	- Facade parity mode now only performs a dual run and compares index counts (hash logic eliminated).
	- Environment flag `G6_FACADE_PARITY_STRICT` enforces index count parity only.
	- Rationale: structural drift is expected post-pipeline promotion; execution success + targeted
		shape/field checks provide higher signal-to-noise.

## Environment Flag Deprecations

### Unified Suppression Environment Variable
`G6_SUPPRESS_DEPRECATIONS` now honored by all stubs and wrappers. Legacy per-script suppressors (`G6_SUPPRESS_DEPRECATED_RUN_LIVE`, `G6_SUPPRESS_BENCHMARK_DEPRECATED`) still accepted for one grace release; plan removal of legacy keys in next cleanup wave.

### Cycle Table Flag Set (Deprecated 2025-10-07)
The following flags are now no-ops; underlying table system removed. They will be fully purged after one release window if no external dependency reports emerge:

| Flag | Status | Replacement | Action |
|------|--------|-------------|--------|
| G6_DISABLE_CYCLE_TABLES | deprecated (no-op) | Structured events only | Remove from env configs |
| G6_DEFER_CYCLE_TABLES | deprecated (no-op) | Structured events only | Remove from env configs |
| G6_CYCLE_TABLE_GRACE_MS | deprecated (no-op) | N/A | Remove lines; no timing impact |
| G6_CYCLE_TABLE_GRACE_MAX_MS | deprecated (no-op) | N/A | Remove lines; no timing impact |

## Removal Preconditions

### Suppression & Panels Env Removal Timeline

| Deprecated Env Var | Replacement | First Warn | Grace Window | Removal Target* | Planned Action |
|--------------------|-------------|------------|--------------|-----------------|----------------|
| (REMOVED) `G6_SUPPRESS_DEPRECATED_RUN_LIVE` | `G6_SUPPRESS_DEPRECATIONS` | 2025-09-26 | REMOVED 2025-10-01 | Use unified suppression only | Code & docs purged. |
| (REMOVED) `G6_SUPPRESS_BENCHMARK_DEPRECATED` | `G6_SUPPRESS_DEPRECATIONS` | 2025-09-30 | REMOVED 2025-10-01 | Use unified suppression only | Code & docs purged. |
| (REMOVED) `G6_SUMMARY_PANELS_MODE` | Auto-detect (no env) | 2025-09-30 | Completed | 2025-10 | Removed (2025-10-02) – env references & warnings eliminated. |
| (REMOVED) `G6_SUMMARY_READ_PANELS` | Auto-detect (no env) | 2025-09-30 | Completed | 2025-10 | Removed (2025-10-02) – env references & warnings eliminated. |
| `perf_cache` group alias | Use `cache` group | 2025-10-02 | 1 release (R+1) | 2025-11 | Planned removal if no usage telemetry flags dependency. |

*Removal Target assumes no blocking feedback; any discovered external dependency extends window by one release.

Post-removal checklist (apply per batch PR):
1. Grep repository for env name (case-sensitive) to confirm zero references.
2. Remove from `docs/env_dict.md`, `.env.example`, any script banners, and PowerShell / BAT launchers.
3. Update `README.md` and `MIGRATION.md` removing migration guidance (or move to historical section if policy requires).
4. Adjust tests: drop monkeypatch/setenv lines; ensure no warnings expected.
5. Add CHANGELOG entry summarizing removal and pointing to auto-detect / unified suppression.

Rollback plan: If removal causes unexpected operational regression, re-introduce a shim reading the env (no warning) for one hotfix release, paired with an advisory note.

*Earliest Removal is contingent on: (a) parity harness stability, (b) no undiscovered semantic gaps, (c) updated operational run-books.

## Monitoring & Acceptance Criteria
- Parity harness (`tests/test_orchestrator_parity.py`) remains green across releases.
- No net-new metrics emitted only by legacy loop in last two releases.
- Operators confirm migration of automation scripts (if any) away from direct `collection_loop`.

### Removed Scripts (2025-10-01)
Deleted after successful migration and doc convergence:
* scripts/run_live.py
* scripts/terminal_dashboard.py
* scripts/panel_updater.py
* (2025-10-02) src/archived/main.py (legacy entrypoint stub)
* (2025-10-02) src/archived/main_advanced.py (legacy advanced entrypoint stub)

### Documentation Consolidation (2025-10-01)
Multiple historical README variants (`README_COMPREHENSIVE.md`, `README_web_dashboard.md`, `README_CONSOLIDATED_DRAFT.md`) were archived and merged into the canonical `README.md`. (Removed 2025-10-03) – delete completed; update any external references accordingly.

All automation must point to `scripts/run_orchestrator_loop.py` and summary consumers to `scripts/summary/app.py` (legacy `summary_view.py` removed).

### Deprecation Warning Consolidation (2025-10-02)
Central emission now handled by `src.utils.deprecations.emit_deprecation` with:
* One-time default emission keyed by logical id.
* Global suppression via `G6_SUPPRESS_DEPRECATIONS` (unchanged policy).
* Verbose repeat mode via `G6_VERBOSE_DEPRECATIONS`.
* Force + critical flags for facade echo (pipeline promotion) to guarantee visibility even under suppression.
 * Migrated sites (phase 1): metrics direct import shim, init_helpers.apply_group_gating, parity_harness.snapshot_hash,
	 (REMOVED) synthetic.generate_synthetic_quotes wrapper (stub now inert), KiteProvider constructor & deprecation property shims.
Future cleanups may migrate remaining ad-hoc deprecation warnings to this helper.

## Planned Candidates (Not Yet Deprecated)
| Candidate | Precondition Before Deprecation | Rationale |
|-----------|---------------------------------|-----------|
| `G6_EXPIRY_MISCLASS_SKIP` (alias) | Full adoption of policy flag `G6_EXPIRY_MISCLASS_POLICY` | Reduce redundant flag surface |
| `G6_PARALLEL_COLLECTION` (alias of G6_PARALLEL_INDICES) | Remove all code references & update docs | Consolidate parallelism flags |

## Policy Exceptions
Any acceleration (removal sooner than N+2) requires:
- Explicit sign-off in PR description
- CI label `fast-deprecation`
- Justification (security, correctness, critical performance gain)

## Adding a New Deprecation
1. Implement replacement & ensure feature parity tests.
2. Add one-time warning guard (pattern used in `unified_main.collection_loop`).
3. Append table row under Active Deprecations.
4. Update docs referencing old path (mark as deprecated).
5. Link PR in Change Log (future_enhancements.md) if strategic.

---
For questions, open a discussion or tag maintainers in the PR.

---

### Legacy Panels Bridge (Tombstone & Flag Retirement)

Phase 3 (2025-10-05): `scripts/status_to_panels.py` replaced with a tombstone stub (exit code 2) printing migration guidance unless `G6_SUPPRESS_LEGACY_CLI=1`.

Phase 4 (2025-10-05): Completed retirement of both gating flags. All conditional logic referencing:
* `G6_UNIFIED_STREAM_GATER` (legacy opt-in)
* `G6_DISABLE_UNIFIED_GATER` (temporary opt-out)

has been removed from the runtime path. The `StreamGaterPlugin` is now unconditional. Setting either env var only triggers a one-time warning (test enforced) and has no behavioral effect.

Current Rollout Timeline (updated):
* Phase 1: StreamGaterPlugin opt-in (DONE)
* Phase 2: Default-on with opt-out `G6_DISABLE_UNIFIED_GATER` (DONE)
* Phase 3: Remove legacy bridge script (DONE – accelerated)
* Phase 4: Retire opt-in & opt-out flag handling (DONE)
* Phase 5: (Planned) Remove residual warning + metric name normalization shim once external configs stop setting retired flags (target 2025-10-20, contingent on zero warning occurrences in ops logs for 5 consecutive business days)

Operational Notes:
* Conflict protection metric `g6_stream_conflict_total` remained 0 through observation; no dual-writer detected.
* Tests added to assert single warning emission when retired flags are present.
* Documentation now treats gating as a permanent capability; flags should not appear in examples or templates.

Next Steps Prior to Phase 5:
1. Monitor logs (CI + prod) for any residual retired flag warning occurrences.
2. If no occurrences for 5 business days, schedule removal of warning branch and normalization shim.
3. Regenerate metrics catalog after shim removal to confirm no name drift.

Rollback Strategy: Extremely low risk; should re-introduction be required, prefer feature-toggling via a scoped debug env (new name) rather than reviving legacy flags.

Follow-Up (Phase 5 Checklist Draft):
* Delete warning emission block in `stream_gater.py`.
* Remove metric name normalization shim logic tied specifically to legacy counter adoption (if still present).
* Re-run `scripts/gen_env_docs.py` and metrics catalog generation to ensure no orphaned references.
* Add a short note to CHANGELOG summarizing finalization of gating subsystem.

### KiteProvider Direct Construction Deprecation (Warning Suppression Strategy)

Status: Active (Phase 10 hardening).

Background: Direct instantiation of `KiteProvider` emits a `DeprecationWarning` to steer
users and internal tests away from poking internal attributes and to prefer the
structured `provider_diagnostics()` call. This keeps the surface area tight while
still allowing existing flows to operate.

Test Strategy: A pytest fixture `kite_provider` (in `tests/conftest.py`) now constructs
the provider inside a warnings suppression context so the majority of tests do not
spam global output. A focused test (`test_kite_provider_diagnostics.py`) still asserts
that the deprecation warning is emitted for direct construction and for first-time
access of each deprecated property shim.

Rationale: Reduces recurring noise in 500+ test runs while preserving a guardrail
that the deprecation path still produces a warning until full removal.

Migration Guidance: Code transitioning off deprecated property shims should switch
to `provider_diagnostics()` and reference stable keys (documented inline). Future
removal will delete the property shims and the construction warning once downstream
usage metrics indicate negligible reliance.

Planned Follow-up:
1. Optional env flag `G6_SUPPRESS_KITE_DEPRECATIONS` mirroring global suppression style.
2. Removal window definition after two releases with fixture adoption and no external
	feedback requiring direct state access.

Owner: Broker/Provider maintainers.
Tracking: Add removal checklist issue referencing this section before starting Phase C.

### Summary Flag Retirement Roadmap (2025-10-03)

The following summary-related environment flags now emit one-time deprecation warnings via `SummaryConfig.load()` using the centralized `emit_deprecation` helper:

| Flag | Current Behavior | Planned Change | Replacement / Post-Removal Behavior | Earliest Removal |
|------|------------------|----------------|--------------------------------------|------------------|
| `G6_SUMMARY_REWRITE` | Toggles new summary path (if set) | Ignored (path always on) | Remove flag entirely; unified path unconditional | R+1 |
| `G6_SUMMARY_PLAIN_DIFF` | Disables diff suppression when set to 0 | Flag removed; suppression always on | Optional future opt-out only if regression emerges | R+2 |
| `G6_SSE_ENABLED` | Enables SSE publisher plugin | Auto-enable when `G6_SSE_HTTP=1` (or panels ingest URL set) | No flag; capability / config driven | R+2 |
| `G6_SUMMARY_RESYNC_HTTP` | Enables resync HTTP endpoint | Endpoint always on with SSE unless disabled | Introduce `G6_DISABLE_RESYNC_HTTP=1` (opt-out) | R+2 |

Rationales:
* Reduce cognitive load and environment surface area; defaults now safe & production-ready.
* Observability (metrics + tests) indicates stable operation without manual gating.
* Aligns with governance policy: once replacement path is battle-tested (>=2 phases) gating flag enters removal window.

Operational Notes:
* CI / tests relying on explicit enabling should remove setenv lines; warnings guarantee early visibility during transition.
* A global suppression env `G6_SUPPRESS_DEPRECATIONS=1` silences the warnings (unchanged policy).
* After removal, exporting the retired flag becomes a no-op (no warning) for one release before being fully purged from docs.

Migration Checklist (apply before each flag deletion PR):
1. Grep repository for the flag name (code + docs + scripts/launchers).
2. Confirm no tests still set the flag (except deprecation coverage tests).
3. Update this section marking the flag as REMOVED with date.
4. Add CHANGELOG entry summarizing removal & replacement behavior.
5. Validate metrics / integration tests pass with environment unset.

Rollback Plan:
If unexpected operational regressions occur post-removal, reintroduce a shim in `SummaryConfig` reading the env but producing a warning (fast-follow hotfix). Metrics will track resumed usage to refine guidance.

### Panels Schema Transitional Field Duplication Removal (indices/system panel)

Status: Removed (compatibility shim deleted) – 2025-10-01.

Background: During the initial introduction of the wrapped panels schema (`{"panel": ..., "updated_at": ..., "data": {...}}`) a temporary backward compatibility layer duplicated selected fields from two panels at the top-level of each panel JSON file:

* `indices_panel.json`: `items`, `count`
* `system_panel.json`: `memory_rss_mb`, `cycle`, `interval`, `last_duration`

Rationale: This short-lived duplication allowed existing exploratory scripts / legacy tests that still expected flat keys to pass while the canonical wrapper (`data`) structure propagated through the codebase and tests were updated.

Change: The duplication block in `PanelsWriter` (emission loop) was removed. All consumers must now access these values exclusively via the nested `data` object (e.g., `indices_panel["data"]["items"]`, `system_panel["data"]["memory_rss_mb"]`). No top-level fallbacks remain.

Migration Guidance:
1. Replace any direct lookups like `panel_json["items"]` with `panel_json["data"]["items"]` (similarly for the other system metrics fields).
2. If performing generic iteration, prefer `payload = panel_json.get("data", {})` and operate solely within that namespace to future-proof against additional metadata keys at the top level.
3. Remove any conditional logic attempting both flat and nested access patterns.

Detection / Validation Tips:
* A quick repository / script audit command (example) previously: grep -R "indices_panel.*\"items\""; now ensure no usages bypass `data`.
* Tests updated: `tests/test_unified_summary_parity_stub.py` asserts nested keys only.

Versioning / Risk:
* Considered low risk; duplication never documented as stable and existed only for an internal transition window.
* No environment flag gated this removal; wrapper mode already the default and required.

Rollback Plan: Re-introduction would entail restoring a small block in `PanelsWriter` that promotes selected `data` keys to the top-level for specified panels. Currently no external dependency justifies this.

Owner: Summary/Unification maintainers.
Tracking: Covered under Panels schema cleanup task (Phase post-bridge removal).

## Newly Registered (Pending Removal) – `G6_PIPELINE_COLLECTOR`

Historical purpose: Pre-promotion opt-in to pipeline collectors.

Current behavior: No longer changes execution path (pipeline is default). Presence now triggers a one-time `DeprecationWarning` and log warning.

Migration Guidance:
	* Remove `G6_PIPELINE_COLLECTOR` from all environments / scripts.
	* To force legacy temporarily use `G6_LEGACY_COLLECTOR=1`.
	* Rollout controller `G6_PIPELINE_ROLLOUT` removed (2025-10-01 Stage 2). Use orchestrator facade modes (`mode=legacy|pipeline`) and `parity_check=True` for parity diagnostics.

Timeline:
	* First warning release: 2025-09-30
	* Target removal of warning & flag parsing: Q4 2025 (after two green releases)

After Removal: Flag ignored silently (and rollout flag removed). Shadow diff path deleted from `unified_collectors`.

Implementation Reference: `src/utils/deprecations.check_pipeline_flag_deprecation`.

