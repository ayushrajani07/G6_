# Legacy Loop Removal Readiness Checklist

Goal: Safely remove `unified_main.collection_loop` (legacy loop) after feature parity and ecosystem readiness are confirmed.

## 1. Functional Parity
- [x] Orchestrator loop provides bounded cycle control (env: `G6_LOOP_MAX_CYCLES` + alias `G6_MAX_CYCLES`).
- [x] Runtime status writing present (timestamp, indices_info, options fields).
- [x] Metrics emission parity (core counters, histograms). *(Spot-check; deep diff optional)*
- [ ] Dashboard / panels integration validated exclusively through orchestrator for N consecutive green runs (target: 2).
- [ ] No remaining non-deprecation tests import or execute `src.unified_main` loop code.

## 2. Test Suite Migration
- [x] Status/options tests migrated (timestamp, indices options field).
- [x] Mock provider single cycle & dashboard smoke migrated.
- [x] Per-index option counts migrated.
- [ ] Any residual CLI invocation tests either converted or explicitly marked as legacy-deprecation coverage.

## 3. Deprecation & Communication
- [x] Gating env introduced: `G6_ENABLE_LEGACY_LOOP` (off by default) – subsequently removed 2025-09-28.
- [x] Deprecations doc lists legacy loop with guidance.
- [ ] Announce removal timeline (add to `DEPRECATIONS.md` with target release version once checklist >= 80% complete).
- [ ] Provide migration snippet in README / upgrade notes (orchestrator usage example).

## 4. Code Hygiene
- [ ] Remove fallback enabling logic (DONE in `conftest.py`).
- [ ] Remove dead imports & helpers tied only to legacy loop after removal window.
- [ ] Ensure no circular references appear after deletion.

## 5. Observability & Safety Nets
- [ ] Add final metric: `g6_legacy_loop_invocations_total` freeze value (optional snapshot before removal).
- [ ] Ensure alert rules (if any) are updated to reference new loop metrics names only.
- [ ] Run two consecutive full test suite passes with LEGACY loop disabled globally (only deprecation tests re-enable).

## 6. Removal Execution Plan
1. Achieve all above unchecked items.
2. Tag release: `vX.Y.0` announcing deprecation final window closure.
3. In following minor release (or same if criteria already met), remove:
   - `collection_loop` implementation.
   - Related CLI flags (`--run-once` etc.) if solely legacy (or map to orchestrator equivalents).
4. Update docs & samples; run doc link checker.
5. Add CHANGELOG entry referencing this checklist.

## 7. Post-Removal Validation
- [ ] Run smoke scripts (`scripts/dev_tools.py summary`, panels bridge) using orchestrator only.
- [ ] Confirm no import errors for `src.unified_main` references (except gracefully raising deprecation if stub retained temporarily).

## Progress Snapshot (at creation time)
- Parity: partial (core tests migrated, panels path pending dedicated orchestrator-only run).
- Migration: majority complete; only deprecation/gating tests exercise legacy path.
- Communication: initial docs present; timeline TBD.

---
Maintainer Action: Update checkboxes as milestones are achieved. When all mandatory (non-optional) boxes are checked, proceed with removal per Plan Section 6.
