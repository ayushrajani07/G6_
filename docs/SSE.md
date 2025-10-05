# Summary SSE & Unified HTTP (Consolidated)

This document merges prior `SSE_ARCHITECTURE.md` and `SSE_SECURITY.md` into a
single authoritative reference for the streaming subsystem.

## 1. Goals & Rationale
- Decouple network event ingestion from renderers.
- Centralize security & connection governance (auth, IP/UA allow, rate limits).
- Provide heartbeat & generation safety for reliable diff application.

## 2. Architecture Overview
(From legacy SSE_ARCHITECTURE) Key components:
- PanelStateStore (thread-safe; tracks baseline, diffs, severity, follow-ups, heartbeat timestamps, generations).
- SSEPanelsIngestor plugin (pulls events, mutates store, enriches snapshot with `panel_push_meta`).
- Unified Loop / Render Pipeline (consumes enriched snapshot; no raw SSE parsing).

Event lifecycle: network frame -> parse -> store mutation -> plugin injects metadata on next cycle -> renderer consumes consistent view.

### Heartbeat & Staleness
Store records last event/full/diff times; `heartbeat()` classifies `init|ok|warn|stale` with thresholds. Enriched snapshot adds compact keys: `last_evt`, `last_full`, `last_diff`, `stale_sec`, `health`.

### Generation Safety
Diffs dropped if generation mismatch; sets `need_full` to trigger baseline refresh expectation.

### Follow-up Alerts
Normalized list with bounded length providing recent notable events (severity + component context).

## 3. Security & Hardening
(From legacy SSE_SECURITY) Two server modes: legacy dedicated SSE HTTP and unified HTTP multi-endpoint server. Hardening rounds:

| Round | Focus | Key Additions |
|-------|-------|---------------|
| 1 | Baseline controls | API token auth, IP allow list, global connection cap, payload truncation & sanitization, graceful bye |
| 2 | Abuse & observability | Per-IP connect rate limiting, User-Agent allow list, X-Request-ID echo, hashed UA audit logging, expanded metrics |

### Event Framing & Limits
Events serialized JSON with size cap `G6_SSE_MAX_EVENT_BYTES` (default 65536). Oversized -> `{}` as `truncated` event, metric increment.

### Authentication & Network Controls
| Control | Env Var | Effect |
|---------|---------|--------|
| API Token | G6_SSE_API_TOKEN | Require matching `X-API-Token` or 401 |
| IP Allow List | G6_SSE_IP_ALLOW | Restrict clients by IP, else 403 |
| Global Connection Cap | G6_SSE_MAX_CONNECTIONS | 429 + Retry-After:5 when exceeded |
| CORS Origin | G6_SSE_ALLOW_ORIGIN | Sets Access-Control-Allow-Origin |

### Per-IP Connection Rate Limiting
`G6_SSE_IP_CONNECT_RATE` = `N/W` (or `N` for 60s window). Sliding window with stale timestamp pruning + second-chance active handlers check. Rejected -> 429; metric `g6_sse_http_rate_limited_total`.

### User-Agent Allow List
`G6_SSE_UA_ALLOW` comma substrings. Non-match -> 403; metric `g6_sse_http_forbidden_ua_total`.

### Request Correlation
`X-Request-ID` sanitized & echoed for log correlation.

### Metrics (Prometheus Prefix g6_sse_http_)
active_connections, connections_total, disconnects_total, rejected_connections_total, auth_fail_total, forbidden_ip_total, rate_limited_total, forbidden_ua_total, events_sent_total, events_dropped_total, security_events_dropped_total, event_size_bytes (hist), event_queue_latency_seconds (hist), connection_duration_seconds (hist).

### Structured Diff Latency
Structured diff mode (`G6_SSE_STRUCTURED=1`) includes internal `_ts_emit` used for queue latency histogram.

## 4. Shared Helper Extraction
Refactor phases introduced `sse_shared.py` centralizing:
- Phase 1: auth / IP / UA allow / per-IP connection rate limiting / security config resolution.
- Phase 2: event framing (`write_sse_event`) + per-connection token bucket (`allow_event_token_bucket`).
Unified & legacy servers delegate to ensure parity (ordering: 401 -> 403 -> 429; UA precedence maintained).

## 5. Environment Centralization
`SummaryEnv` consolidates: `sse_token`, `sse_allow_ips`, `sse_connect_rate_spec`, `sse_allow_user_agents`, `sse_allow_origin`.
Escape hatch: `G6_SSE_SECURITY_DIRECT=1` to re-read raw env each request (debug only).
Live-tuned vars still read directly: `G6_SSE_MAX_CONNECTIONS`, `G6_SSE_MAX_EVENT_BYTES`, `G6_SSE_EVENTS_PER_SEC`.

## 6. Operational Guidance
1. Set API token, IP allow list, UA allow list for production.
2. Size rate limit window to legitimate reconnection patterns.
3. Monitor `rate_limited_total` / `forbidden_ua_total` for abuse.
4. Scrape `/metrics` from unified server for dashboards.
5. Use heartbeat fields to detect stalled streams in health checks.

## 7. Testing Coverage
Automated tests: auth/ACL, rate limiting, UA filter, shutdown bye, unified endpoints, advanced metrics, diff application, heartbeat classification, event truncation metrics.

## 8. Future Enhancements
- Shared cluster-level limiter.
- Adaptive UA reputation / scoring.
- Snapshot diff hashing for renderer skip.
- Extended panel baseline caching & multi-source aggregation.
- Strict security mode (`G6_SSE_SECURITY_STRICT`).

## 9. Migration / Deprecations
Legacy enable flags removed; SSE auto-active when publisher present. Resync disable flag `G6_DISABLE_RESYNC_HTTP=1` only. Deprecated scripts removed; tests enforce absence.

## 10. Changelog Reference
See CHANGELOG Unreleased entries (SSE shared refactor Phases 1 & 2) for extraction timeline.

_Last consolidated: 2025-10-05._
