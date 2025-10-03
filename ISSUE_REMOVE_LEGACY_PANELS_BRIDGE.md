# Removal Plan: Legacy Panels Bridge (historical `scripts/status_to_panels.py`)

Status: Completed (bridge removed early)
Date: 2025-09-30
Owner: TBD (assign to platform maintainer)

## Background
The legacy panels bridge script (`scripts/status_to_panels.py`) converted `runtime_status.json` to per-panel JSON artifacts. The unified summary loop now produces these artifacts directly through `PanelsWriter`, making the out‑of‑process bridge redundant.

Legacy bridge stub replaced then fully deleted; docs & launch tooling now point exclusively to unified summary path.

## Objectives
1. Eliminate dead code & reduce cognitive overhead.
2. Prevent drift between two generation paths.
3. Simplify onboarding: a single documented mechanism for panels artifacts.

## Scope of Removal
- Delete the legacy bridge script.
- Delete `scripts/summary/bridge_detection.py` (no longer needed for conflict detection once bridge gone).
- Remove associated deprecation test (`test_panels_bridge_deprecation.py`).
- Scrub residual references in docs (`DEPRECATIONS.md`, `README.md`, any design notes).
- Remove environment allow override (legacy panels bridge) and any deprecation suppression branch specific to the bridge.

## Out of Scope
- Further manifest schema evolution (tracked separately).
- Enhancing PanelsWriter performance (future optimization task).

## Execution Timeline
Removed on 2025-09-30 (accelerated; earlier than planned T0+7d).

## Preconditions Checklist (all satisfied)
- [x] No CI jobs invoke `scripts/status_to_panels.py`.
- [x] Docs no longer instruct its usage.
- [x] Manifest schema (`schema_version`) adopted & tested.
- [x] Parity test passes.

## Removal Steps (completed)
1. Deleted files.
2. Deleted deprecation test.
3. Updated `DEPRECATIONS.md` (marked removed).
4. Purged env override references.
5. Tests green.
6. (Pending) CHANGELOG entry.

## Rollback Plan
Restore last stub from VCS if an external dependency surfaces (low risk).

## Communication
- Announce in release notes for version covering 2025-10-07.
- Notify any dashboards or downstream processors (none known relying on bridge-specific timing semantics).

## Open Questions
- Do we need a soft symlink / shim for a longer grace period? (Current stance: no.)
- Any telemetry desired before deletion? (Optional: count stub invocations via metrics; currently not instrumented.)

## Acceptance Criteria
- Repository contains zero executable references to the bridge.
- Panels artifacts derived solely from unified loop.
- Tests green; documentation consistent.

---
PR Checklist Template (for execution phase):
- [ ] Removed files
- [ ] Updated docs
- [ ] Updated tests
- [ ] CHANGELOG updated
- [ ] Grep confirms zero references
- [ ] Squash & merge
