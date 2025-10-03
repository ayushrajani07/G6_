# Environment Variable Lifecycle (Phase 3 Draft)

This document tracks the status of selected environment variables and their
planned evolution. It complements `docs/env_dict.md` by adding temporal
metadata (introduction, deprecation, removal target) and replacement guidance.

| Name | Status | Introduced | Deprecated | Removal Target | Replacement | Notes |
|------|--------|------------|------------|----------------|-------------|-------|
| G6_METRICS_ENABLED | active | 2024-Q4 | - | - | - | Canonical metrics enable flag |
| G6_METRICS_ENABLE | deprecated | 2024-Q2 | 2025-Q1 | 2025-Q4 | G6_METRICS_ENABLED | Legacy duplicate; migrate |
| G6_ALLOW_LEGACY_PANELS_BRIDGE | deprecated | 2024-Q3 | 2025-Q2 | 2025-Q4 | - | Panels bridge unification |
| G6_SUMMARY_LEGACY | deprecated | 2024-Q2 | 2025-Q2 | 2025-Q4 | - | Unified summary model adoption |
| G6_REFACTOR_DEBUG | experimental | 2025-Q2 | - | - | - | Temporary diagnostics flag |

## Status Definitions
- active: Supported and recommended.
- experimental: May change or be removed; not guaranteed stable.
- deprecated: Supported but slated for removal (plan migration).
- removed: No longer honored; setting has no effect.

## Governance
1. New flags start as experimental unless stability is guaranteed.
2. Deprecations require: documentation update, lifecycle table entry, warning log on use.
3. Removal requires: two release cycles after deprecation and explicit CHANGELOG entry.

## Next Steps
- Expand coverage to remaining `G6_*` flags (automated cross-check against inventory).
- Add runtime warning for deprecated names (hook into config/runtime assembly).
- Generate this table automatically from `src/config/env_lifecycle.py` in future CI step.
