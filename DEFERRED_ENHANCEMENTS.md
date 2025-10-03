# Deferred Enhancements (Unified Summary Architecture)

This file tracks intentionally deferred items after Phase 1 remediation.

## 1. SSE / Event Ingestion Layer
- Implement network SSE/WebSocket client feeding diff events
- Integrate with `merge_panel_diff` for incremental panel state updates
- Backpressure & reconnect strategy
- Unit tests for diff merge edge cases (removals, type shifts)

## 2. Snapshot Model Evolution
Status: PARTIAL – `UNIFIED_MODEL.md` created; adapter still present pending native assembler emission.

- Promote `from_legacy_unified_snapshot` to internal only once assembler returns native `UnifiedStatusSnapshot` (TODO)
- Native assembler production of `UnifiedStatusSnapshot` (TODO)
- Schema version bump policy doc & migration helpers (policy documented in `UNIFIED_MODEL.md`, helpers TODO)
- Add rolling window performance stats (latency p95 / avg) with optional ring buffer (TODO)

## 3. Curated Layout Integration
- Refactor curated layout to consume `UnifiedStatusSnapshot` directly
- Add toggles for minimal vs verbose curated modes
- Export curated layout metrics (render time, active blocks pruned)

## 4. Plugin System Enhancements
- Runtime plugin enable/disable via config file (JSON/YAML)
- Structured logging context injection (cycle number, snapshot ts)
- Plugin health tracking (last success ts, error count)

## 5. Metrics & Observability
- Standardized metric names for DQ counts, alert severities, cycle durations
- Histogram support for cycle duration & snapshot assembly time
- Optional OpenTelemetry exporter plugin

## 6. Testing & QA
- Golden snapshot fixture comparisons (ensure deterministic fields stubbed)
- Fuzz tests for `merge_panel_diff`
- Load test harness simulating 1s refresh with 10k adaptive alerts

## 7. Deprecation Cleanup
- Remove legacy derive_* implementations after external callers migrate
- Remove fallback paths in `plain_fallback` once model path proven stable

## 8. Documentation
Status: PARTIAL – Core model doc (`UNIFIED_MODEL.md`) in place.

- Architecture diagram (data flow: status + panels -> assembler -> model -> plugins) (TODO)
- FAQ section for common integration questions (TODO)
- Cross-reference from plugins doc to model doc (DONE)

## 9. Performance Optimizations
- Cache panel file stat() results, invalidate on mtime change
- Optional mmap read for large status file
- Concurrent panel file reads using thread pool (bounded)

## 10. Reliability
- Add checksum / version stamp in dossier for consumer validation
- Graceful handling when panels directory temporarily missing

---
Last updated: (auto) initial creation phase 1.
