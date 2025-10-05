# G6 Deprecations Registry

Central authoritative list of deprecated components (scripts, modules, environment flags) with migration paths and planned removal timelines. This file is referenced by warnings emitted at runtime (e.g., legacy loop invocation) to give operators a stable source of truth.

Status legend:
- Active: still supported but warning emitted when invoked.
- Pending Removal: will be deleted after stated release horizon.
- Removed: retained here for historical trace (flag removed from env docs/tests once no longer referenced).

Dates use ISO (YYYY-MM-DD). "R+n" refers to n stable release cycles after initial deprecation warning.

## 1. Deprecated Execution Paths
| Component | Replacement | Deprecated Since | Planned Removal | Migration Action | Notes |
|-----------|-------------|------------------|-----------------|------------------|-------|
| `scripts/run_live.py` (smoke runner) | `scripts/run_orchestrator_loop.py` | 2025-09-26 | R+2 (post legacy loop removal) | Update automation / docs to new runner. | Suppress warning: `G6_SUPPRESS_DEPRECATED_RUN_LIVE=1` |
| `scripts/benchmark_cycles.py` legacy unified_main benchmarking semantics | Orchestrator bootstrap + direct `run_cycle` loop (current script implementation) | 2025-09-27 | R+1 | No action if already using current script. Remove any internal wrappers invoking unified_main. | Emits one-time info log; suppress with `G6_SUPPRESS_BENCHMARK_DEPRECATED=1`. |
| `scripts/expiry_matrix.py` legacy provider init fallback | Direct orchestrator `init_providers` path | 2025-09-27 | Removed (2025-09-27) | Ensure environment sets `G6_USE_MOCK_PROVIDER=1` for offline runs; no legacy fallback available. | Historical only; suppression flag `G6_SUPPRESS_EXPIRY_MATRIX_WARN` scheduled for deletion next release. |
| `src/tools/token_manager.py` unified_main launch fallback | Orchestrator runner script (`scripts/run_orchestrator_loop.py`) | 2025-09-27 | R+1 | Invoke orchestrator runner directly; eliminate reliance on unified_main presence. | Fallback path logs deprecation warning; will be excised after one stable release. |

## 2. Environment Flag Deprecations / Aliases
| Flag | Replacement / Rationale | Deprecated Since | Planned Removal | Migration | Notes |
|------|-------------------------|------------------|-----------------|-----------|-------|
| `G6_EXPIRY_MISCLASS_SKIP` | Policy superseded by `G6_EXPIRY_MISCLASS_POLICY=reject` semantics | 2025-09-26 | R+1 | Set `G6_EXPIRY_MISCLASS_POLICY=reject` (or `rewrite`/`quarantine`) | Currently mapped internally; new features target policy flag only. |
| `G6_SUPPRESS_EXPIRY_MATRIX_WARN` | Obsolete after removal of legacy fallback in `scripts/expiry_matrix.py` | 2025-09-27 | Next release | Remove usage; flag will be dropped from env docs once deleted. | Present only to satisfy env var coverage until deletion. |
| `G6_SUPPRESS_DEPRECATED_RUN_LIVE` / `G6_SUPPRESS_BENCHMARK_DEPRECATED` / `G6_SUPPRESS_DEPRECATED_WARNINGS` | Unified suppression via `G6_SUPPRESS_DEPRECATIONS` | 2025-10-05 | R+1 (remove legacy aliases) | Set `G6_SUPPRESS_DEPRECATIONS=1` to silence all non-critical deprecation banners | Automatically mapped at import; emits one-time consolidation warning. |

### 2.1 Summary Flag Retirement (2025-10-03)
The summary subsystem is consolidating multiple rollout flags now that the unified path and SSE streaming have stabilized.
One-time deprecation warnings are emitted at config load for:
* `G6_SUMMARY_REWRITE` – replacement always-on (removal target R+1)
* `G6_SUMMARY_PLAIN_DIFF` – diff suppression default; flag removed (target R+2)
* `G6_SSE_ENABLED` – will auto-enable when `G6_SSE_HTTP=1`; flag removal target R+2
* `G6_SUMMARY_RESYNC_HTTP` – resync endpoint becomes default; opt-out flag `G6_DISABLE_RESYNC_HTTP` will supersede (target R+2)

See root `DEPRECATIONS.md` for full timeline, migration actions, and rollback strategy.

## 3. Removal Preconditions (Examples)
Before deleting a deprecated component, all of the following must be satisfied:
1. Parity harness (if orchestration-related) shows no divergence for two consecutive green runs.
2. CI / automation / docs references updated (grep for component name returns no active usage outside this file).
3. Env doc coverage test passes without needing the deprecated flag (or flag moved to historical section here first).
4. Release notes drafted with clear upgrade guidance.

## 4. Historical (Removed) Items
| `unified_main.collection_loop` | Removed (2025-09-28) | `src.orchestrator.loop.run_loop` | N/A | Use orchestrator runner (`scripts/run_orchestrator_loop.py`). Flags `G6_ENABLE_LEGACY_LOOP`, `G6_SUPPRESS_LEGACY_LOOP_WARN` obsolete. |
| `scripts/summary_view.py` | Removed (2025-10-03) | `scripts/summary/app.py` | N/A | Use unified summary (`python -m scripts.summary.app`). Skipped legacy tests retained as placeholders to assert removal milestone. |

## 5. Guidance for Introducing New Deprecations
When marking a new feature as deprecated:
1. Emit a single warning on first use (guard with module-level sentinel).
2. Add an env var to suppress if noise could impact tests (pattern: `G6_SUPPRESS_<NAME>_WARN`).
3. Update this registry with replacement, timeline, and migration action.
4. Add/update tests verifying warning emission and suppression.

## 6. Next Actions
- Monitor usage of `run_live.py`; schedule deletion once orchestrator runner adoption confirmed.
- Announce planned alias sunset for `G6_EXPIRY_MISCLASS_SKIP` in release notes ahead of R+1.

### Metrics
Runtime usage of deprecated components is tracked via `g6_deprecated_usage_total{component}` allowing release engineering to gate removals based on observed production reliance.

## 7. Consolidated Deprecation Schedule (Roadmap View)

| Item | Type | Status | Deprecated Since | Planned Removal | Replacement / Outcome | Notes |
|------|------|--------|------------------|-----------------|-----------------------|-------|
| run_live.py | Script | Removed | 2025-09-26 | 2025-10-01 (executed) | run_orchestrator_loop.py | Fully deleted; row retained historical. |
| benchmark_cycles.py (legacy semantics) | Script | Active (Stub) | 2025-09-27 | 2025-10-31 | bench_tools.py subcommands | Emits banner; suppress via unified suppression. |
| bench_aggregate/diff/verify | Scripts | Removed | 2025-09-30 | 2025-10-05 (executed) | bench_tools.py | Hard deleted; inventory synced. |
| perf_cache metric alias | Metrics Group | Removed | 2025-10-02 | 2025-10-05 (executed) | cache group | Guard warns if legacy name used in env filters. |
| --enhanced flag | CLI Flag | Removed | 2025-09-30 | 2025-10-05 (executed) | (none needed) | Docs scrubbed; tests updated. |
| Legacy suppression envs (per-script) | Env Vars | Active (grace) | 2025-10-05 | R+1 | G6_SUPPRESS_DEPRECATIONS | Auto-mapped at import; warning once. |
| G6_EXPIRY_MISCLASS_SKIP | Env Var | Active | 2025-09-26 | R+1 | G6_EXPIRY_MISCLASS_POLICY | Policy flag covers replacement behaviors. |
| G6_SUPPRESS_EXPIRY_MATRIX_WARN | Env Var | Pending Removal | 2025-09-27 | Next release | (none) | Obsolete after fallback deletion. |
| summary flag set (REWRITE/PLAIN_DIFF/etc.) | Env Vars | Active (rolling) | 2025-10-03 | Staggered (R+1..R+2) | defaults / inverse flags | See section 2.1 for per-flag notes. |
| summary_view.py | Module | Removed | 2025-10-01 | 2025-10-03 (executed) | scripts.summary.app | Shim period ended; tests green. |
| unified_main loop | Module Path | Removed | 2025-09-26 | 2025-09-28 (executed) | orchestrator loop | Parity harness validated. |

_Last updated: 2025-10-05_