# Wave 3 Summary: Semantic Dashboard Typing & Protocol Adoption

Date: 2025-09-28

## Scope Executed
1. Centralized dashboard / panel data shapes via `src/types/dashboard_types.py` (StreamRow, FooterSummary, storage slices, ErrorEvent, HistoryEntry union, RollState, protocols).
2. Refactored `metrics_cache.py` to emit strongly typed structures (rows, footer, storage snapshot, error events) and to maintain a typed history deque.
3. Introduced `UnifiedSourceProtocol` in `app.py` with guarded optional import; endpoints now clearly express availability semantics.
4. Added `OutputRouterProtocol` usage pattern (now embodied in PanelsWriter; former panel_updater removed) with transactional publish + removal of extraneous fallback duplication.
5. Removed legacy `# type: ignore` markers (assignment) by tightening TypedDict usage and shaping history entries properly.
6. Extended developer guidelines (Section 15) documenting dashboard typing conventions, protocols, anti-patterns, and migration steps.

## Key Improvements
| Area | Before | After | Benefit |
|------|--------|-------|---------|
| Panel Rows | `List[Dict[str, Any]]` | `List[StreamRow]` | Static safety & discoverability |
| Storage Snapshot | Untyped nested dict | `StorageSnapshot` (Csv/Influx/Backup) | Clear sink extensibility |
| Error Events | Implicit tuple logic | `List[ErrorEvent]` | Simpler panel rendering & sorting |
| Unified Source | Any (or absent) | Protocol + optional import | Safer endpoint handling |
| Router Publish | Ad-hoc attribute access | Protocol + txn context | Atomic panel updates |
| History | Mixed dict shards | `HistoryEntry` union | Foundation for future discriminated union |

## Removed Ignored Typing Noise
All prior `# type: ignore[assignment]` in the dashboard metrics layer are eliminated; only targeted, justified ignores remain elsewhere (if any) for optional runtime imports.

## Risk & Follow-up
No logic changes to metric parsing; risk limited to typing & structural transformation. Fallback paths preserved for optional imports. Minor chance of overlooked panel key in templates—initial manual scan is clean.

## Wave 4 Proposed Work
| Priority | Task | Description | Expected Gain |
|----------|------|------------|---------------|
| P1 | Discriminated History Union | Add `{'kind': 'errors'|'storage', ...}` to remove structural inference | Cleaner type narrowing; simpler tooling |
| P1 | Panel Payload TypedDicts | Define `IndicesStreamPanel`, `StoragePanel`, etc. for on-disk JSON root | End-to-end schema clarity |
| P1 | Template Field Audit Test | Add pytest that loads templates & asserts all referenced keys exist in sample TypedDict instance | Prevent silent template drift |
| P2 | Error Handler Protocol | Abstract `get_error_handler()` behind `ErrorHandlerProtocol` (handle_error signature) | Easier mocking in tests |
| P2 | Memory Snapshot Typing | Strongly type `_build_memory_snapshot` return & related fragment | Consistency, fewer `dict` accesses |
| P3 | Pydantic Models (Optional) | Lightweight models for external API endpoints (`/api/unified/*`) | Validation & self-doc |
| P3 | Router Capability Probe Helper | Utility function `supports_panels(router)` centralizing duck-typing test | Reduce repetition |
| P3 | Typed Panel Generation Tests | Snapshot tests verifying JSON schema shape vs TypedDict structure | Regression safety |
| P4 | mypy Strict Subpackage | Enable stricter flags (`disallow-any-generics`) under `src/web/dashboard` | Guardrail for regressions |

## Suggested Ordering
1. Panel payload root TypedDicts + discriminated history union (unlock simplified template assertions).
2. Template audit test to freeze shape expectations.
3. Error handler protocol + memory snapshot typing.
4. Optional Pydantic layer & stricter mypy config.

## Metrics for Success (Wave 4)
- Zero `Any` usages in dashboard subpackage (except deliberate external library boundaries).
- Test asserting template key coverage passes.
- No new `# type: ignore` required for panel-related modules.

## Notes
If a future real-time streaming transport (WebSocket / SSE) is introduced, the current TypedDicts can directly serve as serialized envelope schemas without further refactor.

---
End of Wave 3 Summary.
