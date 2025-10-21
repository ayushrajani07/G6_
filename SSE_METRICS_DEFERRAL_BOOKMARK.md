SSE metrics visibility — bookmark (deferred)

Date: 2025-10-14

TL;DR
- Safe to defer fixing SSE metrics visibility for a few hours. Normal data flow, caching, and most dashboards continue to work.
- Only artifacts referencing the two SSE metric families may show N/A or fail: g6_sse_http_active_connections and g6_sse_http_connections_total.

Temporary toggles (during market hours)
- PowerShell (current session only):
  - $env:G6_SSE_HTTP = "0"  # disable SSE HTTP path
  - $env:G6_SUMMARY_METRICS_HTTP = "0"  # optional: disable summary metrics server
- Tests: run a subset that skips SSE
  - pytest -q -k "not sse"
  - Or use VS Code task: "pytest - parallel (safe subset)"

Repro notes
- Focused test: tests/test_metrics_server_basic.py::test_metrics_server_exposes_sse_metrics
- Local manual check (Python requests or curl):
  - GET http://127.0.0.1:9325/metrics
  - Expect to see the two names anywhere in the body:
    - g6_sse_http_active_connections
    - g6_sse_http_connections_total

What’s implemented so far
1) Pre-registration and zero-sampling of SSE metrics families
   - scripts/summary/sse_http.py: _maybe_register_metrics()
2) Global generate_latest wrappers/injectors
   - sitecustomize.py: injects SSE families if missing; adds UDS cache metrics
3) Summary metrics server-level injection
   - scripts/summary/metrics_server.py: in do_GET, injects/forces SSE families before responding
4) Diagnostics and identifiers
   - Server response header: Server: G6SummaryMetrics/0.1
   - Start sentinel file when server binds to port 9325

Observed behavior as of 2025-10-14
- /metrics (port 9325) responds with 200 and core metrics, but the two SSE names were not visible in body during a quick repro.
- Start sentinel exists; scrape diagnostics were inconsistent/not found, suggesting either a different handler path or file-write context under the test harness.

Likely root causes (hypotheses)
- Test is hitting a different code path/handler instance than the one instrumented.
- File writes from the handler are sandboxed or writing to an unexpected CWD.
- Registry resets in autouse fixtures interfering with scrape-time state, though response-level prepend should have bypassed that.

Next steps (post-market)
1) Re-run the focused test to confirm current state.
2) Add an in-memory marker/header from do_GET (e.g., X-G6-SSE-Injected: 1) and assert it in the test to confirm the exact handler path.
3) If header present but names absent, dump the exact response body prefix captured inside the handler to compare with client side.
4) Ensure unconditional prepend executes before write; verify no downstream middleware rewrites body.
5) If the test uses a different server, align or export a single helper to start the metrics server used by tests.

Code pointers
- scripts/summary/metrics_server.py  # /metrics handler (port 9325)
- scripts/summary/sse_http.py        # SSE metrics family registration
- sitecustomize.py                   # global generate_latest & collector injectors
- src/metrics/testing.py             # force_new_metrics_registry utilities
- scripts/summary/unified_http.py    # alternate /metrics path (module-level)

Minimal success criteria
- GET /metrics on port 9325 contains both strings:
  - g6_sse_http_active_connections
  - g6_sse_http_connections_total

Change log
- 2025-10-14: Bookmark created; fix deferred until after market hours.
