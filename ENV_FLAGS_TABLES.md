# Runtime Environment Flags (Tables, Headers & Dedup)

This document summarizes the environment flags introduced or modified for cycle table aggregation, header deduplication, and log compaction.

## Table / Aggregation Flags

- G6_DISABLE_CYCLE_TABLES
  Disable accumulation & emission of per-cycle human tables.
  Values: 1/true/yes/on to disable. Default: off (tables enabled if module imported).

- G6_CYCLE_TABLE_GRACE_MS
  Milliseconds to defer final table flush after `cycle_status_summary` in order to capture late `option_match_stats` events. If > 0 the first call to `emit_cycle_tables` arms a deadline and returns; a subsequent invocation after the deadline performs the flush.
  Default: 0 (immediate flush).

- G6_CYCLE_TABLE_GRACE_MAX_MS
  Upper bound (ms) on how long the deferred flush can extend (safety cap). Default: same as `G6_CYCLE_TABLE_GRACE_MS`.

- G6_DISABLE_COLOR
  Disable ANSI color in coverage columns.

- G6_DEFER_CYCLE_TABLES
  Defer human table emission until orchestrator loop completion (flush via automatic call). Useful to avoid interleaving multiple partial table blocks when collectors invoked multiple times per cycle.

## Coverage Coloring Thresholds (code constants)
- Green: >= 0.90
- Yellow: >= 0.70
- Red: < 0.70

## Header / Banner Deduplication

- G6_SINGLE_HEADER_MODE
  Emit the daily banner/header exactly once centrally in `run_orchestrator_loop` and suppress all per-cycle headers in `unified_collectors`.
  Values: 1/true/yes/on to enable. Default: off.

- G6_DISABLE_REPEAT_BANNERS
  When enabled (and single header mode off) suppress repeated daily banner emission inside collectors after first appearance.

- G6_COMPACT_BANNERS
  Switch header format from multi-line framed banner to a single concise line.

- G6_DAILY_HEADER_EVERY_CYCLE
  Force banner every cycle (overrides suppression) for debugging comparisons.

## Phase Timing & Summaries

- G6_PHASE_TIMING_MERGE
  Merge per-phase timings into one consolidated `PHASE_TIMING_MERGED` line per cycle.

- G6_PHASE_TIMING_SINGLE_EMIT
  When used alongside `G6_PHASE_TIMING_MERGE=1`, suppress intermediate (per index block) merged lines and emit exactly one consolidated `PHASE_TIMING_MERGED` at the end of the cycle.

- G6_GLOBAL_PHASE_TIMING
  When enabled: suppress all `PHASE_TIMING_MERGED` emission (including single-emit) inside collectors and aggregate phase timings across *all* collector invocations for the cycle. The orchestrator emits a single `PHASE_TIMING_GLOBAL` line once per cycle. Automatically benefits from merge + single emit semantics; you do NOT need to set those flags explicitly when this is on.

- G6_AGGREGATE_GLOBAL_BANNER
  Emit aggregated legs/fails summary banner after each index block (or globally in concise mode) showing system status (GREEN/DEGRADED based on fail count).

- (Implicit) When `G6_SINGLE_HEADER_MODE=1` timing merge and single emit are auto-enabled.

## FINNIFTY Specific Logic

- (No explicit flag) Adaptive widening disabled and strike sampling normalized to multiples of 100; logic resides in code paths guarded by index symbol equality.

## Other Related Flags (contextual)

- G6_IMPORT_TRACE: Emit import trace markers for diagnosing slow module import.
- G6_ENABLE_DATA_QUALITY: Enable data quality checks (affects potential late option stats timing).
- G6_STRUCT_COMPACT: Compact structured JSON payloads (truncate long arrays, drop verbose fields) before logging.
- G6_BANNER_DEBUG: Emit DEBUG lines explaining why banners/market-open lines were suppressed.

## Interaction Notes

1. If `G6_SINGLE_HEADER_MODE` is set, `G6_DISABLE_REPEAT_BANNERS` becomes moot for header emission inside collectors (they are always suppressed).
2. Grace delay (`G6_CYCLE_TABLE_GRACE_MS`) only influences human-readable table flush, not structured JSON events.
3. Merged phase timing (`G6_PHASE_TIMING_MERGE`) coexists with raw `PHASE_TIMING` lines; disabling it restores original per-phase emission.
4. Aggregated summary (`G6_AGGREGATE_GLOBAL_BANNER`) adjusts system status: GREEN when total fails == 0 else DEGRADED.
5. `G6_GLOBAL_PHASE_TIMING` suppresses both merged and single-emit timing lines; only the orchestrator-level global line remains.
6. A curated superset reference of these flags with defaults lives in `.env.summary` for quick copying.

## Quick Examples

Single header, merged timings, compact banner, 250ms grace for tables:
```
G6_SINGLE_HEADER_MODE=1 \
G6_COMPACT_BANNERS=1 \
G6_PHASE_TIMING_MERGE=1 \
G6_CYCLE_TABLE_GRACE_MS=250 \
python scripts/run_orchestrator_loop.py --cycles 5
```

Immediate tables, colorful full banners:
```
unset G6_SINGLE_HEADER_MODE
unset G6_CYCLE_TABLE_GRACE_MS
python scripts/run_orchestrator_loop.py --cycles 1
```

(Adjust unset syntax per shell; on Windows PowerShell: `$env:G6_SINGLE_HEADER_MODE='';`.)

## Troubleshooting

- Tables missing: Verify `G6_DISABLE_CYCLE_TABLES` not set and module imported; ensure at least one `cycle_status_summary` event emitted.
- Delayed or absent table after enabling grace: A second `cycle_status_summary` (next cycle) may trigger flush if first cycle completed within grace window without subsequent emit call.
- Duplicate headers while single header mode active: Check that orchestrator script is the only entry point; external wrappers invoking collectors directly will bypass central header logic.

---
Maintainers: Update this file when introducing new G6_* flags affecting human log surface area.
