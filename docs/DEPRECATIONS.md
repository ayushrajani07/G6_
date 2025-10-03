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

## 3. Removal Preconditions (Examples)
Before deleting a deprecated component, all of the following must be satisfied:
1. Parity harness (if orchestration-related) shows no divergence for two consecutive green runs.
2. CI / automation / docs references updated (grep for component name returns no active usage outside this file).
3. Env doc coverage test passes without needing the deprecated flag (or flag moved to historical section here first).
4. Release notes drafted with clear upgrade guidance.

## 4. Historical (Removed) Items
| `unified_main.collection_loop` | Removed (2025-09-28) | `src.orchestrator.loop.run_loop` | N/A | Use orchestrator runner (`scripts/run_orchestrator_loop.py`). Flags `G6_ENABLE_LEGACY_LOOP`, `G6_SUPPRESS_LEGACY_LOOP_WARN` obsolete. |

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

---
_Last updated: 2025-09-27_