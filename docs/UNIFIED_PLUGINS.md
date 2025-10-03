# Unified Summary Plugin Interface

This document describes the OutputPlugin interface used by the unified summary
loop (`scripts/summary/unified_loop.py`) and provides guidance for implementing
and registering new plugins.

## Goals

Plugins enable orthogonal side‑effects (terminal rendering, panels JSON writes,
metrics emission, dossier generation, etc.) without coupling them to the core
loop or duplicating snapshot assembly logic.

## Lifecycle

1. Core loop constructs / reuses a context (status path, refresh interval, env flags)
2. Each iteration:
   - Raw runtime status file (and panel JSONs when enabled) are read
        - (Removed) Legacy `assemble_unified_snapshot` assembler deleted; always use `assemble_model_snapshot`.
   - Plugins are invoked in order with the snapshot
3. Plugins may emit output, persist files, push metrics, etc.

## Interface (current minimal contract)

```python
class OutputPlugin(Protocol):
    name: str  # short identifier
    def setup(self, ctx: LoopContext) -> None: ...  # optional one-time init
    def process(self, snapshot: Any, ctx: LoopContext) -> None: ...  # per cycle
    def shutdown(self) -> None: ...  # optional cleanup
```

`LoopContext` (simplified) provides:
- `status_file`: path to runtime status JSON
- `interval`: refresh interval seconds (float)
- `env`: mapping of relevant env vars captured at startup (may be subset)
- `now()`: callback returning current time (testability)

## Provided Plugins

| Plugin | Purpose |
| ------ | ------- |
| `TerminalRenderer` | Rich / plain textual UI output to terminal |
| `PanelsWriter` | Writes per-panel JSON artifacts (supersedes legacy bridge) |
| `MetricsEmitter` | Pushes counts / gauges to metrics backend |
| `DossierWriter` | Writes consolidated unified snapshot JSON dossier |
| `SSEPanelsIngestor` | Consumes SSE panel events into in-memory overrides (panels_mem) |

## DossierWriter Notes

- Lives at `scripts/summary/plugins/dossier.py`
- Controlled by env vars:
  - `G6_SUMMARY_DOSSIER_PATH`: target JSON file (required for activation)
  - `G6_SUMMARY_DOSSIER_INTERVAL`: seconds between writes (default 15)
- Atomic write (temp file + replace) to avoid partial readers
- Uses `assemble_model_snapshot` (stable model; legacy assembler removed)

## Adding a New Plugin

1. Create a module under `scripts/summary/plugins/` (e.g. `foo_exporter.py`)
2. Implement a class with `name`, `setup`, `process`, and optional `shutdown`
3. Import and append an instance to the plugin list in `scripts/summary/app.py`
4. Keep heavy imports inside methods if optional dependencies (lazy import)
5. Handle exceptions internally – raise nothing (loop should not crash)

Example skeleton:

```python
from scripts.summary.plugins.base import OutputPlugin
from typing import Any

class FooExporter(OutputPlugin):
    name = "foo_exporter"
    def __init__(self, target: str):
        self._target = target
    def setup(self, ctx):
        # open connections, verify target, etc.
        pass
    def process(self, snapshot: Any, ctx):
        try:
            payload = {
                "ts": ctx.now(),
                "indices": [i.name for i in getattr(snapshot, 'indices', [])],
            }
            # write / send payload
        except Exception:
            # swallow to protect loop
            pass
    def shutdown(self):
        pass
```

Register in `scripts/summary/app.py` (simplified):

```python
plugins = [TerminalRenderer(), PanelsWriter(), FooExporter(target="out/foo.json"), DossierWriter()]
```

## Snapshot Model Stability

Downstream plugins must use the versioned model in `src/summary/unified/model.py`.
The legacy adapter (`from_legacy_unified_snapshot`) and legacy assembler have been removed; the
model builder is always active.

See `UNIFIED_MODEL.md` for the canonical field inventory, precedence rules, and
versioning policy. New plugin development should rely only on fields defined
there to minimize break risk.

## Error Handling Philosophy

- Plugins must never raise; wrap logic in try/except
- Prefer incremental / idempotent writes
- Use atomic replace for file outputs

## Future Enhancements (Deferred)

- Event-driven incremental diff application (SSE/WebSocket) feeding snapshot assembly
    - (Initial SSEPanelsIngestor implemented; pending: reconnect backoff, auth headers, metrics) 

## Metrics (Instrumentation)

Enable unified metrics with `G6_UNIFIED_METRICS=1`. When enabled and `prometheus_client` is installed, the following metric families are exported:

Core loop (MetricsEmitter):
- `g6_unified_cycle_total` (Counter)
- `g6_unified_cycle_duration_seconds` (Histogram)
- `g6_unified_snapshot_build_seconds` (Histogram)
- `g6_unified_plugin_process_seconds{plugin="..."}` (Histogram)
- `g6_unified_plugin_exceptions_total{plugin="..."}` (Counter)
- `g6_unified_panels_write_seconds` (Histogram)
- `g6_unified_render_seconds` (Histogram)
- `g6_unified_conflict_detected` (Gauge)
- `g6_unified_last_cycle_timestamp` (Gauge)
- `g6_unified_errors_total` (Counter)

SSE ingestion:
- `g6_sse_events_total` (Counter) – total SSE events (panel updates) observed
- `g6_sse_panel_generations_total` (Counter) – in-memory panel generations applied
- `g6_sse_ingest_errors_total` (Counter) – SSE processing failures
- `g6_sse_snapshot_build_seconds` (Histogram) – time to rebuild unified snapshot with in-memory panels
- `g6_sse_apply_full_total` (Counter) – full panel replacements applied
- `g6_sse_apply_diff_total` (Counter) – diff merges applied

All metrics registration is best-effort; absence of `prometheus_client` or env gate disables silently.
- Structured metrics hooks with typed schema
- Plugin enable/disable via config file instead of static list
- Pluggable IO abstraction for remote storage targets

## Testing Recommendations

- Provide small unit tests calling `process` with a fabricated snapshot dataclass
- Validate: output file present, metrics counters incremented, etc.
- Use dependency injection (pass writer function) to avoid filesystem in tests

## Changelog

- v1 (current): Initial documentation covering core contract & existing plugins.

## Migration Phases Toward UnifiedStatusSnapshot

Phase | State | Notes
----- | ----- | -----
1 | Bridge (complete) | Plugins consumed SummarySnapshot only.
2 | Dual emission (ACTIVE) | Loop now attaches `snapshot.model` (UnifiedStatusSnapshot) each cycle; plugins may opt-in.
3 | Model primary (planned) | Plugins must prefer model; dict fields retained but deprecated in docs.
4 | Model only (future) | Remove dict fields; version bump & migration notes.

## Planned Roadmap Additions

Item | Description | Target Phase
---- | ----------- | -----------
Diff merge helper | IMPLEMENTED: `merge_panel_diff` in `src/web/dashboard/diff_merge.py` with unit tests | 2
Rolling stats plugin | DossierWriter consumes incremental stats (p95 latency, error streaks) using model extension fields | 3
WebSocketBroadcaster | Replaces SSE ingestion; supports both full + diff messages with classification metrics | 3
Plugin scheduling | Optional `interval_sec` metadata allowing staggered heavy plugins | 3

## Deferred / Open Questions

- Whether to expose partial model updates (diffs) directly to plugins or always supply a full fresh model each cycle.
- Consolidation of panels hashing logic into a reusable util for PanelsWriter & future integrity auditing plugin.
- Standardization of error classification tags per plugin for better observability dashboards.

---
Document updated: Unified model consolidation notes appended (2025-10-01).
