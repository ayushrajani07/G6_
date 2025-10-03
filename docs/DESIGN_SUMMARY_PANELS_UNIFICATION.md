# Summary & Panels Bridge Unification Design

_Last updated: 2025-09-30_

## 1. Problem Statement
We currently run two cooperating processes for operator telemetry:
Historical (pre-unification) architecture used two processes:
1. Legacy bridge (`scripts/status_to_panels.py`): read `runtime_status.json`, derived & wrote panel JSON artifacts.
2. Summary UI (`scripts/summary_view.py`): rendered terminal view, optionally reading those panel files.

Current (unified) architecture eliminates the external bridge; a single process builds a `SummarySnapshot` then plugins (PanelsWriter, TerminalRenderer, MetricsEmitter) consume it.

Costs of the split:
- Double IO: status file is parsed separately by both processes every refresh (amplified under short cadences).
- Race / freshness ambiguity: summary may momentarily lag panel JSON writes or read partially-written files (mitigated by resilience heuristics but still complexity).
- Operational orchestration overhead: users (and VS Code tasks) start/stop multiple loops.
- Duplicate derivation logic: certain metrics / transformations appear in both code paths (e.g., provider health summarization, adaptive alerts condensation, per-index analytics).

## 2. Goals & Non‑Goals
Goals:
- Single event loop (or structured scheduler) performing: status ingest -> enrichment -> snapshot -> (optional) panels export -> terminal render.
- Eliminate redundant parsing of status & panel JSON.
- Uniform in-memory snapshot abstraction ("Dossier") consumed by renderers and exporters.
- Enable pluggable outputs (terminal, JSON panels, metrics adapters) with consistent lifecycle (init/start/stop hooks).
- Preserve current CLI ergonomics; minimal flag churn.

Non-Goals (Phase 1):
- Building a network (SSE/WebSocket) push layer (can follow; design should not preclude).
- Changing panel JSON schema (avoid a compatibility shock first pass).
- Rewriting Rich layout extensively (only adapt data sourcing layer).

## 3. Proposed Architecture
Core concepts:
- SnapshotBuilder: existing `scripts/summary/snapshot_builder.py` evolves into a reusable producer returning an immutable `SummarySnapshot` dataclass (status core + derived analytics + adaptive signals + per-index panels content + timestamps + anomalies list).
- Output Plugins: each output implements interface:
  ```python
  class OutputPlugin(Protocol):
      name: str
      def setup(self, ctx: Context) -> None: ...
      def process(self, snap: SummarySnapshot) -> None: ...  # may raise RecoverableError
      def teardown(self) -> None: ...
  ```
  Built-ins: TerminalRenderer (Rich/Plain), PanelsWriter (writes JSON artifacts), MetricsEmitter (optional), LogExporter (structured debug), Future: SSEBroadcaster.
- Orchestrator Loop (UnifiedLoop): single async (or sync + timed sleep) loop performing:
  1. Read + validate status (and any direct metrics sources) once.
  2. Build snapshot (derivations in-memory).
  3. Sequentially invoke enabled outputs' process().
  4. Track processing time / backpressure; adapt sleep to honor target cadence.

### Data Flow (Unified)
```
runtime_status.json -> SnapshotBuilder -> SummarySnapshot -> [TerminalRenderer]
                                                       -> [PanelsWriter]
                                                       -> [MetricsEmitter]
```

### Threading Model Options
| Option | Description | Pros | Cons | Recommendation |
|--------|-------------|------|------|----------------|
| Single-thread sync loop | Current pattern extended | Simple, deterministic ordering | Long render or IO blocks next cycle | Phase 1 choice (fast enough) |
| Asyncio loop + awaitable plugins | Use asyncio; plugins can perform non-blocking IO | Better concurrency for slow panel writes | Complexity; Rich isn't fully async | Evaluate after profiling |
| Worker thread for heavy exporters | PanelsWriter offloaded to thread | Avoid UI jank when JSON large | Concurrency safety for snapshot copy required | Possible Phase 2 |

## 4. Migration Strategy
Historical Phases (for context):
- Phase 0–2: Dual-process pattern & experimental unified loop.
- Phase 3: Default flip to unified.
- Phase 4: Bridge stubbed (current) – pending deletion.

## 5. Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Longer cycle time when both render & JSON writes happen | Stale UI / missed cadence | Measure per-plugin latency; if total > target, downgrade panel write frequency (every Nth cycle) or thread offload. |
| Snapshot mutation by plugins causing inconsistent state | Data races / incorrect views | Treat `SummarySnapshot` as frozen (dataclass(frozen=True)); plugins receive copies or read-only view. |
| Partial writes of panel JSON under unified process | Corrupted downstream consumers | Continue atomic write pattern: write to temp file + rename. |
| Error in one plugin halts all outputs | Reduced observability | Wrap each plugin invocation; log + metrics; continue unless error classified fatal (config toggle). |
| Conflict when old bridge still running | Double writes / churn | Lock file or panels directory sentinel detection; warn & skip PanelsWriter unless forced. |
| Adoption drag (operators keep using old two-process habit) | Slow consolidation | Gate new improvements (latency metrics, advanced scoring) behind unified path to incentivize switch. |

## 6. Interfaces & Types
```python
@dataclass(frozen=True)
class SummarySnapshot:
    status: dict
    derived: dict  # provider health, anomalies, cycle stats
    panels: dict   # keys -> panel model objects or serializable dicts
    ts_read: float
    ts_built: float
    cycle: int
    errors: list[str]
```

Plugin contract (initial sync version):
```python
class BaseOutputPlugin:
    name = "base"
    def setup(self, ctx: Context) -> None: ...
    def process(self, snap: SummarySnapshot) -> None: ...
    def teardown(self) -> None: ...
```
Context contains config, logger, metrics emitter.

## 7. Backward Compatibility
- Existing CLI without `--unified` behaves identically (continues to optionally read panel JSON if present).
- `scripts/status_to_panels.py` unchanged until Phase 3; docs mark unified mode as experimental.
- Panel JSON schema unchanged Phase 1–2.

## 8. Testing & Parity
New tests:
- `tests/test_unified_summary_parity.py`: generate simulated status cycles; run (a) bridge + summary (legacy) vs (b) unified with `--write-panels`; assert:
  - For each panel name: structural keys match; allow tolerated numeric drift via threshold.
  - Terminal aggregated counts (provider health, anomalies) match.
- Latency budget test: ensure single cycle duration < 2x legacy average (configurable threshold).

## 9. Metrics Additions
- `unified_loop_cycle_duration_seconds` (histogram)
- `unified_plugin_latency_seconds{plugin="terminal"}` (histogram)
- `unified_plugin_errors_total{plugin=...,type=...}` (counter)
- `unified_panels_conflict_total` (counter) when legacy bridge detected.

## 10. Rollout Criteria
Flip default when:
- Parity test passes for 7 consecutive CI runs.
- p95 cycle duration with panels writer enabled < 1.5 * legacy baseline.
- No critical operator feedback issues open for > 1 week.

## 11. Decommission Checklist (Panels Bridge) – Status
All active runtime references removed; deletion issue open. Remaining task: delete stub + detection helpers after external confirmation window.

## 12. Future Extensions
- SSE / WebSocket broadcaster plugin using same snapshot.
- Adaptive scoring plugin producing an operator risk score panel.
- Panel write frequency decoupled (e.g., every N cycles) via plugin scheduler.
- Dynamic plugin enable/disable at runtime (hot reload).

## 13. Open Questions
- Should panel JSON writing be transactional across all panels (bundle write)? (Leaning: keep per-panel atomic writes for isolation.)
- Is asyncio required or can phase 1 remain synchronous? (Profile after prototype.)
- Need a minimal schema version annotation inside panel JSON to smooth future migrations.

---
Author: (auto-generated draft)
Pending Review: core maintainers.
