# Incremental Typing Rollout Plan (Wave 4 Follow‑On)

This document captures the phased strategy for expanding strict mypy coverage beyond the initial "strict nucleus" now enforced.

## Current Baseline (Phase 0 – COMPLETE)
Strict modules (with `follow_imports=normal`):
- `src/collectors/pipeline_root.py`
- `src/collectors/pipeline/` (package surface; re‑exports)
- `src/parity/*`

Configuration tactics:
- Global `follow_imports=skip` + targeted overrides keeps traversal minimal.
- Legacy / high-noise areas temporarily silenced with `ignore_errors = True` stanzas in `mypy.ini`.
- All strict nucleus modules: 0 mypy errors (baseline snapshot).

## Guiding Principles
1. Peel shields one cluster at a time (small diff surface; fast feedback).
2. Always land each cluster at ZERO mypy errors before moving on.
3. Delete or refine `type: ignore` instead of accumulating dead comments (enforced by `warn_unused_ignores = True`).
4. Prefer narrowing return shapes (Dict[str, X] → dataclass / TypedDict) when it removes cascades of `Any`.
5. Avoid premature typing of large provider/broker surfaces until pipeline + metrics foundations are stable.

## Metrics / Acceptance Criteria
For each phase:
- All modules in the phase: 0 mypy errors.
- No new `ignore_errors` blocks introduced (net decrease only).
- Unused `type: ignore` count = 0 for touched modules.
- Public functions have explicit parameter & return annotations (no implicit `-> Any`).
- No regression in existing tests (`pytest -q`).

Optional quality gates (stretch):
- Remove obviously redundant runtime defensive checks once types guarantee conditions.
- Introduce `TypedDict` / `dataclass` for recurrent dict payloads (expiry metrics, enrichment output).

## Phase Roadmap
| Phase | Target Cluster | Rationale | Est. Size | Key Risks |
|-------|----------------|-----------|-----------|-----------|
| 1 | `src.collectors.pipeline.executor`, `pipeline.phases`, `pipeline.shadow` | Closest to nucleus; high leverage for downstream clarity | Small/Moderate | Hidden dynamic imports |
| 2 | `src.collectors.unified_collectors` | Bridges legacy & pipeline; unlocks parity trust | Moderate | Mixed structural patterns |
| 3 | `src.collectors.modules.*` (process in logical groups: expiry*, index*, memory*) | Decomposes largest shield into themed slices | Large (chunked) | Volume of dict plumbing |
| 4 | Supporting utils (`src.utils.output`, `memory_pressure`, `memory_manager`) | Reduce transitive Any ingress | Small | OS / platform branches |
| 5 | Metrics surface (`src.metrics.*` selective) | High cardinality but stabilizes observability layer | Large | Many `type: ignore` placeholders |
| 6 | Provider adapter & broker kite subset | External boundary typing; improves reliability | Large | External SDK looseness |

## Phase 1 Detailed Playbook
1. Remove `ignore_errors` blocks for:
   - `mypy-src.collectors.pipeline.executor`
   - `mypy-src.collectors.pipeline.phases`
   - `mypy-src.collectors.pipeline.shadow`
2. Run: `mypy src/collectors/pipeline/executor.py src/collectors/pipeline/phases.py src/collectors/pipeline/shadow.py`
3. Triage error classes:
   - `no-untyped-def`: add annotations (prefer concrete over `Any`).
   - `no-any-return`: wrap ambiguous return shapes in `TypedDict` or dataclass.
   - `unused-ignore`: delete the line or add real fix.
4. Introduce lightweight data structures:
   - `ExpiryPhaseResult` dataclass (if recurring tuple/dict patterns) to reduce key typos.
5. Re-run mypy until green.
6. Add a short section to this file logging completion (date + diff of removed shields).

## Data Shape Conventions
| Concept | Suggested Shape | Notes |
|---------|-----------------|-------|
| Enriched Option Quote | `TypedDict` (symbol, ltp, iv?, greeks?, oi?) | Narrow optional fields with `NotRequired` once Python 3.11+ typing is leveraged |
| Persist Outcome | Existing `PersistOutcome` dataclass | Already typed |
| Phase/Executor Aggregation | New dataclass (phase name, success flag, counts) | Avoid dict merging logic |

## De-Shield Checklist (Per Cluster)
- [ ] Remove `ignore_errors` for cluster in `mypy.ini`.
- [ ] Run targeted mypy.
- [ ] Add annotations / dataclasses / TypedDicts.
- [ ] Remove stale `type: ignore` markers.
- [ ] Achieve zero errors.
- [ ] Commit with message: `typing(phaseX): unshield <cluster> (0 errors)`.
- [ ] Update this document (Completion Log).

## Completion Log
### 2025-10-08 – Phase 1 Complete
Cluster: `pipeline.executor`, `pipeline.phases`, `pipeline.shadow`, `pipeline.gating`, `pipeline.error_helpers`

Baseline Errors: 71 (after unshielding)
Final Errors: 0

Highlights:
- Removed all unused `# type: ignore` in cluster.
- Added explicit annotations for phase functions, executor helpers, gating store.
- Repaired accidental syntax regressions in `phases.py` (salvage/iv/greeks blocks).
- Normalized ratio / churn computations with safe numeric coercions.
- Replaced dynamic attr ignores with `cast` for `_rolling_window`.

Next Candidate Cluster: `unified_collectors` (Phase 2) after brief soak.

Verification Commands (executed locally):
- `pytest -q` (pass; only expected skips)
- `mypy` on Phase 1 modules (0 issues)

### 2025-10-08 – Phase 2 Complete
Cluster: `collectors.unified_collectors`, supporting metric wrappers, column store pipeline adaptations

Baseline Errors (after unshielding `unified_collectors.py`): 108
Final Errors: 0

Adjacent Remediations:
- Introduced `TypedDict` structures (`IndexStructEntry`, `ExpiryStructEntry`) to replace sprawling `Dict[str, Any]` payloads.
- Harmonized fallback function signatures (eliminated variant mismatch noise & conditional overload drift).
- Replaced broad `# type: ignore` metrics calls with protocol-driven safe wrappers (`_MetricLabel`, `_safe_label`, `_SupportsMetricOps`).
- Removed redundant casts after shaping intermediate vars; tightened outage / threshold numeric handling.
- Cleaned `src/column_store/pipeline.py` (≈9 unused ignores removed) via `_Dummy` metrics fallback + guarded emission helper.
- Refactored `analytics/vol_surface.py` metrics emission (iteration guard + optional timestamp coercion) removing stale ignores.

Quality / Risk Notes:
- No runtime logic changes beyond defensive wrapper introduction; behavioral parity preserved (verified via existing tests + spot smoke runs).
- Metrics emission now resilient to partial metric object presence (graceful no-op instead of ignore masking).

Verification Commands (executed locally):
- Targeted: `mypy src/collectors/unified_collectors.py` → 0 errors.
- Column store & vol surface spot: `mypy src/column_store/pipeline.py src/analytics/vol_surface.py` → 0 errors.
- `pytest -q` (unchanged pass state).

Follow-On Targets (Phase 3 Preview):
- Orchestrator components (`src/orchestrator/components.py`) – high concentration of unused ignores & dynamic attribute access.
- Orchestrator cycle/state modules – union optional access patterns causing cascading `attr-defined` suppressions.
- Gradual introduction of narrow protocols for adaptive alert feeds to eliminate remaining localized ignores.

Decision Log Addendum:
- Adopt protocol-based metric abstraction pattern as standard for future clusters.
- Prefer minimal local helpers over expanding global typing configuration knobs.

Exit Criteria Met: YES (0 errors, net decrease in ignores, no new shields added).

## Future Enhancements (Post-Rollout)
- Enable `disallow_any_generics = True` once surface Any reduced.
- Consider `--strict-equality` globally (already on nucleus), then project-wide.
- Add pre-commit hook: run nucleus + last unshielded cluster mypy as fast gate.
- Generate type coverage report (e.g., using `mypy --html-report` on CI) for visibility.

---
Maintained as a living artifact. Keep concise; append decisions rather than rewriting history.
