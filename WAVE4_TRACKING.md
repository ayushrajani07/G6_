# Wave 4 Tracking

## 1. Overview
Wave 4 focus: elevate typing rigor, introduce panel envelopes (dual legacy + enveloped JSON), add template safety audit, unify endpoint schema typing, and harden dashboard code under stricter mypy rules with minimal runtime impact.

## 2. Task Matrix (Completed vs Pending)
| Task | Description | Status | Key Artifacts |
|------|-------------|--------|---------------|
| 1 | History entries discriminated union (`kind: 'errors'|'storage'`) | Done | `dashboard_types.py`, `metrics_cache.py` |
| 2 | Panel envelope root TypedDicts + dual write (indices, storage, footer) | Done | PanelsWriter (formerly panel_updater), `dashboard_types.py` |
| 2a | PoC template migration (footer fragment) | Done | `_footer_fragment.html`, `footer_enveloped.json` usage |
| 3 | Template field audit test (regex scan) | Done | `tests/test_template_audit.py` |
| 4 | `ErrorHandlerProtocol` introduction | Done | `dashboard_types.py`, `error_handling.py` (attempt & revert) |
| 5 | `MemorySnapshot` TypedDict + endpoint return typing | Done | `dashboard_types.py`, `app.py` |
| 6 | `supports_panels` helper + diagnostics | Done | `panel_support.py`, PanelsWriter |
| 7 | Unified endpoint response TypedDicts | Done | `dashboard_types.py`, `app.py` |
| 8 | Stricter mypy for `src.web.dashboard.*` + remediation | Done | `mypy.ini`, `app.py`, `metrics_cache.py` |
| 8b | Literal `kind` tightening & discriminant refactor | Done | `dashboard_types.py`, `metrics_cache.py` |
| 9 | Tracking document (this file) | Done | `WAVE4_TRACKING.md` |
| 10 | Storage panel template migration to envelope fallback | Done | `_storage_fragment.html`, `storage_enveloped.json` usage |

## 3. Typing & Mypy Hardening
- Added `[mypy-src.web.dashboard.*]` section with: `disallow_untyped_defs`, `disallow_incomplete_defs`, `no_implicit_optional`, `warn_return_any`, `warn_unreachable`, `strict_equality`.
- Introduced/enhanced TypedDicts:
  - Panel payloads: `IndicesStreamPanel`, `StoragePanel`, `FooterPanel` (now with `Literal` kinds)
  - Snapshots & events: `StreamRow`, `FooterSummary`, `StorageSnapshot`, `ErrorEvent`, `MemorySnapshot`
  - History: `HistoryErrors`, `HistoryStorage` (discriminated union via `kind` `Literal`)
  - Unified API: `UnifiedStatusResponse`, `UnifiedIndicesResponse`, `UnifiedSourceStatusResponse` and nested core/resources/adaptive/index entries
- Protocols leveraged: `UnifiedSourceProtocol`, `OutputRouterProtocol`, `PanelsTransaction`, `ErrorHandlerProtocol`.
- Error count journey (dashboard modules): 49 initial strict errors -> 0 (after refactor & helper extraction). Removed all unused `# type: ignore` lines.
- Extracted `_build_error_events` + `_previous_error_value` to eliminate a persistent false-positive unreachable warning.

## 4. Panel Envelope Migration Status
- Dual-output strategy: legacy JSON plus `<name>_enveloped.json` for indices stream, storage, footer.
- Footer template updated to prefer `footer_enveloped.json` (successful PoC of envelope consumption pattern).
- Storage template now migrated (prefers `storage_enveloped.json` with fallback to `snapshot.storage`). Pattern proven repeatable.
- Transitional casts minimized; future step: migrate remaining templates to enveloped variant & retire legacy file writes.
- Diagnostic helper `supports_panels` centralizes capability detection (with `panels_support_diagnostics`).

## 5. Template Safety & Audit
- `tests/test_template_audit.py` scans Jinja templates for `snapshot.*` attribute chains.
- Validates presence against sample structures (special-case handling for enveloped footer fallback).
- Provides early detection if field names drift during refactors.

## 6. Key Refactors & Rationale
- Consolidated kind-based branching via `Literal` discriminants -> clearer code paths & safer narrowing.
- Isolated error events aggregation to enable pure-function testing and remove control-flow complexity.
- Introduced typed memory snapshot and unified API payload wrappers for downstream tooling / future clients.
- Footer panel migration acts as reference implementation for remaining panel transitions.

## 7. Remaining / Deferred Follow-Ups
| Priority | Item | Rationale | Suggested Action |
|----------|------|-----------|------------------|
| High | Migrate remaining templates to envelopes | Unify data contract, deprecate legacy JSON duplication | Incremental template updates + remove legacy writes after adoption |
| High | Add unit tests for `_build_error_events` | Lock behavior & guard refactors | Create focused test with synthetic history states |
| Medium | Remove transitional casts in PanelsWriter path | Tighten type fidelity once all panels fully modeled | Replace any residual casts in summary panel write logic |
| Medium | Expand strict mypy scope beyond dashboard | Broaden static safety | Gradually add package-level strict sections |
| Medium | Introduce runtime schema validation (optional) | Defense in depth pre-template render | Lightweight pydantic or manual asserts under DEBUG |
| Low | Consider consolidating panel write logic | Reduce duplication between legacy & envelope writes | After legacy deprecation, collapse pathways |

## 8. Metrics & Outcomes
- Strict mypy adoption without suppressions achieved.
- Zero runtime-surface changes required for metrics ingestion.
- Template audit provides ongoing safety net for future refactors.
- Error event logic simplified (improved maintainability & testability).

## 9. Next Concrete Steps (Suggested Sequence)
1. Add tests for `_build_error_events` (cover: no history, single delta, multiple keys capped by `max_events`, negative/no-op deltas filtered).
2. Remove legacy footer & storage standalone JSON writes once dashboard definitively uses envelopes only (update test + doc).
3. Introduce envelope for memory or errors panel (if desired) to standardize panel contract.
4. Expand strict mypy to another focused package (candidate: `src.panels.*`).
5. Remove any remaining casts in PanelsWriter code; replace with properly typed assembly functions.
6. Add micro-benchmark or timing log for metrics cache augmentation (optional) to ensure refactors didn’t regress performance.

## 13. Wave 4 Issue Backlog (Initial Draft)
| ID | Title | Theme | Description | Acceptance Criteria | Priority | Status |
|----|-------|-------|------------|---------------------|----------|--------|
| W4-01 | Complete Taxonomy Mapping | Taxonomy Completion | Replace remaining broad `except` blocks in pipeline phases with categorized exceptions | All pipeline phases raise only `PhaseRecoverableError`, `PhaseFatalError`, or documented specific exceptions; zero bare excepts in `src/collectors/modules/pipeline*.py` | High | Done |
| W4-02 | Fatal Ratio Alert Rule | Taxonomy Completion | Add Prometheus alert: fatal index failures > threshold | Recording + alerts (`G6PipelineFatalSpike`,`G6PipelineFatalSustained`,`G6PipelineParityFatalCombo`) present; validated via `tests/test_fatal_ratio_alert_rule.py`; docs reference in `ALERTS_PANEL_ENHANCEMENT.md` | High | Done |
| W4-03 | Alert Severity Labels | Alert Severity & Panels | Introduce severity classification for alert categories (e.g. critical, warning) | Snapshot `alerts.severity` map added, env override `G6_ALERT_SEVERITY_MAP`; docs updated | High | Done |
| W4-04 | Alert Panel Grouping | Alert Severity & Panels | Dashboard panel grouping by severity + category | Panel code updated (`alerts.py`), docs & tests added | Medium | Done |
| W4-05 | Phase Retry Metrics | Performance & Resource | Instrument retry/backoff occurrences per phase | Histogram `g6_pipeline_phase_retry_backoff_seconds`, gauge `g6_pipeline_phase_last_attempts`, test `test_retry_metrics.py` | Medium | Done |
| W4-06 | Memory Footprint Gauge | Performance & Resource | Add RSS gauge sampling pipeline cycles | Gauge `g6_pipeline_memory_rss_mb`; test `test_memory_gauge.py` | Medium | Done |
| W4-07 | Distributional Parity (Strike Shape) | Parity Deep Dive | Compare strike ladder shape distributions (e.g., normalized hist diff) | Component `strike_shape` (L1/TVD), env `G6_PARITY_STRIKE_SHAPE`, test `test_parity_strike_shape.py` | Medium | Done |
| W4-08 | Coverage Variance Component | Parity Deep Dive | Add variance comparison of strike coverage per index | Component `strike_cov_variance`, env `G6_PARITY_STRIKE_COV_VAR`, test `test_parity_strike_cov_variance.py` | Low | Done |
| W4-09 | Benchmark Cycle Integration | Benchmark Evolution | Emit bench deltas into runtime metrics periodically | Integrated helper `_maybe_run_benchmark_cycle` in `pipeline.py`; env `G6_BENCH_CYCLE`, interval/config vars (`G6_BENCH_CYCLE_INTERVAL_SECONDS`,`G6_BENCH_CYCLE_INDICES`,`G6_BENCH_CYCLE_CYCLES`,`G6_BENCH_CYCLE_WARMUP`); metrics `g6_bench_legacy_p50_seconds`, `g6_bench_pipeline_p50_seconds`, `g6_bench_delta_p50_pct`, `g6_bench_delta_p95_pct`, `g6_bench_delta_mean_pct`; test `test_bench_cycle_integration.py` | Medium | Done |
| W4-10 | Bench Threshold Alert | Benchmark Evolution | Add alert when p95 regression > configured threshold | Alert `BenchP95RegressionHigh` (5m, expr uses `g6_bench_delta_p95_pct` vs `g6_bench_p95_regression_threshold_pct`), test `test_bench_p95_regression_alert_rule.py`, README & CHANGELOG updated | Low | Done |
| W4-11 | Legacy Parity Harness Cleanup | Cleanup & Deprecation | Remove obsolete parity harness modules after parity stability | Completed: deprecated scripts, migrated tests to parity score/signature paths, removed harness modules & associated tests | High | Done |
| W4-12 | Deep Metrics Import Prune | Cleanup & Deprecation | Remove deprecated direct imports of `src.metrics.metrics` | Replaced executor + tests imports with facade (`from src.metrics import ...`); dynamic getattr pattern retained; zero remaining non-doc occurrences of `from src.metrics.metrics` aside from docs/migration examples; updated guidelines; test suite green | Medium | Done |
| W4-13 | Dashboard Envelope Completion | Cleanup & Deprecation | Migrate remaining templates to enveloped JSON only | All panels emit & consume `<name>_enveloped.json`; legacy writes gated behind `G6_PANELS_LEGACY_COMPAT` (default off); README schema + CHANGELOG updated (2025-10-08) | High | Done |
| W4-14 | Operator CLI Parity Snapshot Tool | Ops Tooling | CLI to dump current rolling parity + alert diff JSON to file/stdout | Script `scripts/parity_snapshot_cli.py`; test `test_parity_snapshot_cli.py` validates schema & components; README & CHANGELOG updated | Medium | Done |
| W4-15 | Anomaly Classification Event | Ops Tooling | Structured event emission when alert parity diff spikes | Module `pipeline/anomaly.py`, event `pipeline.alert_parity.anomaly` (env `G6_PARITY_ALERT_ANOMALY_THRESHOLD` & `G6_PARITY_ALERT_ANOMALY_MIN_TOTAL`), integrated in pipeline; test `test_parity_anomaly_event.py` | Low | Done |
| W4-16 | Error Event Builder Tests | Taxonomy Completion | Unit tests for `_build_error_events` function | Implemented (`tests/test_error_event_builder.py`) covering empty history, single delta, capped multi, ordering, negative/zero filtered | High | Done |
| W4-17 | Retry Policy Documentation | Performance & Resource | Document per-phase retry/backoff policies & thresholds | Section 4.6 added to `PIPELINE_DESIGN.md`; matches implemented metrics | Medium | Done |
| W4-18 | Weight Tuning Study Artifact | Parity Deep Dive | Collect empirical distributions for alert & strike components | Script `parity_weight_study.py`, sample `data/parity_weight_study_sample.json`, design Section 4.7 (method + adoption) | Low | Done |
| W4-19 | Panel Performance Benchmark | Performance & Resource | Measure dashboard panel JSON read/parse latency | Implemented `scripts/bench_panels.py` + test `tests/test_panels_perf_benchmark.py` producing per-panel mean/p95/min/max and aggregate stats | Low | Done |
| W4-20 | CI Gate: Parity & Fatal Guard | Ops Tooling | CI step fails if rolling parity < threshold or fatal ratio > limit | Script `scripts/ci_gate.py`, tests `tests/test_ci_gate.py`, README usage section, CHANGELOG entry; sample workflow snippet | High | Done |

## 14. Issue Field Glossary
- Theme: Aligns with Wave 4 strategic focus areas.
- Acceptance Criteria: Objective, testable completion definition.
- Priority: Initial triage (can be rebalanced during sprint planning).


## 10. Reference Files Modified This Wave
- `src/types/dashboard_types.py`
  (Former) `scripts/panel_updater.py` (removed in favor of unified PanelsWriter)
- `src/web/dashboard/app.py`
- `src/web/dashboard/metrics_cache.py`
- `src/utils/panel_support.py`
- `src/web/dashboard/templates/_footer_fragment.html`
- `tests/test_template_audit.py`
- `mypy.ini`

## 11. Validation Summary
- Mypy: clean (dashboard modules) under strict subset.
- Template audit: passes after footer envelope integration.
- Runtime safety: Network/envelope reads wrapped in error handler with low severity.

## 12. Notes
- Discriminated unions now unlock future compile-time assurance for history-based branching.
- Envelope adoption path intentionally incremental to minimize deployment risk.
- Structured tracking file (this doc) can be versioned each wave; consider adding a brief changelog header in future iterations.

---
_Last updated: (auto-generated) Wave 4 typing & envelopes tracking._
