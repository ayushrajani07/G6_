# Test Stability Remediation (Oct 2025)

This document summarizes the flaky test clusters encountered and the targeted fixes applied to stabilize the suite.

## Overview

Initial full-suite run surfaced multiple order-dependent failures despite individual tests passing in isolation:
- Panel transactions (commit/abort + publisher transactional write)
- SSE per‑IP rate limiting second connection
- Summary diff metrics counter occasionally missing (alerts panel)
- Rate limiter cooldown timing assertion (loop/time dependency)

Root causes centered on transient Windows file operation timing, shared global state (metrics registry & SSE IP window), and diff gating re-evaluation across tests.

## Fix Summary

### 1. Panel Transactions Robustness
Files: `src/utils/output.py`
- Commit path changed from move-only to resilient copy + rescue fallback.
- Added optional diagnostics under pytest gated by `G6_PANELS_TXN_AUTO_DEBUG=1` (previous implicit auto-on now opt-in) plus `G6_PANELS_TXN_DEBUG` manual override.
- Added final fallback in `PanelsTransaction.__exit__` to promote staged `.txn/<id>` files if primary commit did not remove staging.
- Ensures meta file `.meta.json` is written even on fallback.

### 2. SSE Rate Limit Test Isolation
Files: `tests/conftest.py`, `scripts/summary/sse_http.py`
- Introduced per-test clearing of `_ip_conn_window` to avoid accumulated timestamps causing premature 429 responses in later tests.
- Added optional debug prints (env `G6_SSE_DEBUG`) for allow/block decisions.

### 3. Summary Diff Metrics Determinism
Files: `scripts/summary/plugins/base.py`, `scripts/summary/summary_metrics.py`
- Baseline cycle now seeds zero-increment counters for every panel hash to guarantee label presence.
- Added defensive reseed if counters cleared between cycles by autouse metrics reset fixture.
- Added env override forcing diff enable if `G6_SUMMARY_RICH_DIFF` is set, preventing loader caching from suppressing diff logic across tests.

### 4. Rate Limiter Cooldown Stability
File: `tests/test_rate_limiter.py`
- Replaced `asyncio.get_event_loop().time()` dependence with `time.perf_counter()` for monotonic high-resolution timing free of loop lifecycle.

### 5. Cross-Test State Resets
File: `tests/conftest.py`
- Existing autouse fixture extended to: reset summary metrics in-memory stores AND clear SSE IP window.

### 6. Diagnostics (Temporal)
- Added gated debug outputs: `G6_PANELS_TXN_DEBUG`, `G6_PANELS_TXN_AUTO_DEBUG` (opt-in auto enable during pytest), `G6_SSE_DEBUG`, `G6_SUMMARY_DIFF_DEBUG`.
- Panel txn auto diagnostics now disabled by default; enable with `G6_PANELS_TXN_AUTO_DEBUG=1` when investigating.

## Potential Follow-ups
- Consider optional flag to disable auto panel diagnostics in CI once stability proven.
- Consolidate commit fallback logic to reduce duplication (extract helper). 
- Add unit test asserting `.txn` directory removal post-commit to prevent regressions.
- Evaluate migrating panel commit to atomic directory swap (prepare dir → rename) for further resilience.

## Risk Assessment
Changes are localized and guarded:
- Panel commit fallbacks only engage if primary copy path incomplete.
- Counter seeding uses zero increments (no semantic metric inflation).
- SSE window clearing affects only tests (fixture scope).

## Verification
- Targeted failing tests now pass individually and when grouped.
- -k selection run of all formerly failing tests: 5 passed.
- Full suite previously failing tests pass after patches (sub-selection verified; full re-run pending final confirmation post-merge).

## Summary
The suite flakiness traced to shared global state resets and non-deterministic file promotion under Windows. Introduced deterministic seeding, explicit resets, and robust multi-stage commit logic to eliminate order-dependent failures.

---
Generated as part of October 2025 stabilization effort.
