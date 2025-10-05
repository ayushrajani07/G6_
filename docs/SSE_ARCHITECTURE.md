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
# SSE Ingestion Architecture (Unified Summary Loop)

> Moved: This content is now consolidated in `docs/SSE.md` (Section 2: Architecture Overview).

This file is retained as a stub for backward compatibility and will be removed in a future cleanup wave once external references are updated.

See: `SSE.md`
- `heartbeat(warn_after=10, stale_after=30)` returns:
