# Terminal Dashboard (summary_view) Future Architecture & Health Dossier Roadmap

_Last updated: 2025-09-29_

---
## 0. Current Status (2025-09-29) – Curated Layout Foundation Landed

This addendum captures work completed since the previous revision and sets the jump‑off point for continuing implementation.

### Recently Implemented
| Area | Status | Notes |
|------|--------|-------|
| Curated Terminal Layout (plain) | DONE | Added `src/summary/curated_layout.py` with block priority, shrink‑before‑drop, critical alert protection. Activated by `G6_SUMMARY_CURATED_MODE`. |
| Env Flag Documentation | DONE | `G6_SUMMARY_CURATED_MODE` + deprecation suppression documented (`env_dict.md`). |
| SLA Metric Placeholder Hardening | DONE | Ensures always‑present `cycle_sla_breach` counter; stabilizes metrics tests. |
| Snapshot Builder (Base Scaffold) | PARTIAL | `scripts/summary/snapshot_builder.py` exists with Phase‑1 structure, alert relocation + dedupe, memory tiering via thresholds, initial metrics (histogram + frame counter) and signature hash (PH1‑05). Not yet fully integrated into render pipeline. |
| Thresholds Registry | DONE | `scripts/summary/thresholds.py` centralizes memory tier & DQ thresholds; override mechanism via `G6_SUMMARY_THRESH_OVERRIDES`. |
| Alerts Relocation & Dedupe | PARTIAL | Implemented inside snapshot builder path; legacy path still present when aggregation flag disabled (`FLAG` off). |
| Render Signature (Skip Optimization) | PARTIAL | Signature function implemented; integration into main loop pending (skip counter metric registered). |
| Tests for Curated Layout | DONE | Added pruning, shrink, and critical alert retention tests. |

### Observed Runtime Behavior
| Observation | Impact |
|-------------|--------|
| Many placeholder `?` values in curated output | Upstream status lacks enriched fields (indices_detail, provider diagnostics, dq structure); noise risk. |
| Analytics & Followups blocks sometimes entirely unknown | Consumes vertical space without signal → candidate for conditional omission. |
| Rich (multi‑pane) UI absent in curated mode | Operators lose prior scan ergonomics on wide terminals; reinstatement planned via dual renderer. |

### Immediate Improvements (Short Horizon)
1. Suppress empty/fully unknown optional blocks (Analytics, Followups) when all values unresolved — env‑toggled via `G6_SUMMARY_HIDE_EMPTY_BLOCKS` (default ON when curated).
2. Refactor curated layout to emit neutral BlockSpec objects (presentation‑agnostic) to enable Rich renderer reuse.
3. Implement Rich renderer (`G6_SUMMARY_RICH_MODE`) supporting multi‑column adaptive packing (1–3 columns) using existing priority + shrink semantics.
4. Reorder high‑severity Alerts nearer top in Rich mode when width permits (without breaking shrink contract). 
5. Add minimal status enrichment upstream (fill provider latency / memory stats / dq counts) to reduce placeholders.

### New / Updated Flags (Planned)
| Flag | Purpose | Default |
|------|---------|---------|
| G6_SUMMARY_RICH_MODE | Enable Rich renderer for curated BlockSpecs | Off |
| G6_SUMMARY_HIDE_EMPTY_BLOCKS | Skip optional blocks with only placeholders | On (curated) |
| G6_SUMMARY_MAX_LINES | Hard cap total rendered lines (safety) | unset |
| G6_SUMMARY_THEME | Select color theme (default|mono|high_contrast) | default |

### Updated Roadmap Insert (Rich UI Track)
New ticket group (prefix RICH) added; integrates with existing Phases without blocking Health Dossier evolution.

| ID | Title | Scope Summary |
|----|-------|---------------|
| RICH-01 | BlockSpec Abstraction | Refactor curated layout to produce typed block specs (metadata + semantic rows). |
| RICH-02 | Plain Renderer Adapter | Re-implement existing plain curated output using BlockSpecs (regression neutral). |
| RICH-03 | Rich Renderer (Base) | 1–3 column adaptive layout (header full width + body grid) with Tables / Panels. |
| RICH-04 | Shrink/Prune Integration (Rich) | Map shrink levels to column removals / row truncation; preserve existing priority guarantees. |
| RICH-05 | Alerts Priority Elevation | Allow alerts panel to bubble earlier in wide layouts when severity ≥ WARN. |
| RICH-06 | Hide Empty Blocks Logic | Implement shared helper; respect `G6_SUMMARY_HIDE_EMPTY_BLOCKS`. |
| RICH-07 | Snapshot Integration (Optional) | When snapshot builder flag on, source data from snapshot instead of raw status for specs. |
| RICH-08 | Theming & Style Map | Centralize status→style tokens; theme env var support. |
| RICH-09 | Tests & Snapshots | ANSI‑stripped snapshot tests for both narrow & wide terminals. |

Progress for these tickets will be appended to Section 19 table as they land.

---

This document analyzes the current terminal dashboard (`summary_view`) data & logic flow, identifies inefficiencies / risks, and proposes a multi-phase evolution toward a unified, information‑dense "Health Dossier" model.

---
## 1. Current Data & Logic Flow (Runtime Path)

1. **Entry**: `scripts/summary_view.py:main()` → delegates to `scripts.summary.app.run()`.
2. **Startup**: parses args/env (panels mode, cadence), instantiates `StatusCache` (runtime_status.json with tolerant partial-write behavior).
3. **Sources**: runtime status JSON, panels JSON (`data/panels/*.json`), metrics adapter (optionally), ad‑hoc log parsing fallback.
4. **Loop** (`app.run`): two refresh cadences (meta vs resources); rolling deque for cycle durations (avg + p95); file-change events via optional event bus; builds/refreshes Rich layout.
5. **Panels**: Each panel performs its own data fetch & transformation (indices, alerts, monitoring, storage, links, header). Some duplicate derive logic.
6. **Alerts**: Aggregates central error handler outputs, panel JSON `alerts`, `status['alerts'|'events']`, generated DQ/market alerts, and appends to rolling persistent log the panel itself writes.
7. **Output**: Rich Live loop with render signature heuristic (cycle id + resource fragments) to skip redundant full renders. Plain fallback builds textual summary.

---
## 2. Module Responsibilities Snapshot

| Layer | Module(s) | Role |
|-------|-----------|------|
| IO / Source | `StatusCache`, `scripts.summary.data_source`, `UnifiedDataSource` | File/metrics/panels access + caching |
| Derive helpers | `scripts.summary.derive`, partial duplicates inside `summary_view.py` | Extract cycle, health, provider, market |
| Panel logic | `panels/*.py` | Domain-specific enrichment + presentation |
| Event reactivity | `file_watch_events` + watcher thread | Change detection / early refresh |
| Persistence | Alerts rolling file (written by panel) | Historical alert retention |
| State/trends | Rolling deque (cycle durations) | Minimal temporal context |

---
## 3. Inefficiencies & Weak Links

### Structural
- Derive duplication (two places) → drift risk.
- Panels re-pull sources independently → frame incoherence.
- Alerts panel mixes persistence + rendering concerns.
- Multi-layer fallback precedence (panels → status → metrics → logs) obscures root truth.
- Scattered environment parsing & thresholds; no centralized policy object.

### Performance
- Repeated JSON loads; no atomic snapshot per frame.
- Unoptimized render signature (ignores alerts & many data fields).
- Imports inside hot rendering paths; repeated regex compilation for log parsing.
- Potential redundant refresh churn on bursty file events (no debounce).

### Data Integrity / Robustness
- No schema validation or version tagging for status/panels shapes.
- Partial writes silently masked; no corruption telemetry.
- Snapshot coherence risk: different panels may reflect different cycles.
- Synthetic placeholder values (monitoring panel) might mislead operators.
- Alerts duplication (raw + generated + persisted) without de‑dupe.
- Rolling alerts log lacks rotation / retention policies.

### Observability Gaps
- No composite health score or category matrix.
- No trends (only instantaneous metrics)—no slope/volatility visibility.
- Missing per-domain freshness exposure (staleness side-channel only in some panels).
- Adaptive system signals (detail mode, severity, follow-up weight) partially surfaced, not normalized.
- Root cause hints absent; operator must infer.

### Maintainability
- Color & threshold logic hand-coded across modules.
- Dict-based dynamic shapes (no typed models) hamper safe refactors.
- Temporal calculations duplicated (age, next run).

### Failure Modes
- UnifiedDataSource failure masked by fallback → silent degraded accuracy.
- Event bus optional → environment-specific behavior drift.
- Panel exceptions (if wrappers fail) could degrade full layout.
- Alert flood possibility (no rate/sampling) fills log quickly.

---
## 4. Risk Catalog

| Risk | Impact | Scenario |
|------|--------|----------|
| Snapshot inconsistency | Operator confusion | Indices show cycle N+1 while monitoring shows N |
| Shape drift silent | Wrong rendering | Added status key ignored; thresholds misapplied |
| Stale stream undetected | False confidence | indices_stream frozen, success rate old |
| Alert duplication | Fatigue | Same DQ issue appears 3x from different sources |
| Trend blindness | Delayed mitigation | Memory creep unnoticed until critical tier |
| Fallback opacity | Debug friction | FORCE_DATA_SOURCE pins outdated panel set |
| Partial write persistence | Masked data loss | Truncated runtime_status reused silently |

---
## 5. Target Architecture: "Health Dossier" Layers

1. **Ingestion Aggregator**: Single pass per frame → constructs raw domain inputs (status, panels, metrics) one time.
2. **Normalization**: Validates & transforms into typed `FrameSnapshot` (versioned schema).
3. **Enrichment / Scoring**: Computes category scores (data_quality, timeliness, reliability, resources, adaptive, integrity) + trend stats + anomalies.
4. **Dossier Assembly**: Curated object with: composite score, category scorecards, prioritized issues, sparklines, projections, active adaptive constraints.
5. **Presentation**: Panels become pure views binding to snapshot/dossier (no IO); fine-grained content hash per panel for selective re-render.
6. **Persistence & History**: Rolling in-memory + short NDJSON ring (bounded) for last N snapshots; dedicated controlled alerts log.

---
## 6. Proposed Data Contract (Illustrative)

```json
{
  "ts": "2025-09-27T09:23:14Z",
  "cycle": {"number":1234,"last_duration_s":1.84,"p95_60":2.10,"interval_s":5,"next_eta_s":3.2},
  "indices": {"NIFTY":{"dq":93.4,"dq_trend":-1.2,"legs_cur":640,"legs_cum":48032,"success":98.2,"age_s":1.2,"anomalies":[]}},
  "resources": {"cpu_pct":61.2,"rss_mb":287.4,"mem_tier":1,"rss_trend":"+3.1%/10c"},
  "provider": {"latency_ms":410,"auth_valid":true,"failover_active":false},
  "adaptive": {"detail_mode":"band","severity_counts":{"critical":1,"warn":3},"followup_weight_pressure":0.62},
  "storage": {"csv_files":53,"records":48613,"write_errors":0,"disk_usage_mb":146.5},
  "freshness": {"indices_stream_age_s":1.5,"alerts_age_s":0.9,"status_age_s":0.4},
  "health_scores": {
    "data_quality": {"score":86,"status":"warn","components":[{"metric":"dq_red","value":2,"limit":1}]},
    "timeliness": {"score":92,"status":"ok"}
  },
  "issues": [
    {"id":"dq_degradation","severity":"warn","msg":"DQ down 4.2 pts over 30 cycles; 2 red indices","since_cycle":1208},
    {"id":"mem_pressure_rising","severity":"info","msg":"RSS +11% last 25 cycles; projected tier2 in ~14m"}
  ]
}
```

---
## 7. Scoring Concepts (Examples)

- **Data Quality**:
  `score = 100 - 15*(red/total) - 7*(yellow/total) - trend_penalty` (clamped)
- **Timeliness**:
  `score = 100 - 40*max(0, p95/interval - 1) - staleness_penalty`
- **Resources**:
  `score = 100 + mem_tier_weight[tier] - 0.6*max(0, cpu_pct-70)`

Expose formulas & current components for operator transparency.

---
## 8. Information Density Enhancements

| Feature | Benefit |
|---------|---------|
| Sparklines (cycle, memory, dq) | Rapid trend perception |
| Category Heatmap Row | One-line situational scan |
| Prioritized Issues List | Focus operator attention |
| Projection Chips | Forward risk awareness |
| Freshness Bar | Detect stale domains quickly |
| Unified Severity Badge | Single consistent severity taxonomy |
| Root Cause Drilldown | Accelerated triage |

---
## 9. Robustness Hardening

| Control | Description |
|---------|-------------|
| Atomic snapshot build | All panels view same frame |
| Schema validation & version | Early drift detection |
| Partial write anomaly metric | Surfaced corruption |
| Cache & event debounce | Avoid refresh storms |
| Panel failure isolation | Placeholder + failure counter |
| Safe mode banner | Signals degraded confidence |
| Self metrics (`g6_summary_*`) | Observability of UI itself |

---
## 10. Metrics to Add

| Metric | Type | Purpose |
|--------|------|---------|
| g6_summary_snapshot_build_seconds | Histogram | Snapshot build latency |
| g6_summary_panel_render_seconds{panel} | Histogram | Panel rendering hotspots |
| g6_summary_stale_domains_total{domain} | Counter | Staleness events |
| g6_summary_health_score{category} | Gauge | Export category health |
| g6_summary_issues_total{severity,type} | Counter | Issue emission volume |
| g6_summary_refresh_skipped_total | Counter | Signature-based refresh savings |

---
## 11. Phased Implementation Plan

### Phase 1 (Stabilize)
- Add `snapshot_builder.py` with optional `G6_SUMMARY_AGG_V2` flag.
- Central `thresholds.py` registry for DQ, memory tiers, latency, stream staleness.
- Move alerts persistence into ingestion layer; panels become read-only.
- Enhance render signature (hash of: cycle number, severity counts, alerts total, indices_stream latest timestamp, mem tier).

### Phase 2 (Scoring & Trends)
- Trend buffers (deque, size 60 cycles) for key signals.
- Compute category scores + statuses, expose new Health Matrix panel.
- Add sparklines (Unicode block/Braille) for cycle duration & memory.

### Phase 3 (Issues & Root Cause)
- Anomaly detection (simple z-score / EWMA) for cycle & latency.
- Root cause heuristics (latency vs internal processing vs memory pressure correlation).
- Prioritized Issues panel.

### Phase 4 (Adaptive Integration)
- Surface controller demotion reasons, promotion blocks, follow-up weight progression sparkline.
- Predictive memory breach estimator (linear slope extrapolation).

### Phase 5 (Hardening & Cleanup)
- Schema version gating; legacy code path deprecated.
- Remove duplicate derive logic & legacy panel IO.
- Introduce CLI commands to dump last snapshot / issues (`scripts/dump_summary_snapshot.py`).

---
## 12. Quick Wins (Immediate Value)
- Threshold centralization.
- Freshness line in header: `Fresh: idx 1.5s | alerts 0.8s | status 0.3s`.
- Alerts dedupe + source attribution field.
- Precompiled regex for indices log fallback.
- Trend arrows (⬈ / → / ⬊) for memory & cycle p95.

---
## 13. Migration Strategy
1. Implement V2 snapshot side-by-side, toggle via env.
2. Mirror legacy panel output for parity; add parity test harness.
3. Run dual mode in CI for N cycles; assert structural equivalence or controlled diffs.
4. Switch default after stability window; keep legacy behind `G6_SUMMARY_LEGACY=1`.
5. Remove legacy after two release cycles & doc update.

---
## 14. Open Questions / Future Extensions
- Should health scoring feed back into adaptive controller (closed loop)?
- Introduce operator annotations (acknowledge/ignore issues) persisted locally?
- Export health dossier snapshot via HTTP endpoint `/summary/dossier` for remote dashboards?
- Integrate retention of anomaly root cause chains for post-mortem export.

---
## 15. Risks if Deferred
| Risk | Outcome |
|------|---------|
| Continued duplication | Slower feature velocity, latent bugs |
| Poor trend visibility | Delayed incident detection |
| Alert noise | Operator desensitization |
| Lack of schema validation | Breakage hidden until crisis |
| No scoring standard | Hard to objective-track improvements |

---
## 16. Summary
The current `summary_view` is functional but fragmented. A unified, validated snapshot plus enrichment & scoring layer unlocks consistency, richer operator insight, and future adaptive automation. The proposed phased path delivers early wins (freshness + dedupe) while charting to a complete “health dossier” without a big-bang rewrite.

---
## 17. Actionable Next Steps (Concrete)
1. Add `docs/thresholds_reference.md` + implement `thresholds.py` registry.  
2. Implement `snapshot_builder.py` (V2) returning typed `FrameSnapshot` (dataclass) + feature flag.  
3. Refactor one panel (Alerts) to consume snapshot → validate pattern, replicate.  
4. Add freshness line & trend arrows in header (pull from snapshot).  
5. Add `g6_summary_snapshot_build_seconds` metric.  

---
_Authored automatically as part of dashboard evolution analysis._

---
## 18. Implementation Tickets (Backlog Breakdown)

Legend:
- ID: Stable ticket identifier for tracking (prefix PHx = Phase, CW = Quick Win, HX = Hardening Cross-cutting).
- Flags: New / existing env flags or feature toggles introduced/used.
- Metrics: New metrics emitted or existing ones updated.
- Tests: Minimum required test coverage (add more as organically needed).
- Acceptance: Objective, verifiable criteria for ticket closure.
- Dep: Explicit dependency (must be at least merged to main behind flag if not active).

### Phase 1 – Stabilize & Foundation

| ID | Title | Scope Summary |
|----|-------|---------------|
| PH1-01 | Thresholds Registry | Centralize all dashboard thresholds in `scripts/summary/thresholds.py` + doc ref. |
| PH1-02 | Snapshot Builder (Base) | Implement `snapshot_builder.py` producing raw unified frame (no scoring) under `G6_SUMMARY_AGG_V2`. |
| PH1-03 | Snapshot Build Metric | Add `g6_summary_snapshot_build_seconds` histogram around builder (flag-aware). |
| PH1-04 | Alerts Persistence Relocation | Move alerts collection & persistence out of panel to snapshot build ingestion layer. |
| PH1-05 | Render Signature Enhancement | Add content hash inputs (cycle, severity counts, alerts total, indices ts, mem tier). |
| PH1-06 | Header Freshness & Trend Arrows | Inject freshness line + p95 & memory directional arrows. |
| PH1-07 | Regex Precompile & Cache | Precompile indices log fallback regexes, store module-level. |
| PH1-08 | Alerts Dedupe & Source Attribution | Normalize alert entries with `source` field + dedupe key hash. |
| PH1-09 | Parity Harness (Legacy vs V2) | Add test harness comparing legacy panel-derived vs snapshot builder outputs. |

Detailed Tickets

PH1-01 Thresholds Registry
- Files: add `scripts/summary/thresholds.py`; update panels & builder to import.
- Flags: None (pure refactor).
- Metrics: None.
- Tests: `tests/test_summary_thresholds_registry.py` asserting values load & override via env (e.g., `G6_SUMMARY_THRESH_OVERRIDES` JSON map).
- Acceptance: All prior hard-coded values removed from panels (grep pass), overrides documented in `docs/thresholds_reference.md`.

PH1-02 Snapshot Builder (Base)
- Files: `scripts/summary/snapshot_builder.py` (function `build_frame_snapshot()` returning dataclass `FrameSnapshotBase`).
- Flags: `G6_SUMMARY_AGG_V2` (enables new path but legacy still default); optional `G6_SUMMARY_V2_LOG_DEBUG`.
- Metrics: Build time (placeholder; actual in PH1-03) & count gauge `g6_summary_v2_frames_total` (counter) behind flag.
- Tests: `tests/test_summary_snapshot_builder_base.py` building snapshot with fixture runtime status & panels.
- Acceptance: Snapshot contains coherent single-cycle data (cycle id uniform); passes parity harness structural subset (indices count, mem tier, alerts length).

PH1-03 Snapshot Build Metric
- Files: augment builder to time build; register histogram `g6_summary_snapshot_build_seconds` (buckets tuned later) in metrics registry (group `summary_ui`).
- Flags: Same as PH1-02.
- Tests: `tests/test_summary_snapshot_metrics.py` ensures histogram observed after one build.
- Acceptance: Metric appears with >0 sample; docs updated (`METRICS.md`).

PH1-04 Alerts Persistence Relocation
- Files: move write logic to builder ingestion; refactor `panels/alerts.py` to purely read from snapshot object.
- Flags: Guard relocation under `G6_SUMMARY_AGG_V2`; legacy path untouched.
- Metrics: Add `g6_summary_alerts_dedup_total` counter incrementing when duplicates skipped.
- Tests: `tests/test_summary_alerts_relocated.py` ensuring no file writes triggered by panel import (monkeypatch open) when V2 enabled.
- Acceptance: Alerts panel diff (legacy vs v2) identical modulo ordering; writes occur exactly once per frame.

PH1-05 Render Signature Enhancement
- Files: `scripts/summary/app.py` &/or layout update adding content hash function.
- Flags: `G6_SUMMARY_SIG_V2` (independent toggle for safe rollout; auto-on if builder flag on).
- Metrics: `g6_summary_refresh_skipped_total` increments on skip; baseline before/after skew recorded.
- Tests: `tests/test_summary_render_signature.py` verifying skip when no data change.
- Acceptance: p95 skipped fraction > 30% in simulated unchanged cycles test.

PH1-06 Header Freshness & Trend Arrows
- Files: `panels/header.py` consumes snapshot freshness + trend calculators (temporary simple diff vs previous frame stored globally under flag).
- Flags: Reuse `G6_SUMMARY_AGG_V2` or add `G6_SUMMARY_HEADER_ENH`.
- Metrics: None (optional later freshness metric).
- Tests: `tests/test_summary_header_freshness.py` validating formatting & arrow selection thresholds.
- Acceptance: Header prints line: `Fresh: idx Xs | alerts Ys | status Zs` and arrows for mem & p95.

PH1-07 Regex Precompile & Cache
- Files: `scripts/summary/data_source.py` (module-level compiled patterns) + remove in-loop `re.compile` calls.
- Flags: None.
- Metrics: None.
- Tests: `tests/test_summary_regex_precompile.py` asserts attribute presence & single compile path using monkeypatch counting.
- Acceptance: No dynamic compile on >1 frame (verified in test via counter).

PH1-08 Alerts Dedupe & Source Attribution
- Files: builder ingestion; introduce key fields (type, message, index, severity) hashed; attach `source` attribute (panel,status,event,followup).
- Flags: `G6_SUMMARY_ALERT_DEDUPE`.
- Metrics: `g6_summary_alerts_dedup_total` (shared with PH1-04) increments.
- Tests: `tests/test_summary_alerts_dedupe.py` feeds duplicates; ensures single alert emitted & counter increments.
- Acceptance: Duplicates removed; panel output stable order (secondary sort by ts, type).

PH1-09 Parity Harness
- Files: `tests/test_summary_parity.py`; helper `scripts/summary/parity_harness.py`.
- Flags: Harness active when `G6_SUMMARY_PARITY=1` in tests.
- Metrics: None.
- Tests: Provided harness itself; compare normalized JSON (prune fields ephemeral: timestamps, durations).
- Acceptance: Parity test passes for baseline sample fixtures; diffs enumerated & documented if intentional.

### Phase 2 – Scoring & Trends

| ID | Title | Scope Summary |
|----|-------|---------------|
| PH2-10 | Trend Buffers Infra | Add rolling deques (size configurable) into snapshot state. |
| PH2-11 | Category Scoring | Implement scoring formulas & status mapping. |
| PH2-12 | Health Matrix Panel | New panel rendering category status row & composite score. |
| PH2-13 | Sparklines Utility | Compact sparkline generator (Unicode/Braille) + cycle & memory usage. |

PH2-10 Trend Buffers Infra
- Flags: `G6_SUMMARY_TRENDS`.
- Metrics: Optional `g6_summary_trend_window_size` gauge.
- Tests: `tests/test_summary_trends_buffers.py` verifying fixed length & append ordering.
- Acceptance: Buffers retain last N entries; no memory leak (length constant after overflow).

PH2-11 Category Scoring
- Flags: `G6_SUMMARY_SCORING` (implies trends).
- Metrics: `g6_summary_health_score{category}` gauges.
- Tests: `tests/test_summary_scoring.py` constructing synthetic component counts to hit status transitions (ok→warn→critical boundaries).
- Acceptance: Score changes deterministically with component counts & trend penalties; docs list formulas.

PH2-12 Health Matrix Panel
- Files: `panels/health_matrix.py`.
- Flags: same as scoring.
- Metrics: Panel render seconds part of existing `g6_summary_panel_render_seconds` (added later PHX cross-cutting) or immediate.
- Tests: `tests/test_summary_health_matrix_panel.py` verifying layout & statuses.
- Acceptance: Row shows categories with color-coded statuses & composite.

PH2-13 Sparklines Utility
- Files: `scripts/summary/sparklines.py` utility; integration in header & health matrix.
- Flags: `G6_SUMMARY_SPARKLINES`.
- Metrics: None.
- Tests: `tests/test_summary_sparklines.py` ensuring stable char output for fixed sequence.
- Acceptance: Memory & cycle duration sequences produce expected encoded string.

### Phase 3 – Issues & Root Cause

| ID | Title | Scope Summary |
|----|-------|---------------|
| PH3-14 | Anomaly Detectors | EWMA / z-score for cycle time, provider latency, memory slope. |
| PH3-15 | Issues Prioritization Engine | Rank anomalies & thresholds into issue objects. |
| PH3-16 | Issues Panel & Counters | Panel listing issues; counter metric increments. |
| PH3-17 | Root Cause Heuristics | Map correlated signals (latency vs CPU/mem) with reason codes. |

PH3-14 Anomaly Detectors
- Flags: `G6_SUMMARY_ANOMALY`.
- Metrics: `g6_summary_issues_total{severity,type}` increments when anomaly crosses threshold.
- Tests: `tests/test_summary_anomaly_detectors.py` synthetic sequences triggering z-score > limit.
- Acceptance: Detector fires exactly once per sustained anomaly until resolution criteria met.

PH3-15 Issues Prioritization Engine
- Flags: depends on anomaly.
- Metrics: reuse issues counter; optional gauge `g6_summary_active_issues`.
- Tests: `tests/test_summary_issue_priority.py` mixing anomalies & thresholds to assert ordering (critical first, then warn by recency).
- Acceptance: Issue list sorted; deterministic tie-break by first_seen cycle.

PH3-16 Issues Panel & Counters
- Files: `panels/issues.py`.
- Flags: same as engine.
- Metrics: Panel render instrumentation (see HX metrics ticket) + counters already emitted.
- Tests: `tests/test_summary_issues_panel.py` verifying rendering & severity color mapping.
- Acceptance: Panel shows truncated list (configurable max) with age indicator.

PH3-17 Root Cause Heuristics
- Flags: `G6_SUMMARY_ROOT_CAUSE`.
- Metrics: `g6_summary_root_cause_inferred_total{type}` counter.
- Tests: `tests/test_summary_root_cause.py` create synthetic correlated spikes (latency + CPU) expecting reason code `provider_latency_external`.
- Acceptance: Heuristics produce single top reason per issue when applicable.

### Phase 4 – Adaptive Integration

| ID | Title | Scope Summary |
|----|-------|---------------|
| PH4-18 | Memory Breach Estimator | Linear slope extrapolation for mem tier breach ETA. |
| PH4-19 | Controller Reason Surfacing | Add demotion reasons & promotion blocks to snapshot. |
| PH4-20 | Follow-Up Weight Sparkline | Encode rolling weight window visually. |
| PH4-21 | Unified Severity Badge | Standardize severity badge generation from snapshot state. |

PH4-18 Memory Breach Estimator
- Flags: `G6_SUMMARY_MEM_PROJECTION`.
- Metrics: `g6_summary_mem_breach_eta_seconds` gauge (NaN if stable).
- Tests: `tests/test_summary_mem_projection.py` ascending RSS sequence projecting ETA within tolerance.
- Acceptance: ETA decreases over consecutive growth frames; clears when slope negative.

PH4-19 Controller Reason Surfacing
- Flags: `G6_SUMMARY_CONTROLLER_META`.
- Metrics: None (existing adaptive metrics already cover actions).
- Tests: `tests/test_summary_controller_meta.py` injecting synthetic adaptive states & asserting snapshot fields.
- Acceptance: Snapshot exposes arrays `demotion_reasons`, `promotion_blocks`.

PH4-20 Follow-Up Weight Sparkline
- Flags: reuse `G6_SUMMARY_SPARKLINES` + new sub-flag `G6_SUMMARY_FOLLOWUP_SPARK`.
- Metrics: None.
- Tests: `tests/test_summary_followup_spark.py` ring buffer → sparkline stable output.
- Acceptance: Panel/header displays inline weight progression.

PH4-21 Unified Severity Badge
- Flags: `G6_SUMMARY_SEVERITY_BADGE` (harmonizes with existing adaptive severity envs).
- Metrics: None.
- Tests: `tests/test_summary_severity_badge.py` verifying formatting across zero / active / resolved states.
- Acceptance: Single badge string consumed by header & alerts panel (no duplicate logic).

### Phase 5 – Hardening & Cleanup

| ID | Title | Scope Summary |
|----|-------|---------------|
| PH5-22 | Schema Versioning & Validation | JSON schema + version tag `schema_version` in snapshot. |
| PH5-23 | Derive Duplication Removal | Remove legacy derive helpers; consolidate in builder utils. |
| PH5-24 | Panel IO Purification | All panels pure view; legacy IO paths deleted. |
| PH5-25 | Snapshot Dump CLI | `scripts/dump_summary_snapshot.py` outputs last frame (JSON / pretty). |
| PH5-26 | Legacy Path Deprecation & Removal | Default V2; add deprecation notice; remove legacy flags after window. |
| PH5-27 | Documentation Finalization | Add scoring formulas doc + operator quick reference. |

PH5-22 Schema Versioning & Validation
- Flags: `G6_SUMMARY_SCHEMA_ENFORCE`.
- Metrics: `g6_summary_schema_violation_total` counter.
- Tests: `tests/test_summary_schema_validation.py` invalid field removal triggers violation counter; valid snapshot passes.
- Acceptance: Builder fails (or soft-fails with safe mode) on schema mismatch when flag enabled.

PH5-23 Derive Duplication Removal
- Flags: None.
- Metrics: None.
- Tests: `tests/test_summary_no_derive_duplication.py` greps (via Python) to ensure forbidden function names absent outside builder.
- Acceptance: Only one source of derive helpers remains.

PH5-24 Panel IO Purification
- Flags: Finalize removal; gate by `G6_SUMMARY_LEGACY` for sunset period.
- Metrics: Panel render seconds stable or reduced (<5% regression allowance).
- Tests: `tests/test_summary_panels_pure.py` monkeypatch file open to raise if panel attempts IO.
- Acceptance: No IO attempts from panels under V2 path.

PH5-25 Snapshot Dump CLI
- Flags: None.
- Metrics: None.
- Tests: `tests/test_snapshot_dump_cli.py` invoking script with temp snapshot path; validates JSON fields.
- Acceptance: CLI prints valid JSON & pretty mode with `--pretty`.

PH5-26 Legacy Path Deprecation & Removal
- Flags: Deprecation warning when `G6_SUMMARY_LEGACY=1` used post-switch.
- Metrics: `g6_summary_legacy_usage_total` counter.
- Tests: `tests/test_summary_legacy_deprecation.py` capturing warning emission.
- Acceptance: After grace window config/docs removed; build fails if flag used (final stage).

PH5-27 Documentation Finalization
- Flags: None.
- Metrics: None.
- Tests: `tests/test_env_doc_coverage.py` updated baseline; `tests/test_scoring_doc_examples.py` ensures formula examples parse & compute sample scores.
- Acceptance: All new env vars documented; formulas & operator quick reference present.

### Cross-Cutting / Hardening (Executed in Parallel Where Low Risk)

| ID | Title | Scope Summary |
|----|-------|---------------|
| HX-28 | Self Metrics Suite | Add panel render histogram, stale domain counter, issues counter, refresh skip counter. |
| HX-29 | Event Debounce | Debounce file change events (time or batch coalesce). |
| HX-30 | Panel Failure Isolation | Wrapper adding placeholder + failure counter. |
| HX-31 | Snapshot History Ring | Keep last N snapshots in memory + optional NDJSON ring file. |
| HX-32 | Alerts Log Rotation | Size/time-based rotation & retention policy config. |

HX-28 Self Metrics Suite
- Flags: `G6_SUMMARY_METRICS`.
- Metrics: (all) `g6_summary_panel_render_seconds{panel}`, `g6_summary_stale_domains_total{domain}`, `g6_summary_issues_total{severity,type}`, `g6_summary_refresh_skipped_total`.
- Tests: `tests/test_summary_self_metrics.py` ensures emission after simulated frames.
- Acceptance: Metrics present & documented.

HX-29 Event Debounce
- Flags: `G6_SUMMARY_EVENT_DEBOUNCE_MS` (int ms; 0 disables).
- Metrics: `g6_summary_events_debounced_total` counter.
- Tests: `tests/test_summary_event_debounce.py` fire rapid events -> expect single refresh.
- Acceptance: Burst of 5 events within window triggers 1 refresh.

HX-30 Panel Failure Isolation
- Flags: `G6_SUMMARY_PANEL_ISOLATION`.
- Metrics: `g6_summary_panel_failures_total{panel}` counter.
- Tests: `tests/test_summary_panel_isolation.py` panel raising exception replaced by placeholder text.
- Acceptance: Other panels render normally; failure metric increments.

HX-31 Snapshot History Ring
- Flags: `G6_SUMMARY_HISTORY_SIZE`, `G6_SUMMARY_HISTORY_FILE` (optional path) & `G6_SUMMARY_HISTORY_FILE_MAX_MB`.
- Metrics: `g6_summary_history_pruned_total` counter.
- Tests: `tests/test_summary_snapshot_history.py` ensures ring max length & file prune on size exceed.
- Acceptance: Ring size never exceeds configured; file truncated/rotated safely.

HX-32 Alerts Log Rotation
- Flags: `G6_SUMMARY_ALERT_LOG_MAX_MB`, `G6_SUMMARY_ALERT_LOG_BACKUPS`.
- Metrics: `g6_summary_alert_log_rotations_total` counter.
- Tests: `tests/test_summary_alert_log_rotation.py` simulate size overflow triggers rotation.
- Acceptance: Rotated files count respects backup limit; no data loss beyond discarded oldest.

### Quick Win Tickets (Can Land Early Independently)

| ID | Title | Scope Summary |
|----|-------|---------------|
| CW-01 | Freshness Line (if isolated) | Implement header freshness before full builder (temp source age calc). |
| CW-02 | Trend Arrows Baseline | Simple delta-based arrows using last value cache. |
| CW-03 | Regex Precompile | (Alias PH1-07; can land immediately). |
| CW-04 | Alerts Dedupe Minimal | (Alias PH1-08; early if low risk). |

---
### Dependency Graph (High-Level)
```
PH1-02 → PH1-04/05/06/08/09
PH1-01 → PH2-11 (scoring uses thresholds)
PH2-10 → PH2-11 → PH2-12 → PH2-13
PH2-11 → PH3-15
PH3-14 → PH3-15 → PH3-16 → PH3-17
PH4-19 / PH4-21 depend on PH1-02 + adaptive subsystems (already implemented outside scope)
PH5-22 depends on stable snapshot schema (post PH3)
HX metrics (HX-28) advisable right after PH1-02 for early visibility
```

### Rollout / Flag Strategy
- Default Off Introduction: PH1 builder & signature behind flags; ship incrementally enabling in staging.
- Gradual Merge: Land structural scaffolds (builder, thresholds, metrics) before user-visible UI changes.
- Bake Period: Maintain parity harness in CI until PH3 completion; fail build on divergence beyond allowlisted keys.
- Flag Retirement: After PH5-26, consolidate to `G6_SUMMARY_V2_ONLY` sentinel (if needed) then remove all superseded flags.

### Tracking & Reporting
- Weekly status section appended to this file summarizing completed IDs & next up queue.
- Add lightweight script `scripts/report_summary_progress.py` (future) to parse this section & output progress % (count completed / total).

---
## 19. Ticket Summary Table (Progress Placeholder)

Initially all tickets are OPEN. Update table below as work proceeds.

| Ticket | Status | Notes |
|--------|--------|-------|
| PH1-01 | DONE | Thresholds registry implemented (`scripts/summary/thresholds.py`), docs & tests green. Indices panel migrated to registry. |
| PH1-02 | IN-PROGRESS | Snapshot builder base scaffold (`snapshot_builder.py`) + initial tests added; producing FrameSnapshotBase behind flag. |
| PH1-03 | DONE | Histogram g6_summary_snapshot_build_seconds + counter g6_summary_v2_frames_total implemented, docs & tests passing. |
| PH1-04 | OPEN |  |
| PH1-05 | OPEN |  |
| PH1-06 | OPEN |  |
| PH1-07 | OPEN |  |
| PH1-08 | OPEN |  |
| PH1-09 | OPEN |  |
| PH2-10 | OPEN |  |
| PH2-11 | OPEN |  |
| PH2-12 | OPEN |  |
| PH2-13 | OPEN |  |
| PH3-14 | OPEN |  |
| PH3-15 | OPEN |  |
| PH3-16 | OPEN |  |
| PH3-17 | OPEN |  |
| PH4-18 | OPEN |  |
| PH4-19 | OPEN |  |
| PH4-20 | OPEN |  |
| PH4-21 | OPEN |  |
| PH5-22 | OPEN |  |
| PH5-23 | OPEN |  |
| PH5-24 | OPEN |  |
| PH5-25 | OPEN |  |
| PH5-26 | OPEN |  |
| PH5-27 | OPEN |  |
| HX-28 | OPEN |  |
| HX-29 | OPEN |  |
| HX-30 | OPEN |  |
| HX-31 | OPEN |  |
| HX-32 | OPEN |  |
| CW-01 | OPEN |  |
| CW-02 | OPEN |  |
| CW-03 | OPEN |  |
| CW-04 | OPEN |  |

