# SSE Security & Hardening (Round 1 & 2)

This document consolidates the security posture of the Summary SSE streaming endpoint and Unified HTTP server.

## Overview
The SSE publisher provides a low-latency event stream for summary panel updates. Two deployment modes now exist:
- Legacy dedicated SSE server (`scripts.summary.sse_http.serve_sse_http`) on `/summary/events`
- Unified HTTP server (`scripts.summary.unified_http.serve_unified_http`) consolidating `/summary/events`, `/summary/resync`, `/summary/health`, and `/metrics`

Security hardening has been delivered in two rounds:

| Round | Focus | Key Additions |
|-------|-------|---------------|
| 1 | Baseline controls | API token header auth, IP allow list, connection cap, payload truncation, sanitized event names, graceful shutdown bye event |
| 2 | Abuse & observability | Per-IP connection rate limiting, User-Agent allow list, X-Request-ID echo for correlation, audit logging (hashed UA), expanded metrics, structured diff resilience |

## Event Security
Events are JSON serialized with a strict size cap (`G6_SSE_MAX_EVENT_BYTES`, default 65536). Oversized payloads are replaced by an empty `{}` body and emitted as `event: truncated` with a metric increment ( `g6_sse_http_security_events_dropped_total`). Event names are sanitized to alphanumerics plus `_` and `-`.

## Authentication & Network Controls
| Control | Env Var | Behavior |
|---------|---------|----------|
| API Token (optional) | `G6_SSE_API_TOKEN` | Require matching `X-API-Token` header or return 401 |
| IP Allow List (optional) | `G6_SSE_IP_ALLOW` | Comma-separated exact IPs; mismatch returns 403 |
| Global Connection Cap | `G6_SSE_MAX_CONNECTIONS` | Rejects excess with 429 + `Retry-After: 5` |
| CORS Allow Origin | `G6_SSE_ALLOW_ORIGIN` | Sets `Access-Control-Allow-Origin` header |

## Per-IP Connection Rate Limiting (Round 2)
Set `G6_SSE_IP_CONNECT_RATE` to `N/W` (or `N` for `N/60`). Applies a sliding window: if an IP attempts more than N accepted connections within W seconds, additional attempts receive 429 (`rate limited`). Metric increment: `g6_sse_http_rate_limited_total`.

Example: `G6_SSE_IP_CONNECT_RATE=5/30` → Allow at most 5 connections per 30-second window per IP.

## User-Agent Allow List (Round 2)
`G6_SSE_UA_ALLOW` is a comma-separated list of substrings. If set, incoming `User-Agent` must contain at least one substring; otherwise 403 is returned. Metric: `g6_sse_http_forbidden_ua_total`.

## Request Correlation (Round 2)
If client supplies an `X-Request-ID` header (recommended: UUID or short token), it is sanitized (alphanumerics, `_`, `-`) and echoed back in the response headers for diagnostics and log correlation.

## Audit Logging
On connection accept / reject, structured log lines are emitted:
```
INFO  sse_conn accept ip=<ip> req_id=<id> ua_hash=<first12>
WARN  sse_conn reject ip=<ip> reason=<rate_limited|forbidden_ua> ua_hash=<first12>
```
The `ua_hash` is the SHA-256 hash of the User-Agent (first 12 hex chars) to avoid leaking raw UA while enabling grouping.

## Metrics Reference
Prometheus counters/histograms (prefix `g6_sse_http_`):

| Name | Type | Description |
|------|------|-------------|
| active_connections | Gauge | Current accepted SSE connections |
| connections_total | Counter | Total accepted connections |
| disconnects_total | Counter | Total disconnects |
| rejected_connections_total | Counter | Rejections due to cap/auth/IP (legacy bucket) |
| auth_fail_total | Counter | API token mismatches |
| forbidden_ip_total | Counter | IP allow list violations |
| rate_limited_total | Counter | Per-IP connection rate limit rejections |
| forbidden_ua_total | Counter | User-Agent allow list rejections |
| events_sent_total | Counter | Events written to clients |
| events_dropped_total | Counter | Per-connection event drops (rate limiter) |
| security_events_dropped_total | Counter | Oversized / sanitized events dropped |
| event_size_bytes | Histogram | Size distribution of raw SSE event frames |
| event_queue_latency_seconds | Histogram | Time from enqueue (publisher _ts_emit) to write |
| connection_duration_seconds | Histogram | Lifetime of SSE connections |

## Structured Diffs & Latency Tracking
Structured diff mode (`G6_SSE_STRUCTURED=1`) emits `panel_diff` events containing only changed panels. Each event includes an internal `_ts_emit` timestamp (not part of public schema) used purely for latency histogram observation.

## Testing Summary
Automated tests cover:
- Bye event emission on shutdown.
- Unified HTTP endpoints health/resync/events.
- Structured diff emission.
- Advanced metrics presence.
- Security round 2: rate limiting (429), UA filtering (403), X-Request-ID echo.

## Deployment Guidance
1. Set API token and IP allow list in production.
2. Enable rate limiting sized to expected legitimate client reconnection behavior.
3. Add a stable User-Agent prefix for official clients; configure `G6_SSE_UA_ALLOW` accordingly.
4. Scrape `/metrics` via unified server or existing Prometheus endpoint.
5. Monitor `rate_limited_total` and `forbidden_ua_total` for abuse indicators.

## Backward Compatibility & Deprecations
Legacy gating env vars (`G6_SSE_ENABLED`, `G6_SUMMARY_RESYNC_HTTP`, etc.) are ignored—SSE is auto-enabled when available. Use `G6_DISABLE_RESYNC_HTTP=1` only to disable resync endpoint. Remaining deprecated scripts (e.g., legacy run_live-based orchestrators) are removed; tests enforce absence.

## Future Considerations
- Optional token bucket shared across processes (cluster coordination).
- Dynamic UA reputation scoring.
- Per-event payload encryption (if WAN exposure increases threat model).
- Structured panel baseline caching for faster cold-start resync.

---
For migration steps and broader lifecycle changes, see `DEPRECATIONS.md`.

## Centralization Update (SummaryEnv Integration)

Security-related environment variables are now parsed once into `SummaryEnv` and reused by both `sse_http` and `unified_http` handlers:

| Env Var | SummaryEnv Field | Purpose |
|---------|------------------|---------|
| `G6_SSE_API_TOKEN` | `sse_token` | Optional shared secret for `X-API-Token` header auth |
| `G6_SSE_IP_ALLOW` | `sse_allow_ips` | Comma list of IPs granted access |
| `G6_SSE_IP_CONNECT_RATE` | `sse_connect_rate_spec` | Per-IP accept rate limiter window spec |
| `G6_SSE_UA_ALLOW` | `sse_allow_user_agents` | Substring allow list for User-Agent filtering |
| `G6_SSE_ALLOW_ORIGIN` | `sse_allow_origin` | CORS header value |

Handlers still read the following directly (tunable live, low parse complexity):
`G6_SSE_MAX_CONNECTIONS`, `G6_SSE_MAX_EVENT_BYTES`, `G6_SSE_EVENTS_PER_SEC`.

### Escape Hatch
Set `G6_SSE_SECURITY_DIRECT=1` to bypass the centralized values and re-read raw environment variables for each connection (useful in ephemeral debug sessions where vars are mutated after process start without restart). This flag is best-effort and should not be enabled in normal production deployments.

### Failure Mode Safety
If `load_summary_env()` raises, code falls back to legacy direct reads (fail-open strategy favoring availability). Future enhancement: add a strict mode (`G6_SSE_SECURITY_STRICT=1`) to instead fail closed on invalid configuration.

### Testing Guidance
After monkeypatching environment values in tests, call `load_summary_env(force_reload=True)` to ensure subsequent SSE connections reflect the changes.

Last updated: Centralization pass (2025-10-03).
