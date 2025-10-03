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
| `start_live_dashboard_v2.ps1` (deprecated launcher) | `scripts/start_live_dashboard.ps1` | 2025-10-01 | R+1 | Use canonical launcher: `powershell -File scripts/start_live_dashboard.ps1` | Shim prints deprecation banner; scheduled removal next release. |
| `scripts/benchmark_cycles.py` (cycle timing script) | Internal profiling / test harness | 2025-09-30 (Phase 1 cleanup) | R+1 | Use pytest benchmarks or profiling docs | Stub preserves `run_benchmark` for tests. |
| `g6_vol_surface_quality_score_legacy` (duplicate gauge) | `g6_vol_surface_quality_score` | 2025-10-02 (metrics modularization cleanup) | R+1 | Dashboards should reference canonical `g6_vol_surface_quality_score`; update panels/alerts. | Duplicate maintained for one release window; removal planned after confirming no external scrapes rely on legacy name. |
| `src/metrics/cache.py` direct registrations | `src/metrics/cache_metrics.py` (`init_cache_metrics`) | 2025-10-02 | R+1 | Import stays valid; no action unless depending on internal implementation details. | File now a thin shim delegating to new module (no behavior change). |
| `scripts/bench_aggregate.py` / `bench_diff.py` / `bench_verify.py` | `scripts/bench_tools.py` | 2025-09-30 (Phase 2) | R+1 | Use unified subcommands (aggregate, diff, verify) | Wrappers emit deprecation warning unless suppressed. |
| `--enhanced` flag (run_orchestrator_loop) | Unified collectors default | 2025-09-30 (Phase 2) | R+0 (removed) | Remove flag usage; no action required | CLI arg removed; tests adjusted if any. |
| (REMOVED) `G6_SUMMARY_PANELS_MODE` (env toggle) | Auto-detect panels presence | 2025-09-30 (Phase 3) | REMOVED 2025-10-02 | Remove env; summarizer ignores it (auto-detect only) | Purged from code & docs; no runtime warning path remains. |
| (REMOVED) `G6_SUMMARY_READ_PANELS` (legacy alias) | Auto-detect panels presence | 2025-09-30 (Phase 3) | REMOVED 2025-10-02 | Remove env; summarizer ignores alias | Purged from code & docs. |
| `perf_cache` metrics group alias | `cache` metrics group | 2025-10-02 (post modularization) | R+1 | Switch dashboards / alerts to `cache` group naming if referencing alias | Alias internally mapped; removal after one release if no external dependency signals. |
| `scripts/quick_import_test.py` | `scripts/dev_smoke.py import-check` | 2025-09-30 (Phase 3) | R+1 | Invoke consolidated multi-tool | Wrapper delegates & warns unless suppressed. |
| `scripts/quick_provider_check.py` | `scripts/dev_smoke.py provider-check` | 2025-09-30 (Phase 3) | R+1 | Use dev_smoke subcommand | Wrapper delegates & warns unless suppressed. |
| `scripts/quick_cycle.py` | `scripts/dev_smoke.py one-cycle` | 2025-09-30 (Phase 3) | R+1 | Use dev_smoke one-cycle | Wrapper delegates & warns unless suppressed. |
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

All automation must point to `scripts/run_orchestrator_loop.py` and summary consumers to `scripts/summary_view.py` or `scripts/summary/app.py`.

### Deprecation Warning Consolidation (2025-10-02)
Central emission now handled by `src.utils.deprecations.emit_deprecation` with:
* One-time default emission keyed by logical id.
* Global suppression via `G6_SUPPRESS_DEPRECATIONS` (unchanged policy).
* Verbose repeat mode via `G6_VERBOSE_DEPRECATIONS`.
* Force + critical flags for facade echo (pipeline promotion) to guarantee visibility even under suppression.
 * Migrated sites (phase 1): metrics direct import shim, init_helpers.apply_group_gating, parity_harness.snapshot_hash,
	 synthetic.generate_synthetic_quotes wrapper, KiteProvider constructor & deprecation property shims.
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

### Legacy Panels Bridge Deprecation: `scripts/status_to_panels.py`

Status: Removed (script & detection helpers deleted) – 2025-09-30.

Replacement: Unified summary loop (`scripts/summary/app.py`) with in-process `PanelsWriter` emitting panel JSON artifacts (no external bridge needed).

Why: Eliminates duplicate status file reads, reduces IO churn, avoids partial update race windows, simplifies conflict detection (single process responsible for panel set), and aligns with unified snapshot evolution.

Artifacts Produced by Replacement (`PanelsWriter`):

Gating Behavior: N/A (file removed). Former environment allow override retired (environment flag removed).

Environment Controls (current relevant):

Migration Summary:
All internal scripts & docs updated; unified summary writes panels directly; monitoring leverages `manifest.json`.

Testing & Parity:

Risks / Blockers: None (external callers will receive file-not-found; advise updating to unified path).

Rollback Plan: Restore deleted script from VCS history if an unforeseen consumer surfaces (unlikely).

Owner: Summary/Unification maintainers.

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

