# Panels Bridge + Summary Loop Unification Design

Status: Draft (Phase 0 – Architecture)  
Author: Copilot AI (assisted)  
Date: 2025-10-05  
Related Cleanup Wave: Post-Wave consolidation (bridge retirement path)  

## 1. Executive Summary
The legacy `status_to_panels.py` bridge ("bridge") converts a monolithic runtime status JSON into discrete panel JSON artifacts (atomic per-cycle updates + gated `indices_stream` append). The unified summary path (`scripts/summary/app.py` + `UnifiedLoop`) already:
- Reads status (or ingests SSE panel/full + diff events)
- Renders terminal UI (Rich or plain)
- Writes panels via `PanelsWriter` plugin (transactional snapshot capability)
- Publishes SSE + optional metrics + dossier snapshots

Residual gap: The legacy bridge enforces stream cadence gating (`indices_stream` append only on cycle/minute boundaries) and emits a lightweight heartbeat into the `system` panel. Some consumers/tools still rely on the legacy bridge invocation sequencing (e.g., simulator scripts chaining simulator -> bridge -> summary). This design unifies remaining semantics inside the unified loop plugin layer and defines a deprecation/removal path for the standalone bridge script.

## 2. Scope & Non‑Scope
In Scope:
- Fold `indices_stream` gating & append semantics into unified architecture
- Adopt atomic multi-panel publish semantics uniformly (already partially present via `PanelsWriter.begin_panels_txn`)
- Provide system heartbeat + gating state persistence (previously `.indices_stream_state.json` file) through unified path
- Introduce feature flag + shadow validation path to ensure no functional regressions
- Define metrics & observability for parity verification
- Provide migration & rollback procedure

Out of Scope (future / separate tasks):
- Web dashboard frontend adjustments to read new meta fields
- Removal of any last unused fields from panel JSON schemas
- Streaming bus / SSE diff algorithm refinements
- Index coverage analytics refactor

## 3. Current State Analysis
### 3.1 Legacy Bridge Responsibilities
| Responsibility | Mechanism | Notes |
|----------------|-----------|-------|
| Transactional multi-panel write | `router.begin_panels_txn()` context | Falls back to non-txn path if unavailable |
| Build per-panel payloads | `build_panels(reader,status)` | Central factory already reused elsewhere |
| indices_stream gating | Global `_LAST_STREAM_CYCLE` + `_LAST_STREAM_BUCKET`, persisted to `.indices_stream_state.json` | Gate modes: auto/cycle/minute |
| Append stream entries | `build_indices_stream_items` + optional `time_hms` derivation | Cap = 50 items |
| Heartbeat | Emits `system` panel patch with `bridge.last_publish` ISO ts | Used for freshness checks |
| Backoff handling | Sleep/retry with optional WARN system panel entry | Unified loop already has backoff for errors |
| Deprecation barrier | `_maybe_warn_deprecated` (blocks unless override env) | Enforces migration urgency |

### 3.2 Unified Loop & Plugins
- Snapshot model assembly + domain snapshot + panel hash computation.
- `PanelsWriter` writes panels each cycle (currently without indices_stream gating & heartbeat replication).
- SSE ingestion plugin provides real-time panel diffs / full snapshots to terminal – already central state store.
- Metrics plugin exposes unified cycle/build/plugin duration histograms.

### 3.3 Gaps vs Bridge
| Gap | Needed Action |
|-----|---------------|
| indices_stream gating absent | Add gating state & logic inside new plugin (or extend PanelsWriter) |
| Stream state persistence file | Provide same `.indices_stream_state.json` semantics (read/write once) |
| Heartbeat emission (system.bridge.last_publish) | Inject into system panel output each cycle (or only on successful publish) |
| Gate mode env flags (`G6_STREAM_GATE_MODE`) | Continue honoring for backward compatibility, document migration |
| Backoff WARN injection | Not strictly required (loop errors already tracked); optional WARN metric |

## 4. Target Architecture
### 4.1 Component Diagram (ASCII)
```
+------------------+      +--------------------+
| Runtime Status   |-->-->| UnifiedLoop        |
| (file / SSE)     |      |  _build_snapshot() |
+------------------+      +---------+----------+
                                      |
                 Plugins (process order)------------------------------
                                      v
          +--------------+  +----------------+  +----------------+  +----------------+
          | PanelsWriter |  | StreamGater (*)|  | SSEPublisher   |  | MetricsEmitter |
          +------+-------+  +--------+-------+  +--------+-------+  +--------+-------+
                 |                    |                   |                   |
        panels_dir/*.json    indices_stream gating   SSE events          Prom metrics
                                 & heartbeat
```
(*) New specialized plugin (or merged into PanelsWriter as an extension hook). Preferred: separate `StreamGater` for separation of concerns & simpler testing.

### 4.2 Data Flow
1. UnifiedLoop builds `SummarySnapshot` (includes raw status + domain + panel hashes).
2. `PanelsWriter` writes base panels (provider, resources, loop, indices, adaptive_alerts, etc.) inside a txn.
3. `StreamGaterPlugin` executes after base write:
   - Loads or lazily initializes gating state (cycle, bucket).
   - Derives current cycle & bucket (reuse bridge helper logic adapted to snapshot/domain object).
   - Decides append vs skip per same gate-mode logic.
   - On append: build stream items (reuse `build_indices_stream_items` via a lightweight reader adapter fed with already-built snapshot status) + derive `time_hms` field.
   - Updates gating state in memory & persists to `.indices_stream_state.json` only when state changes.
   - Emits heartbeat patch to `system` panel (atomic: uses `PanelsWriter.begin_panels_txn` again OR arranges ordering: Option A: `PanelsWriter` exposes panel update API inside same initial txn via delegation; Option B: plugin opens a new short txn. Chosen: Option A via hook to avoid double fs sync).
4. MetricsEmitter observes plugin durations including gater; exposes mismatch counters.

### 4.3 Interfaces / Contracts
| Interface | Inputs | Outputs | Errors |
|----------|--------|---------|--------|
| StreamGaterPlugin.process | `SummarySnapshot` | Appends to `indices_stream` panel file (atomic) + heartbeat update | Captures exceptions, logs, does not raise (loop continues) |
| Gating State Storage | cycle:int? bucket:str? | Persist JSON file `.indices_stream_state.json` | Missing/partial file tolerated |

### 4.4 Env Flags & Configuration
| Flag | Current Meaning | Target State |
|------|-----------------|--------------|
| G6_STREAM_GATE_MODE | auto/cycle/minute | Retain; document deprecation notice once parity proven |
| G6_ALLOW_LEGACY_PANELS_BRIDGE | Temporary unblock legacy script | Will be removed after Phase 3 |
| G6_SUPPRESS_DEPRECATIONS / G6_PANELS_BRIDGE_SUPPRESS | Generic suppression | Remains generic; script removal renders specialized one moot |

## 5. Implementation Plan (Final State)
The phased rollout (Phases 1–4) concluded on 2025-10-05. The historical flag-driven activation path has been removed; the `StreamGaterPlugin` is now always active in the unified summary loop immediately after the `PanelsWriter` plugin.

Current (authoritative) behaviors:
* Unconditional gating & heartbeat emission (no opt-in / opt-out flags).
* State persisted in `.indices_stream_state.json`; corruption triggers transparent rebuild + error counter increment.
* Metrics emitted: `g6_stream_append_total`, `g6_stream_skipped_total`, `g6_stream_state_persist_errors_total`, `g6_stream_conflict_total`, plus gate mode info gauge.
* Conflict metric should remain at 0 (legacy bridge permanently removed / tombstoned).

Removed concepts:
* Flags `G6_UNIFIED_STREAM_GATER`, `G6_DISABLE_UNIFIED_GATER`, `G6_ALLOW_LEGACY_PANELS_BRIDGE`.
* Parity shadow comparison harness (no longer needed; final diff window closed).
* Menu/script chain invoking legacy bridge.

Migration Guidance (post-removal): No action required for consumers; any existing environment settings for the retired flags are ignored with a one-time warning until Phase 5 cleanup removes the warning branch.

Upcoming (Phase 5 cleanup): excise warning path & transitional normalization shim once logs confirm zero external usage of retired flags for 5 business days.

## 6. Testing Strategy
| Test Type | Coverage |
|----------|----------|
| Unit | Gater cycle gating, bucket fallback, heartbeat emission, metrics counters, state persistence read/write, append cap enforcement |
| Integration | UnifiedLoop with PanelsWriter + Gater plugin executing N cycles with synthetic status file (assert indices_stream length progression) |
| Parity (Optional) | Run legacy bridge once per cycle, capture indices_stream vs plugin result (excluding time_hms minor formatting) |
| Governance | Ensure no legacy script invocation in menus / tasks after Phase 3 |

Edge Cases:
- Missing status fields (`loop.cycle` absent): fallback to minute bucket gating.
- Corrupted state file: ignore and rebuild state; increment `g6_stream_state_persist_errors_total`.
- Rapid cycle increments (missed writes): plugin compares last seen cycle; multi-skip increments skipped counter.
- Timezone formatting fallback if helper missing.

## 7. Metrics Specification
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_stream_append_total | Counter | mode | Successful indices_stream append events |
| g6_stream_skipped_total | Counter | mode, reason | Skip decisions (same_cycle, same_bucket, error) |
| g6_stream_gate_mode_info | Gauge | mode | Set to 1 for active gate mode |
| g6_stream_state_persist_errors_total | Counter |  | State file write failures |
| g6_stream_conflict_total | Counter |  | Both legacy bridge + plugin detected writing concurrently |

## 8. Open Questions
1. Should heartbeat include previous cycle number? (Proposed: add `cycle` inside `bridge.last_publish`.)
2. Do downstream consumers rely on bridge system panel being a merge vs overwrite? (Need verification; propose merge semantics via PanelsWriter partial update API.)
3. Should gating state move into a unified metadata panel instead of hidden file? (Deferred.)

## 9. Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|-----------|
| Divergent gating semantics | Duplicate or missing stream entries | Parity unit tests + shadow mode comparison |
| Legacy script concurrently active | Race & conflicting append order | Conflict detection metric, warn log, optional lock file in panels dir |
| State file corruption | Loss of gating memory, burst of entries | Graceful fallback + skip reason metric |
| Performance regression (extra IO) | Longer loop cycles | Measure plugin duration via MetricsEmitter; optimize by reusing snapshot data |

## 10. Rollback Strategy (Current)
Given bridge code removal and stable metrics, rollback is limited to a full version revert. Reintroducing flags is explicitly out-of-scope; any diagnostic gating would use a fresh, time-boxed env name if ever required.

## 11. Historical Timeline (Condensed)
| Phase | Date | Outcome |
|-------|------|---------|
| 1 | 2025-10-05 | Plugin introduced under opt-in flag; tests + metrics landed |
| 2 | 2025-10-05 | Default-on; opt-out flag added; conflict metric 0 |
| 3 | 2025-10-05 | Legacy bridge tombstoned; docs updated |
| 4 | 2025-10-05 | Flags retired; unconditional gating |
| 5 (planned) | 2025-10-20 | Remove warning + shim (pending quiet period) |

## 12. Current Action Items
* Monitor logs for retired flag warning emissions (expect zero).
* Prepare Phase 5 PR: remove warning branch + normalization shim; regenerate metrics catalog.
* Append Operator Manual appendix with final gating operational notes.

---
Historical phased details removed for brevity; see version control history prior to this edit if full rollout narrative is required.

## 13. Future Enhancements (Backlog)
- Replace state file with single composite `panels_meta.json` (transactional) for all meta (hashes, generation, gating state).
- Expose unified HTTP endpoint to query recent indices_stream events (memory + FS hybrid).
- Diff-based stream compaction to reduce panel churn.

## 14. Appendix – Pseudocode Sketch
```python
class StreamGaterPlugin(OutputPlugin):
    name = "stream_gater"
    def __init__(self):
        self.state = {"cycle": None, "bucket": None}
        self.loaded = False
    def setup(self, ctx):
        self.panels_dir = ctx.get('panels_dir')
    def _load_state(self):
        if self.loaded: return
        path = os.path.join(self.panels_dir, '.indices_stream_state.json')
        try:
            with open(path,'r',encoding='utf-8') as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                self.state['cycle'] = obj.get('last_cycle')
                self.state['bucket'] = obj.get('last_bucket')
        except Exception:
            pass
        self.loaded = True
    def process(self, snap: SummarySnapshot):
        if not os.getenv('G6_UNIFIED_STREAM_GATER'): return
        self._load_state()
        status = snap.status or {}
        cur_cycle = derive_cycle_number(status)  # helper
        cur_bucket = derive_minute_bucket(status)  # helper
        mode = (os.getenv('G6_STREAM_GATE_MODE','auto').lower() or 'auto')
        should_append = True
        if mode in ('auto','cycle') and isinstance(cur_cycle,int):
            should_append = (self.state['cycle'] != cur_cycle)
        elif mode in ('auto','minute','bucket') and isinstance(cur_bucket,str):
            should_append = (self.state['bucket'] != cur_bucket)
        if not should_append:
            inc_metric('g6_stream_skipped_total', {'reason':'no_change','mode':mode})
            return
        for item in build_indices_stream_items_like(status):
            decorate_hms(item)
            panels_api.append_stream('indices_stream', item)
        self.state['cycle'] = cur_cycle or self.state['cycle']
        self.state['bucket'] = cur_bucket or self.state['bucket']
        persist_state(self.state)
        emit_heartbeat(cur_cycle)
```

---
End of design.
