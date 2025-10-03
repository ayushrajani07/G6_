# Wave 4 Tracking

## 1. Overview
Wave 4 focus: elevate typing rigor, introduce panel envelopes (dual legacy + enveloped JSON), add template safety audit, unify endpoint schema typing, and harden dashboard code under stricter mypy rules with minimal runtime impact.

## 2. Task Matrix (Completed vs Pending)
| Task | Description | Status | Key Artifacts |
|------|-------------|--------|---------------|
| 1 | History entries discriminated union (`kind: 'errors'|'storage'`) | Done | `dashboard_types.py`, `metrics_cache.py` |
| 2 | Panel envelope root TypedDicts + dual write (indices, storage, footer) | Done | PanelsWriter (formerly panel_updater), `dashboard_types.py` |
| 2a | PoC template migration (footer fragment) | Done | `_footer_fragment.html`, `footer_enveloped.json` usage |
| 3 | Template field audit test (regex scan) | Done | `tests/test_template_audit.py` |
| 4 | `ErrorHandlerProtocol` introduction | Done | `dashboard_types.py`, `error_handling.py` (attempt & revert) |
| 5 | `MemorySnapshot` TypedDict + endpoint return typing | Done | `dashboard_types.py`, `app.py` |
| 6 | `supports_panels` helper + diagnostics | Done | `panel_support.py`, PanelsWriter |
| 7 | Unified endpoint response TypedDicts | Done | `dashboard_types.py`, `app.py` |
| 8 | Stricter mypy for `src.web.dashboard.*` + remediation | Done | `mypy.ini`, `app.py`, `metrics_cache.py` |
| 8b | Literal `kind` tightening & discriminant refactor | Done | `dashboard_types.py`, `metrics_cache.py` |
| 9 | Tracking document (this file) | In Progress | `WAVE4_TRACKING.md` |
| 10 | Storage panel template migration to envelope fallback | Done | `_storage_fragment.html`, `storage_enveloped.json` usage |

## 3. Typing & Mypy Hardening
- Added `[mypy-src.web.dashboard.*]` section with: `disallow_untyped_defs`, `disallow_incomplete_defs`, `no_implicit_optional`, `warn_return_any`, `warn_unreachable`, `strict_equality`.
- Introduced/enhanced TypedDicts:
  - Panel payloads: `IndicesStreamPanel`, `StoragePanel`, `FooterPanel` (now with `Literal` kinds)
  - Snapshots & events: `StreamRow`, `FooterSummary`, `StorageSnapshot`, `ErrorEvent`, `MemorySnapshot`
  - History: `HistoryErrors`, `HistoryStorage` (discriminated union via `kind` `Literal`)
  - Unified API: `UnifiedStatusResponse`, `UnifiedIndicesResponse`, `UnifiedSourceStatusResponse` and nested core/resources/adaptive/index entries
- Protocols leveraged: `UnifiedSourceProtocol`, `OutputRouterProtocol`, `PanelsTransaction`, `ErrorHandlerProtocol`.
- Error count journey (dashboard modules): 49 initial strict errors -> 0 (after refactor & helper extraction). Removed all unused `# type: ignore` lines.
- Extracted `_build_error_events` + `_previous_error_value` to eliminate a persistent false-positive unreachable warning.

## 4. Panel Envelope Migration Status
- Dual-output strategy: legacy JSON plus `<name>_enveloped.json` for indices stream, storage, footer.
- Footer template updated to prefer `footer_enveloped.json` (successful PoC of envelope consumption pattern).
- Storage template now migrated (prefers `storage_enveloped.json` with fallback to `snapshot.storage`). Pattern proven repeatable.
- Transitional casts minimized; future step: migrate remaining templates to enveloped variant & retire legacy file writes.
- Diagnostic helper `supports_panels` centralizes capability detection (with `panels_support_diagnostics`).

## 5. Template Safety & Audit
- `tests/test_template_audit.py` scans Jinja templates for `snapshot.*` attribute chains.
- Validates presence against sample structures (special-case handling for enveloped footer fallback).
- Provides early detection if field names drift during refactors.

## 6. Key Refactors & Rationale
- Consolidated kind-based branching via `Literal` discriminants -> clearer code paths & safer narrowing.
- Isolated error events aggregation to enable pure-function testing and remove control-flow complexity.
- Introduced typed memory snapshot and unified API payload wrappers for downstream tooling / future clients.
- Footer panel migration acts as reference implementation for remaining panel transitions.

## 7. Remaining / Deferred Follow-Ups
| Priority | Item | Rationale | Suggested Action |
|----------|------|-----------|------------------|
| High | Migrate remaining templates to envelopes | Unify data contract, deprecate legacy JSON duplication | Incremental template updates + remove legacy writes after adoption |
| High | Add unit tests for `_build_error_events` | Lock behavior & guard refactors | Create focused test with synthetic history states |
| Medium | Remove transitional casts in PanelsWriter path | Tighten type fidelity once all panels fully modeled | Replace any residual casts in summary panel write logic |
| Medium | Expand strict mypy scope beyond dashboard | Broaden static safety | Gradually add package-level strict sections |
| Medium | Introduce runtime schema validation (optional) | Defense in depth pre-template render | Lightweight pydantic or manual asserts under DEBUG |
| Low | Consider consolidating panel write logic | Reduce duplication between legacy & envelope writes | After legacy deprecation, collapse pathways |

## 8. Metrics & Outcomes
- Strict mypy adoption without suppressions achieved.
- Zero runtime-surface changes required for metrics ingestion.
- Template audit provides ongoing safety net for future refactors.
- Error event logic simplified (improved maintainability & testability).

## 9. Next Concrete Steps (Suggested Sequence)
1. Add tests for `_build_error_events` (cover: no history, single delta, multiple keys capped by `max_events`, negative/no-op deltas filtered).
2. Remove legacy footer & storage standalone JSON writes once dashboard definitively uses envelopes only (update test + doc).
3. Introduce envelope for memory or errors panel (if desired) to standardize panel contract.
4. Expand strict mypy to another focused package (candidate: `src.panels.*`).
5. Remove any remaining casts in PanelsWriter code; replace with properly typed assembly functions.
6. Add micro-benchmark or timing log for metrics cache augmentation (optional) to ensure refactors didn’t regress performance.

## 10. Reference Files Modified This Wave
- `src/types/dashboard_types.py`
  (Former) `scripts/panel_updater.py` (removed in favor of unified PanelsWriter)
- `src/web/dashboard/app.py`
- `src/web/dashboard/metrics_cache.py`
- `src/utils/panel_support.py`
- `src/web/dashboard/templates/_footer_fragment.html`
- `tests/test_template_audit.py`
- `mypy.ini`

## 11. Validation Summary
- Mypy: clean (dashboard modules) under strict subset.
- Template audit: passes after footer envelope integration.
- Runtime safety: Network/envelope reads wrapped in error handler with low severity.

## 12. Notes
- Discriminated unions now unlock future compile-time assurance for history-based branching.
- Envelope adoption path intentionally incremental to minimize deployment risk.
- Structured tracking file (this doc) can be versioned each wave; consider adding a brief changelog header in future iterations.

---
_Last updated: (auto-generated) Wave 4 typing & envelopes tracking._
