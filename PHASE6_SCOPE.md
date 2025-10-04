# Phase 6 Scope: Production Streaming & Legacy Summary Removal\n\n_Date: 2025-10-03_\n\n## Theme\nElevate the summary subsystem from experimental diff + SSE scaffolds to a production-grade streaming service while completing legacy path retirement and tightening operational & security posture.\n\n## Primary Objectives\n1. Real SSE HTTP Endpoint (text/event-stream) – low-latency push of summary events.\n2. Operational Hardened Interfaces – auth, rate limiting, graceful shutdown, metrics.\n3. Legacy Code Retirement – remove `summary_view.py` & stale flags (rewrite, diff toggles).\n4. Documentation & Adoption – clear run-book for operators, resilience (resync + reconnect).\n5. Performance & Load Confidence – benchmark harness for multi-connection scenarios.\n\n## Out of Scope (Phase 6)\n- Web UI rendering / browser client implementation (Phase 7 candidate).\n- Horizontal sharding of summary generation (single-process optimization only).\n- Persistent snapshot store or WAL (evaluate post streaming stabilization).\n\n## Detailed Work Items\n| ID | Area | Description | Acceptance Criteria | Risk | Mitigation |\n|----|------|-------------|---------------------|------|-----------|\n| S6-1 | SSE HTTP | Implement `/summary/events` streaming endpoint binding to unified loop publisher | Receives hello + full_snapshot then diff events; withstands 5 min no-change (heartbeat) | Medium | Start with single-threaded writer; backpressure simple disconnect |\n| S6-2 | Auth | API token header `X-API-Token` & optional IP allow list | 401 on missing/invalid; 403 on disallowed IP | Low | Fail fast before subscription |\n| S6-3 | Rate Limit | Max N concurrent (env) & per-conn event burst throttle | Connection refused (429) beyond limit; events truncated gracefully | Medium | Document safe defaults |\n| S6-4 | Metrics | `/metrics` exposes SSE gauges/counters + connection count | Prometheus scrape returns without blocking event stream | Low | Use separate HTTP thread |\n| S6-5 | Resync Integration | SSE client can fetch `/summary/resync` then resume stream using hashes | Hash parity test passes with client baseline | Low | Shared builder already in place |\n| S6-6 | Legacy Removal | Delete `summary_view.py`; update deprecation tables | CI green; no imports remain | Medium | Stage behind branch; run grep script |\n| S6-7 | Flag Retirement | Deprecation warnings emitted when deprecated env set | Warnings cover: rewrite, plain diff, SSE enable toggle | Low | Centralize warns in config load |\n| S6-8 | Load Harness | `bench_sse.py` simulates M connections & records events/sec | Report JSON summary (avg latency, events/sec) | Medium | Use threads; keep simple |\n| S6-9 | Shutdown | Graceful SIGINT closes listeners & flushes metrics | No stack traces on Ctrl+C; clients see `event: bye` | Low | Signal handlers minimal |\n| S6-10 | Security | Header sanitation; no traceback leakage | Fuzz test passes; deliberate error returns minimal body | Medium | Wrap handlers with safe error boundary |\n| S6-11 | Docs | Update `terminal_dash.md` + new `STREAMING.md` | Operators can configure & troubleshoot in <10m | Low | Include FAQ & failure modes |\n| S6-12 | Checklist Script | `scripts/dev/check_flag_removal.py` verifying no lingering names | Script returns zero findings pre-removal | Low | Integrate into CI optional job |\n\n## Metrics / KPIs\n- Mean SSE event dispatch latency < 20ms (single client, local).\n- Heartbeat accuracy: no more than ±1 cycle drift over 5-minute idle test.\n- CPU overhead increase < 5% vs Phase 5 baseline at 10 connections.\n- Memory footprint stable (< +10MB) with 20 idle connections.\n\n## Rollout Strategy\n1. Ship endpoint behind existing `G6_SSE_ENABLED` (still honored) + new `G6_SSE_HTTP` toggle.\n2. Bake for one release collecting metrics (connections, errors, backpressure incidences).\n3. Auto-enable when stable; mark toggle deprecated; schedule removal.\n\n## Risk Register\n| Risk | Impact | Probability | Response |
|------|--------|-------------|----------|
| High event burst causes memory growth | OOM / degraded latency | Medium | Add per-connection queue cap & drop oldest events warning |
| Unauthorized access to streaming data | Data exposure | Low | Require token; default deny if token set |
| Blocking metrics scrape | Event latency spike | Low | Separate thread / non-blocking collect |
| Slow client stalls broadcast | Head-of-line blocking | Medium | Use per-connection buffering & timeout disconnect |

## Dependencies
- `prometheus_client` already present (Phase 5 metrics). 
- Existing `SSEPublisher` event queue logic. 
- Resync endpoint (Phase 5) for recovery.

## Exit Criteria
- All S6 work items completed & documented.
- Legacy summary removed; deprecation table updated with actual removal dates.
- Bench harness results archived (`archive/` dated folder) with baseline JSON.
- CI includes SSE integration tests (happy path + reconnect + heartbeat idle).

## Post-Phase Candidates (Phase 7+)
- Browser dashboard (static HTML + JS SSE client) consuming events.
- Multi-process or distributed summary generation.
- Snapshot persistence & replay log.
- Advanced filtering (panel subset, compression, gzip negotiation).

---
Owner: Summary / Streaming Maintainers

