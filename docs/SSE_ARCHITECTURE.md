# SSE Ingestion Architecture (Unified Summary Loop)

## Goals
- Decouple network event ingestion (Server-Sent Events) from rendering logic.
- Provide a single authoritative in-memory state for panels + severity/followup alerts.
- Offer stable diagnostic / heartbeat metadata to renderers without tight coupling.
- Support incremental diff application with generation safety checks.

## Components

### 1. `PanelStateStore`
Thread-safe store that owns:
- Latest `panel_full` baseline status (deep copied on apply)
- Incrementally merged `panel_diff` updates (via `merge_panel_diff` helper or fallback)
- Counters: `panel_full`, `panel_diff_applied`, `panel_diff_dropped`
- Severity info: `severity_counts`, `severity_state`
- Follow-up alerts (bounded list, newest first)
- Heartbeat timestamps: last *any* event, last full, last diff
- Generation fields: server generation (from events), UI generation (local monotonic)
- Freshness evaluation (`heartbeat()`): returns health classification `init|ok|warn|stale` with configurable thresholds.

### 2. `SSEPanelsIngestor` Plugin
- Background daemon thread performing a minimal SSE loop using `urllib`.
- Parses events: `panel_full`, `panel_diff`, `severity_state`, `severity_counts`, `followup_alert`.
- Updates the `PanelStateStore` via narrow mutation APIs.
- Injects enrichment during `process()` into the snapshot's mutable `status` dict:
  - `panel_push_meta.sse_events` (counters)
  - `panel_push_meta.panel_generation` (if known)
  - `panel_push_meta.sse_heartbeat` (last timestamps + health)
  - `adaptive_stream.severity_counts`, `adaptive_stream.severity_state`, `adaptive_stream.followup_alerts`
  - `panel_push_meta.need_full` if the store marks a baseline required

### 3. Render Loop (`summary_view` / Unified Loop)
- No longer interprets raw SSE events directly.
- Reads centralized snapshot from store when present and renders.
- Gains heartbeat/severity/followups automatically via injected fields.

## Event Flow
1. SSE line block completes (blank line delimiter).
2. JSON payload parsed; `type` + `payload` extracted.
3. Store mutation method invoked.
4. On next render cycle, plugin `process()` runs and enriches snapshot.
5. Renderers / writers consume consistent diagnostics and data.

## Heartbeat & Staleness
- Each successful mutation records a `last_event_ts`.
- Separate timestamps kept for `panel_full` and `panel_diff` (enables diagnosing missing full refreshes).
- `heartbeat(warn_after=10, stale_after=30)` returns:
  ```json
  {
    "last_event_epoch": 1690000000.0,
    "last_panel_full_epoch": 1690000000.0,
    "last_panel_diff_epoch": 1690000005.5,
    "stale_seconds": 5.5,
    "health": "ok",
    "warn_after": 10.0,
    "stale_after": 30.0
  }
  ```
- Plugin compresses keys when embedding: `last_evt`, `last_full`, `last_diff`, `stale_sec`, `health`.

## Generation Safety
- `panel_diff` dropped if incoming `generation` mismatches stored generation.
- Drop increments `panel_diff_dropped` and sets `need_full=True` causing UI/requestor to expect a baseline refresh.

## Follow-up Alerts Handling
- Normalized to a uniform dict: `{time, level, component, message}`.
- Inserted at head; truncated to max length (default 50) for bounded memory.

## Testing
- Unit tests cover diff semantics and severity/followup storage.
- Integration test (`tests/test_sse_integration.py`) simulates full lifecycle and heartbeat staleness classification.

## Extensibility Guidelines
- New event types: add branch in `_dispatch_event` and corresponding mutation method.
- Keep mutation methods narrow and side-effect free beyond internal state changes.
- Avoid storing derived UI-only artifacts; derive on demand in renderers.

## Failure & Resilience
- SSE loop employs exponential backoff (1s → 30s) on network errors.
- Merge failures or malformed payloads increment dropped counters without crashing thread.
- Metrics (if `G6_UNIFIED_METRICS` enabled) track event counts, errors, and apply latency.

## Rationale
Centralizing state reduces branching complexity in render code, enables consistent diagnostics across multiple outputs, and isolates network complexity. The heartbeat design provides operational visibility (is the stream active? are diffs flowing?) without extra log parsing.

## Next Opportunities
- Expose explicit `request_full()` method to proactively schedule baseline refresh.
- Add Prometheus gauge for staleness classification.
- Introduce snapshot diff hashing to avoid redundant renderer work.
- Support multi-source aggregation (multiple SSE endpoints) via composite stores.
