# Phase 7 Scope – Streaming Convergence & Flag Retirement

Date: 2025-10-03
Status: Draft (initial commit)
Owner: Summary / Streaming Maintainers

## 1. Theme
Converge streaming + HTTP endpoints into a cohesive, always-on subsystem while retiring transitional flags, introducing structured diff options, improving observability, and tightening security.

## 2. Goals
| ID | Goal | Success Criteria |
|----|------|------------------|
| G1 | Auto-enable SSE + resync | `G6_SSE_ENABLED` & `G6_SUMMARY_REWRITE` ignored (warning only); SSE active when `G6_SSE_HTTP=1` or unified HTTP server enabled. |
| G2 | Unified HTTP server | Single server binds once; dispatches `/summary/events`, `/summary/resync`, `/metrics`, `/summary/health` (future). Graceful shutdown sends bye to SSE clients. |
| G3 | Structured panel diffs | Optional `G6_SSE_STRUCTURED=1` emits `panel_update_structured` events with structured fields (`panel`, `hash`, `changes`). |
| G4 | Advanced metrics | Histograms: event size, panel_update latency; gauge/hist for connection durations; counters for structured vs legacy events. |
| G5 | Flag removal readiness | Checklist script passes (zero code + docs references) before deleting deprecated flags. |
| G6 | Security hardening round 2 | Per-IP connection rate limit, user-agent allowlist, request ID echo header, sanitized audit log lines. |
| G7 | Client reference | Minimal Python & JS clients (auto reconnect, backoff, resync logic). |
| G8 | Performance optimizations | Panel hash caching avoids redundant hashing; JSON payload reuse reduces allocation; cycle time overhead < +2% vs Phase 6 baseline under 10 clients. |
| G9 | Release readiness script | One command validates metrics presence, removed flags, doc updates, and emits JSON report. |

## 3. Non-Goals
* TLS termination (delegated to reverse proxy).
* Full WebSocket upgrade path (future evaluation).
* Cross-panel dependency diff semantics (strictly per-panel this phase).

## 4. Work Breakdown
| Task | Description | Artifacts |
|------|-------------|-----------|
| T1 | Flag removal checklist script | `scripts/dev/flag_removal_check.py` |
| T2 | Auto-enable & ignore flags | Patches in config + deprecations update |
| T3 | Unified server skeleton | `scripts/summary/http_server.py` (dispatcher, graceful shutdown integration) |
| T4 | Migrate SSE / resync / metrics to unified server | Remove direct `serve_sse_http` calls when enabled |
| T5 | Structured diff mode | Hash + change extractor, new event type, tests |
| T6 | Metrics expansion | Add histograms & gauges, update docs & scrape test |
| T7 | Bye event test | `tests/test_sse_bye_event.py` |
| T8 | Security round 2 | Rate limiting per-IP + UA allowlist + request ID |
| T9 | Client reference Python | `scripts/summary/client_example.py` |
| T10 | Client reference JS | `web/examples/sse_client.js` |
| T11 | Hash / json optimizations | Micro-bench; reuse serialized panel updates |
| T12 | Docs update | `terminal_dash.md`, `DEPRECATIONS.md` additions |
| T13 | Release readiness script | `scripts/dev/release_readiness.py` |

## 5. Structured Diff Outline
Event: `panel_update_structured`
```jsonc
{
  "cycle": 1234,
  "updates": [
    {
      "panel": "indices",
      "hash": "<sha256>",
      "added": ["NIFTY"],
      "removed": [],
      "changed_lines": [ {"index":0,"old":"count: 2","new":"count: 3"} ],
      "total_lines": 5
    }
  ]
}
```
Extraction logic computes a simple line-level diff (replace only) keeping operations bounded (O(n)). If diff size exceeds threshold (env: `G6_SSE_STRUCT_MAX_CHANGES`), fallback to legacy `panel_update` for that panel.

## 6. Metrics Additions (Proposed)
| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `g6_sse_event_size_bytes` | Histogram | `type` | Observed serialized event payload size |
| `g6_sse_panel_update_latency_sec` | Histogram | `panel` (maybe sampled) | Time from hash compute to write complete |
| `g6_sse_connection_duration_sec` | Histogram | — | Observed at disconnect |
| `g6_sse_structured_updates_total` | Counter | — | Structured diff events sent |
| `g6_sse_resync_requests_total` | Counter | — | Count HTTP resync hits |

## 7. Configuration Changes
| New Env | Purpose | Default |
|---------|---------|---------|
| `G6_SSE_STRUCTURED` | Enable structured diff events | off |
| `G6_SSE_STRUCT_MAX_CHANGES` | Max per-panel line changes before fallback | 40 |
| `G6_SSE_IP_CONN_RATE` | Max new connections per-IP per minute | 60 |
| `G6_SSE_UA_ALLOW` | Comma-separated allowed UA prefixes | (unset = allow all) |
| `G6_SSE_REQUEST_ID_HEADER` | Header name to echo generated request id | `X-Request-ID` |

## 8. Performance Targets
Metric | Target
-------|-------
Cycle latency delta vs Phase 6 | < +2%
Median panel_update event size | < 8 KB under typical churn
p95 structured diff extraction time | < 2 ms per panel

## 9. Rollback Plan
* Structured mode guarded by flag—disable to revert to legacy events.
* Unified server can be bypassed by setting `G6_UNIFIED_HTTP=0` (temporary backdoor) until confidence gained.
* If metrics histograms cause cardinality issues, disable via `G6_SSE_METRICS_EXTENDED=0`.

## 10. Testing Strategy
Test | Purpose
-----|--------
`test_sse_bye_event.py` | Ensures bye event & connection duration metrics recorded
`test_sse_structured_diff_basic.py` | Validates added/removed/changed detection
`test_sse_structured_diff_threshold.py` | Fallback when changes exceed cap
`test_unified_http_dispatch.py` | Route dispatch correctness
`test_flag_removal_check.py` | Ensures script flags stale references
`test_release_readiness.py` | End-to-end pre-release validation

## 11. Open Questions
1. Should structured diff include original full panel lines when changes exceed threshold (vs forcing fallback)?
2. Introduce backpressure signaling (retry-after event) when server shedding load?
3. Provide optional gzip at unified server layer or rely solely on proxy?

## 12. Timeline (Tentative)
Week | Focus
-----|------
1 | T1–T4 (flags, unified server skeletal migration)
2 | T5–T7 (structured diff + tests + bye coverage)
3 | T8–T11 (security, performance polish)
4 | T12–T13 (docs + release readiness) & stabilization

## 13. Acceptance Criteria
* All goals G1–G9 satisfied with green test suite.
* Deprecated flags removed from code & docs (except historical sections).
* Structured diff mode documented & optional.
* Readiness script JSON consumed in CI.
* No regression in existing SSE integration tests.

---
(End Phase 7 Scope)
