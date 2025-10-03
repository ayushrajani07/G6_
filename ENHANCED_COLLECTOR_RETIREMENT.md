Enhanced Collector Retirement
=============================

Date: 2025-09-29

Summary
-------
The deprecated `src/collectors/enhanced_collector.py` module has been fully
removed. Its remaining unique functionality (synthetic instrument/quote
fallbacks + optional ExpirySnapshot construction) was extracted into a new
`src/collectors/snapshot_collectors.py` module. All orchestrator logic now
routes through `unified_collectors` for primary collection with an optional
post-collection snapshot step when `G6_AUTO_SNAPSHOTS=1`.

Motivation
----------
1. Eliminate dual code paths (enhanced vs unified) that increased complexity
   and test surface area.
2. Centralize persistence, enrichment, and metrics instrumentation in a single
   pipeline (unified collectors) while still supporting lightweight in-memory
   snapshot generation for UI / cache features.
3. Remove lingering deprecation warnings and simplify configuration flags.

Key Changes
-----------
* Removed file: `src/collectors/enhanced_collector.py`.
* (Historical) Added file: `src/collectors/snapshot_collectors.py` (export: `run_snapshot_collectors`).
* Updated `orchestrator/cycle.run_cycle`:
  - Dropped branching on `use_enhanced`; parameter retained as no-op for
    backward compatibility (ignored internally).
  - Added post-unified collection snapshot phase using `run_snapshot_collectors`.
  - (2025-09-29) Snapshot construction fully integrated into `run_unified_collectors` via `build_snapshots` flag; `snapshot_collectors.py` removed.
* Adjusted parallel index helper `_collect_single_index` signature (removed
  `use_enhanced` parameter); updated corresponding test monkeypatch.
* Deleted test `tests/test_enhanced_collector_snapshots.py` – superseded by
  existing `test_auto_snapshots_updates_cache` which now monkeypatches the new
  snapshot collectors function.
* Documentation updates across README files and parity matrix to reference
  snapshot collectors instead of enhanced collectors.

Environment / Flags
-------------------
The legacy `--enhanced` CLI flag is still accepted in `scripts/run_orchestrator_loop.py`
but only logs (implicit) via updated description; its functional effect is removed.

Auto snapshots continue to be driven by `G6_AUTO_SNAPSHOTS=1` plus `G6_SNAPSHOT_CACHE=1`.

Migration Notes
---------------
* Any external scripts importing `run_enhanced_collectors` must switch to either:
  - `from src.collectors.unified_collectors import run_unified_collectors` for full pipeline
  - (Deprecated) `from src.collectors.snapshot_collectors import run_snapshot_collectors` for snapshot-only behavior (now removed; use unified collectors integration instead).
* If previous code relied on synthetic fallbacks for resilience, those are preserved in the snapshot collectors path.
* Snapshot objects (`ExpirySnapshot`) and domain model mapping semantics are unchanged.

Testing & Verification
----------------------
* Full test suite passes: 356 passed / 23 skipped (pre-retirement baseline maintained).
* Updated `test_auto_snapshots_updates_cache` passed with new monkeypatch target.
* Updated `test_parallel_retry` to reflect helper signature change (now passes).

Future Follow-ups (Optional)
----------------------------
* Consider integrating snapshot construction directly into unified collectors under a flag to remove the secondary traversal.
* Evaluate whether the `use_enhanced` parameter can be removed entirely (will require adjusting all run_cycle call sites and parametrized tests after a deprecation window).
* Potentially add a focused unit test for synthetic snapshot fallback now covered by unified collectors (strike/quote synthetic paths remain inside unified pipeline).

End of document.
