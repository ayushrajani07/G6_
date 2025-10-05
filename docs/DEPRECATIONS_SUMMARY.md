# Deprecations Summary (Generated Phase 3)

This document consolidates active deprecations to reduce drift and guide removal work.

## Deprecated Environment Variables

| Variable | Deprecated Since | Target Removal | Replacement | Notes |
|----------|------------------|----------------|-------------|-------|
| `G6_METRICS_ENABLE` | 2025-Q1 | 2025-Q4 | `G6_METRICS_ENABLED` | Legacy metrics enable flag; unified path uses `G6_METRICS_ENABLED`. |
| `G6_ALLOW_LEGACY_PANELS_BRIDGE` | 2025-Q2 | 2025-Q4 | (none) | Panels bridge unified; no longer needed. |
| `G6_SUMMARY_LEGACY` | 2025-Q2 | 2025-Q4 | (none) | Replaced by unified summary app (`scripts/summary/app.py`). |

Deprecated vars trigger a runtime warning during bootstrap when set.

## Deprecated CLI Flags

| Flag | Status | Notes |
|------|--------|-------|
| `--enhanced` (orchestrator loop) | Removed (2025-10-05) | Flag accepted previously as no-op; collectors unified. Update any scripts to drop it. |

## Deprecated Modules

| Module | Replacement | Notes |
|--------|-------------|-------|
| `scripts/summary_view.py` | `scripts/summary/app.py` | Kept as a thin compatibility shim (StatusCache, plain_fallback, wrapper functions). New feature work must target the unified app. |

## Operational Guidance

1. New features should not introduce additional deprecated flags unless absolutely necessary; prefer additive env keys and document them in `ENV_LIFECYCLE.md`.
2. When removing a deprecated item:
   - Ensure at least one full release cycle elapsed since deprecation notice.
   - Update tests referencing shimmed functions.
   - Remove row from this document and move entry to a changelog removal section.
3. For automation, a future governance test can parse `src/config/env_lifecycle.py` and assert every deprecated var appears in this doc.

## Next Cleanup Targets (Not Yet Deprecated)

| Candidate | Rationale | Action Consideration |
|-----------|-----------|----------------------|
| Legacy panels bridge code paths (if any lingering) | Redundant with unified panels writer | Confirm no runtime imports; remove after verifying tests. |
| Unused enhanced UI placeholder package if never populated (`src/ui_enhanced`) | Present but unused beyond flag marker | Either populate with real features or deprecate in next phase. |

---
_Last updated: 2025-10-05_
