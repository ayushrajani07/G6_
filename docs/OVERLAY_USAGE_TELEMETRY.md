# Overlay Usage Telemetry Plan

_Last updated: 2025-09-30_

Purpose: Establish lightweight, low-cardinality instrumentation and logging for the niche overlay feature set (weekday aggregation + plotting) so we can make an evidence-based decision next cleanup wave: retain, refactor, or remove.

## Goals
| Goal | Detail | Success Signal |
|------|--------|----------------|
| Measure real usage | Count invocations of overlay batch + plotting scripts | Non-zero sustained counts across >=2 weeks |
| Detect output relevance | Count generated master CSV + HTML artifacts | Growth or steady regeneration cadence |
| Track failures | Categorize errors (I/O, parse, config) | Low error ratio (<1% invocations) |
| Bound telemetry overhead | Avoid large cardinality / heavy histograms | Single-digit metric family count |
| Provide removal criteria | Explicit numeric thresholds for deprecation vs retention | Decision documented and reproducible |

## Scope (Initial Phase)
Instrument these scripts:
- `scripts/weekday_overlay.py` (EOD aggregation) — mode: `aggregate`
- `scripts/plot_weekday_overlays.py` (HTML plot) — mode: `plot`
- `scripts/generate_overlay_layout_samples.py` (synthetic demo) — mode: `sample` (optional; counts separately)

Utilities that may emit telemetry indirectly:
- `src/utils/overlay_plotting.py`
- `src/utils/overlay_quality.py`

## Metric Design
All metrics grouped under a new logical group: `overlay_usage` (respects existing ENABLE/DISABLE gating). Low cardinality labels only.

| Metric | Type | Labels | Description | Rationale |
|--------|------|--------|-------------|-----------|
| `g6_overlay_usage_invocations_total` | Counter | `script`, `mode` | Total script entry invocations | Core usage volume |
| `g6_overlay_usage_success_total` | Counter | `script`, `mode` | Successful completions | Distinguish failures |
| `g6_overlay_usage_errors_total` | Counter | `script`, `mode`, `etype` | Error occurrences by category | Aid triage |
| `g6_overlay_usage_outputs_total` | Counter | `script`, `otype` | Produced output artifacts (e.g. `master_csv`, `html`, `sample_html`, `quality_report`) | Output significance |
| `g6_overlay_usage_last_run_unixtime` | Gauge | `script` | Unix time of last successful run | Staleness detection |
| `g6_overlay_usage_last_duration_seconds` | Gauge | `script` | Wall time of last successful run | High-level perf trend |

Optional (Phase 2, only if needed):
- Histogram of durations (likely not required; rely on simple gauge + external logs first).

## Error Type Enumeration
`etype` label allowed values (fixed small set):
- `io` (file not found / read / write)
- `parse` (CSV parse / JSON parse)
- `config` (invalid CLI or config JSON)
- `internal` (unexpected exception uncategorized)

## Implementation Pattern
1. Extend metrics registry (lazy safe) with helper `_register('overlay_usage', name, type, help)` calls guarded by group gating.
2. In each script's `main()` (or entry) wrap execution:
   ```python
   import time
   metrics = get_metrics_singleton()
   start = time.time()
   _inc(metrics.overlay_usage_invocations_total, script='weekday_overlay', mode='aggregate')
   try:
       # existing logic
       _inc(metrics.overlay_usage_success_total, script='weekday_overlay', mode='aggregate')
       _set(metrics.overlay_usage_last_run_unixtime, time.time(), script='weekday_overlay')
       _set(metrics.overlay_usage_last_duration_seconds, time.time()-start, script='weekday_overlay')
   except SpecificError as e:
       _inc(metrics.overlay_usage_errors_total, script='weekday_overlay', mode='aggregate', etype='io')
       raise
   ```
3. When writing outputs (HTML, master CSV, quality report) increment `overlay_usage_outputs_total` with appropriate `otype`.
4. Logging: single structured line (INFO) per run summarizing: `{script, mode, duration_ms, outputs, issues}`.

## Logging Additions
Add consistent logger key prefix `overlay_usage`:
```
INFO overlay_usage script=weekday_overlay mode=aggregate duration_ms=842 outputs=csv=42 quality_reports=1 issues=0
INFO overlay_usage script=plot_weekday_overlays mode=plot duration_ms=530 output=html size_kb=187 theme=dark layout=grid
```

## Configuration (Opt-Out / Gating)
Environment control:
- `G6_DISABLE_METRIC_GROUPS=overlay_usage` to suppress (already supported by existing gating mechanism once group assigned).
- No new env vars required for phase 1 (keep surface small).

## Removal / Retention Decision Framework
Collect 4 weeks of metrics (or N cycles of intended usage) and evaluate:
| Signal | Threshold | Action |
|--------|-----------|--------|
| `g6_overlay_usage_invocations_total` for all scripts < 5 per week | Very low | Candidate for removal or external example gist |
| Only `generate_overlay_layout_samples.py` used (others zero) | Demo only | Fold demo into docs; remove scripts |
| Non-trivial aggregation runs (>=3 per week) with outputs | Active | Retain & consider minor refactor (module consolidation) |
| Error ratio (`errors_total / invocations_total`) > 10% | Unhealthy | Triage / fix before removal decision |

## Phase Plan
| Phase | Work | Deliverables |
|-------|------|--------------|
| 1 | Metrics + logging instrumentation | Code changes + docs update (this file) |
| 2 (optional) | Duration histogram / richer quality stats | Only if duration variance matters |
| 3 | Evaluation & decision | Update `CLEANUP_PLAN.md` + potential deprecation entries |

## Minimal Code Touch Points
| File | Change |
|------|--------|
| `src/metrics/metrics.py` | Register overlay_usage metrics (guarded) |
| `scripts/weekday_overlay.py` | Wrap main logic; increment counters; outputs instrumentation |
| `scripts/plot_weekday_overlays.py` | Wrap main; increment counters; HTML output instrumentation |
| `scripts/generate_overlay_layout_samples.py` | Instrument if present |
| `docs/OVERLAY_USAGE_TELEMETRY.md` | (This plan) |
| `CLEANUP_PLAN.md` | Reference telemetry gating (optional) |

## Testing Strategy
- Unit: simulate a fake metrics adapter; invoke small patched main functions; assert counters increment.
- Integration (optional): run scripts with `G6_ENABLE_METRIC_GROUPS=overlay_usage` and scrape `/metrics` or inspect adapter.
- Negative: run with `G6_DISABLE_METRIC_GROUPS=overlay_usage` → metrics absent.

## Risk & Mitigations
| Risk | Mitigation |
|------|------------|
| Cardinality creep via dynamic labels | Fixed enumerations for `script`, `mode`, `etype`, `otype` |
| Performance overhead on large datasets | Minimal: a few counter increments & one gauge set per run |
| Partial failures double-count invocation + success | Only increment success after full completion |
| Backport complexity | Isolated wrapper logic; easy to revert |

## Open Questions (Defer Until Needed)
- Do we need per-index overlay usage? (Probably no; adds cardinality quickly.)
- Should we expose HTML size as a metric? (Prefer log only.)
- Add config-driven sampling? (Not needed; cost already trivial.)

## Next Steps (If Approved)
1. Implement Phase 1 instrumentation PR.
2. Add brief section in main README referencing telemetry & decision policy.
3. Start collection; set calendar reminder for evaluation date.

---
Feedback welcome; after sign-off proceed directly with Phase 1 implementation.
