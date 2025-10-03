# Legacy Import Audit (unified_main / collection_loop)

_Last updated: 2025-09-27_

Purpose: Identify and classify all remaining references to the legacy `unified_main` module and its `collection_loop` so we can (1) verify that only sanctioned transitional or test references remain, and (2) define a concrete remediation plan toward full removal.

## Classification Legend
| Class | Meaning | Removal Strategy |
|-------|---------|------------------|
| core | The legacy module itself (authoritative source until removal) | Delete at final removal milestone |
| orchestrator_bridge | Transitional orchestrator code pulling small pieces (e.g., loader) to avoid duplication | Replace with refactored native implementation before removal (convert to `config.loader`) |
| parity | Explicitly used for parity / deprecation tests or harnesses | Retain until two green stability windows, then delete along with legacy loop |
| deprecated_script | User-facing script still invoking legacy path | Migrate to orchestrator entry; add hard warning now, remove import later |
| util_transitional | Utility importing legacy just for version / bootstrap convenience | Refactor to dedicated version module or orchestrator bootstrap API |
| docstring_ref | Reference inside comments/docstrings only (non-executable) | Optional cleanup (low priority) |

## Inventory

| File | Line(s) | Snippet (trimmed) | Class | Severity | Action |
|------|---------|------------------|-------|----------|--------|
| `src/unified_main.py` | n/a | legacy loop implementation | core | info | Schedule deletion end of R+1 |
| `src/orchestrator/bootstrap.py` | (removed) | (migrated to `from src.config.loader import load_config`) | orchestrator_bridge | done | M1 complete: canonical loader in place |
| `src/orchestrator/parity_harness.py` | 47 | `from src.unified_main import run_collection_cycle` | parity | info | Keep until legacy removal gate passes |
| `tests/test_orchestrator_parity.py` | (indirect) | legacy parity harness usage | parity | info | Keep (guard) |
| `tests/test_panel_status_parity.py` | 32 | dynamic import `src.unified_main` | parity | info | Keep until removal (then switch to archived fixture) |
| `tests/test_deprecation_legacy_loop.py` | 16,39,56 | import module for warning tests | parity | info | Remove with legacy loop |
| `tests/test_deprecation_warnings.py` | 12-15 | explicit import cycle | parity | info | Remove with legacy loop |
| `tests/test_deprecations_registry_format.py` | 13,24 | asserts row text | parity | info | Update assertions post-removal |
| `tests/test_legacy_loop_gating.py` | 13,22 | gating behavior | parity | info | Remove after loop removed |
| `tests/test_status_timestamp_tz.py` | 10 | subprocess `-m src.unified_main` | parity | info | Migrate to orchestrator runner variant |
| `scripts/run_live.py` | 9+ | deprecated launcher docstring | deprecated_script | warn | Replace uses with `scripts/run_orchestrator_loop.py`; set exit warning after grace period |
| `scripts/benchmark_cycles.py` | (migrated) | now uses orchestrator bootstrap + run_cycle | deprecated_script | done | M2 migrated to orchestrator path (no unified_main import) |
| `scripts/expiry_matrix.py` | (migrated) | orchestrator components init_providers only | deprecated_script | done | Fully migrated (legacy fallback removed) |
| `src/utils/build_info.py` | (updated) | now imports `src.version` | util_transitional | done | Uses central version module |
| `src/tools/token_manager.py` | 209-224 | orchestrator script preferred; legacy fallback | util_transitional | warn | Remove legacy fallback after R+1 (row updates when fallback deleted) |
| `src/orchestrator/*` (cycle/status_writer/components/docstrings) | various | purely descriptive mentions | docstring_ref | low | Optional cleanup after removal |
| `scripts/start_mock_mode.ps1` | 18 | warning message only | docstring_ref | low | Adjust message post-removal |
| Archived: `src/archived/main.py`, `src/archived/main_advanced.py` | docstrings | deprecation notice | docstring_ref | low | May delete once changelog covers history |

## Summary Counts
- Total executable legacy imports (non-docstring): 9
  - Parity/Test: 6
  - Orchestrator bridge: 1
  - Deprecated scripts: 3 (benchmark counts as 1)  
  - Utility transitional: 2
- Non-executable (doc/comment) references: ~10 (low priority)

## Remediation Plan & Milestones
| Milestone | Target | Actions |
|-----------|--------|---------|
| M1: Bootstrap Refactor | COMPLETE (2025-09-27) | Extracted canonical `load_config` (ConfigWrapper) to `src/config/loader.py`; updated `bootstrap.py` & `scripts/expiry_matrix.py`; added deprecation shim in `unified_main.load_config`. |
| M2: Script Migration | IN-PROGRESS (2025-09-27) | `benchmark_cycles.py` migrated; `expiry_matrix.py` partially migrated (provider init fallback retained with warning) |
| M3: Utility Decoupling | +7 days | Introduce `src/version.py`; update `build_info.py` & remove unified_main import; update `token_manager` to call orchestrator runner (`scripts/run_orchestrator_loop.py`) |
| M4: Test Realignment | After 2 stable windows | Replace parity tests referencing unified_main with archived fixture or skip markers; remove gating tests tied exclusively to legacy loop |
| M5: Legacy Removal | End R+1 | Delete `unified_main.py`, update docs (`DEPRECATIONS.md`, change log), prune docstring refs |

## Exit Criteria (Audit Clean)
1. Running audit script yields zero `deprecated_script` or `util_transitional` classifications.
2. Only remaining references (before final removal) are parity tests slated for deletion.
3. CI guard blocks new imports of `src.unified_main` outside whitelisted parity test list.

## Next Steps (Implemented in Repository)
- Add `scripts/legacy_import_audit.py` (see below) to enable CI guard.
- Integrate into CI pipeline: run with `--fail-on warn` once remediation of current warn items completed.

---
Generated as part of orchestrator convergence sub-phase.
