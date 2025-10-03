# Collector Modularization Blueprint

Version: 1.0  
Date: 2025-09-29  
Owner: Collectors / Bench Subsystem WG  
Status: Draft (Execution-ready)

---
## 1. Executive Summary
`unified_collectors.py` has accreted multiple responsibilities: universe derivation, expiry/strike normalization, adaptive contraction/expansion, synthetic / strategy overlays, coverage evaluation, metrics emission, anomaly / benchmark hooks, and persistence. The objective is to decompose into a cohesive, testable, observable module set with **zero behavior drift** and **continuous parity guarantees** while keeping the test suite green at every phase.

Core philosophy: *Stabilize contracts → Introduce context + types → Extract pure logic slices guarded by parity harness → Instrument deltas → Decommission legacy monolith progressively*.

---
## 2. Current State Assessment
| Aspect | Current Issue | Impact |
|--------|---------------|--------|
| File Size / Cognitive Load | Large unified file (multi-hundred lines) blending concerns | Slows onboarding & changes risk regressions |
| Hidden Couplings | Implicit data shape mutations between sections | Hard to reason about invariants |
| Testing Granularity | Only end-to-end + broad functional tests | Bug localization slow |
| Metrics Emission | Interleaved with transformation logic | Hard to refactor without metric drift |
| Adaptive Contraction | Prototype logic embedded inline | Difficult to iterate algorithm |
| Synthetic Strategy | Coexists with base acquisition logic | Obscures baseline vs synthetic contributions |
| Persistence & Checkpoint | Mixed formatting + side effects | Side-effect ordering fragile |

Pain Point Summary: Lack of **layer boundaries** & **explicit interfaces** drives change risk and slows future backlog execution (expansion heuristics, new strategy types, coverage improvement scoring, stateful adaptive algorithms).

---
## 3. Goals & Non-Goals
### Goals
- Establish stable, explicit interfaces for each logical slice.
- Achieve deterministic parity (byte / semantic) for all externally visible artifacts & metrics through each phase.
- Reduce mutation surface and side-effect scattering (centralize persistence & emission).
- Enable unit-level testing for previously implicit logic (expiry map, strike depth normalization, contraction decisions, coverage eval).
- Provide observability: per-stage timing, input/output cardinalities, contraction decisions, synthetic contribution ratios.
- Minimize refactor risk with incremental phases + rollback path.
- Improve extensibility for new strategies & adaptive algorithms.

### Non-Goals (for this wave)
- Reinvent underlying data acquisition backends.
- Introduce async or parallel execution model changes.
- Optimize performance beyond low-hanging structural wins.
- Replace existing metrics backend or environment variable semantics.

---
## 4. Architectural Principles
1. **Single Responsibility Modules**: Each module exports *pure* functions + a narrow orchestrator facade where needed.
2. **Context Object**: Immutable (or write-once) `CollectorContext` passed through pipeline; no ad-hoc dict mutation.
3. **Side-Effects Isolation**: Persistence & metrics in dedicated modules with structured events.
4. **Determinism First**: All transformations reproducible given same inputs & environment variables.
5. **Observability Hooks**: Every boundary produces structured debug snapshot (optional via env flag) + counters/timers.
6. **Progressive Extraction**: No large-bang move; each phase extracts and rewires one dimension with parity validation.
7. **Heuristic Encapsulation**: Contraction/adaptation heuristics parameterized & unit-tested independently.
8. **Explicit Data Shapes**: Dataclasses (or TypedDict fallback if cyclic import risk) for key artifacts.

---
## 5. Target Module Set
Proposed directory: `src/collectors/modules/`

| Module | File | Responsibility | Key Exports |
|--------|------|----------------|-------------|
| Types & Context | `context.py` | Core dataclasses / protocol types | `CollectorContext`, `InstrumentRecord`, `ExpiryMap`, `StrikeDepthSpec` |
| Expiry Universe | `expiry_universe.py` | Normalize & group expiries, build map + stats | `build_expiry_map(context, instruments)` |
| Strike Depth / Range | `strike_depth.py` | Depth selection, clamp logic, adaptive width hooks | `compute_strike_depth(config, meta)` |
| Coverage Evaluation | `coverage_eval.py` | Coverage scoring, gap detection, contraction triggers | `evaluate_coverage(snapshot)` |
| Adaptive Contraction / Expansion | `adaptive_adjust.py` | Decide shrink/expand actions based on metrics | `compute_adjustments(history, coverage_metrics)` |
| Synthetic Strategies | `synthetic_strategy.py` | Generate synthetic / derived instruments | `apply_synthetic_strategies(context, base_set)` |
| Metrics Emission | `metrics_emit.py` | All Prometheus/event metrics (pure formatting) | `emit_metrics(stage, metrics_bundle)` |
| Benchmark / Anomaly Bridge | `benchmark_bridge.py` | Invoke benchmark diff/anomaly annotations | `annotate_benchmarks(context, artifact_path)` |
| Persistence & Checkpoint | `persist.py` | Atomic writes, retention, compression | `persist_universe(context, universe_obj)` |
| Orchestrator (Thin) | `pipeline.py` | High-level pipeline calling modules in sequence | `run_pipeline(context)` |
| Legacy Facade | `unified_collectors.py` (shrinking) | Temporary facade delegating to pipeline | `main()` -> pipeline |

Optional (Phase ≥4):
- `debug_dump.py` (central structured debug snapshots)
- `parity_harness.py` (used also by tests)

---
## 6. Interface / Contract Sketches
```python
# context.py
@dataclass(frozen=True)
class CollectorContext:
    env: Mapping[str, str]
    now: datetime
    indices: list[str]
    config: CollectorConfig  # parsed from g6_config
    logger: logging.Logger
    metrics_sink: MetricsSink
    debug: bool = False

@dataclass
class InstrumentRecord:
    symbol: str
    expiry: date
    strike: float | None
    option_type: str | None  # 'C' | 'P' | None
    meta: dict[str, Any]

@dataclass
class ExpiryMap:
    expiries: dict[date, list[InstrumentRecord]]
    stats: dict[str, Any]  # counts, earliest, latest, buckets

@dataclass
class CoverageMetrics:
    total_instruments: int
    expiries: int
    strike_coverage_ratio: float
    contraction_triggered: bool
    details: dict[str, Any]
```
Key principle: modules receive *plain data objects*; no module mutates context.

---
## 7. Dependency Graph
```
context.py
  ↑ (imported by all)
expiry_universe.py  →  strike_depth.py
       ↓                      ↓
 coverage_eval.py   ←   adaptive_adjust.py
       ↓                      ↑
 synthetic_strategy.py         |
       ↓                       |
 benchmark_bridge.py           |
       ↓                       |
 persist.py  ← metrics_emit.py │
       ↑_______________________│
            pipeline.py
```
Rules:
- Metrics emission depends only on *data bundles*, not raw internals.
- Adaptive module depends on coverage metrics + historical ring buffer (kept in orchestrator or a small state carrier object).

---
## 8. Phase Execution Plan
| Phase | Title | Scope | Risk | Rollback Simplicity | Exit Criteria |
|-------|-------|-------|------|---------------------|---------------|
| 0 | Baseline & Metrics | Add timing + cardinality probes to legacy file only | Low | Trivial (metrics optional) | Bench parity snapshot captured; tests green |
| 1 | Context & Types Introduction | Introduce `context.py`, refactor signatures (no logic move) | Low | Rename reversion | All calls use context; no behavior diff; parity snapshot matches |
| 2 | Extract Expiry Universe | Move expiry map + stats logic | Medium | Re-inline function | Parity: expiry buckets identical (hash compare) |
| 3 | Strike & Coverage Split | Extract strike depth + coverage eval; add isolated tests | Medium | Drop imports & revert 2 funcs | Coverage metrics & contraction triggers identical across 10 sampled runs |
| 4 | Adaptive & Synthetic Modules | Pull adaptive contraction + synthetic strategy gen | Higher | Keep legacy toggles behind flag | All synthetic counts & contraction actions match baseline parity set |
| 5 | Persistence & Metrics Isolation | Move writes + formatting | Medium | Roll back single orchestrator import | All emitted metric series & files byte-identical |
| 6 | Benchmark Bridge & Final Orchestrator | Create `pipeline.py`; shrink legacy file to facade | Low | Keep old main in git history | Tests green; legacy file <150 lines |
| 7 | Cleanup & Deprecation | Remove dead code paths, finalize docs | Low | N/A | No direct logic in legacy; docs updated |

Timeboxing suggestion: 1–2 days per medium phase, faster for low-risk.

---
## 9. Success Metrics & KPIs
| Metric | Baseline (Capture) | Target After Phase 7 |
|--------|--------------------|----------------------|
| Lines in `unified_collectors.py` | (Record exact) | <150 |
| Average collector run time | T0 | ≤ T0 (+5% max) |
| Unit test coverage for modules | ~0% specific | ≥75% of new pure logic |
| Parity snapshot diffs | 0 required | 0 sustained across phases |
| Mean time to localize logic bug | (qualitative) | 50% reduction (subjective dev survey) |
| Synthetic vs base instrument attribution clarity | Low | Documented + per-stage metric |

---
## 10. Parity Snapshot Harness Design
Purpose: Guarantee semantic equivalence each phase.

Mechanics:
1. Define `parity_harness.py` with entry: `capture_parity(context, tag) -> ParitySnapshot`.
2. Capture artifacts:
   - Sorted list of instrument symbols.
   - Expiry distribution (date → count).
   - Strike histogram (bucketed).
   - Synthetic instrument count & IDs (if flag enabled).
   - Coverage metrics object (JSON serialized sorted keys).
   - Contraction decisions (if any).
   - Metrics emission sample (scraped or intercepted values).
3. Persist JSON under `parity_snapshots/<phase_tag>.json`.
4. Comparator: `compare_snapshots(a, b) -> list[Diff]` with typed diff categories (count drift, missing symbol, etc.).
5. Test: `tests/test_parity_phaseN.py` asserts `len(diffs)==0`.

Hash Strategy:
- Use stable sorted serialization -> SHA256 to create a single summarizing hash for quick CI gating.

---
## 11. Testing Strategy
| Test Type | Focus | Example |
|-----------|-------|---------|
| Unit | Pure functions (expiry normalization) | test_expiry_map_groups_monthly |
| Property | Idempotence / ordering invariance | input list permutations → same map |
| Parity | Cross-phase regression | baseline vs extracted phase snapshot |
| Mutation Spot | Force contraction trigger | artificially set coverage low |
| Performance Smoke | Runtime envelope | assert runtime < threshold under sample data |

Edge Cases:
- Empty instrument list.
- Single expiry only.
- All strikes identical.
- Synthetic strategies disabled / enabled interplay.
- Extreme contraction parameters (min==max bounds).

---
## 12. Phase 5 Execution Summary (Persistence & Metrics Isolation)

Status: COMPLETED (2025-09-29)

Scope Implemented:
- Extracted benchmark artifact write + anomaly detection + compression + retention + benchmark-related metrics emission into `modules/benchmark_bridge.py`.
- Removed large inline block from `unified_collectors.py`; replaced with a thin call preserving identical behavior & env var semantics.
- Added dedicated unit test `test_benchmark_bridge_unit.py` validating base artifact structure and anomaly spike detection using a synthetic series.

Parity & Validation:
- All existing benchmark/anomaly tests (`test_benchmark_dump*`, `test_benchmark_anomaly*`, `test_bench_report_smoke`, `test_benchmark_verify*`) pass without modification.
- Env var coverage test updated after documenting `G6_COLLECTOR_REFACTOR_DEBUG`.
- Digest stability maintained (hash computed pre-pretty serialization identical to legacy path logic).

Risk Mitigation:
- Module preserves ordering & key set of payload fields; anomaly annotation performed prior to digest insertion exactly as before.
- Metrics names unchanged; lazy instantiation logic mirrored.

Next Phase (6) Preview:
- Introduce `pipeline.py` orchestrator that sequences modules (expiry, strikes, coverage, adaptive, benchmark bridge, persist) reducing `unified_collectors.py` to a facade.
- Add parity snapshot harness to compare pipeline vs legacy facade before full cutover.

---
## 12. Metrics & Observability Plan
New internal debug counters (prefixed `g6_collector_refactor_*` until stable):
- `stage_duration_seconds{stage=...}` (histogram)
- `instruments_count{stage=pre,post}`
- `synthetic_added_total`
- `contraction_events_total{reason=...}`
- `coverage_ratio` (gauge)
- `parity_snapshot_hash` (info label metric updated once per run in dev mode)

Enable via env `G6_COLLECTOR_REFACTOR_DEBUG=1`.

---
## 13. Risk Matrix & Mitigations
| Risk | Phase | Impact | Mitigation | Rollback Trigger |
|------|-------|--------|------------|------------------|
| Hidden side-effect ordering lost | 2–5 | Silent logic drift | Parity harness + file diff tests | Any non-explained diff |
| Performance regression | 3–6 | Latency ↑ | Stage timers baseline compare | >5% sustained increase |

---
## 14. Orchestration Facade (Phase 6 Addition)

Status: IMPLEMENTED (2025-09-29)

Purpose: Provide a single stable API (`run_collect_cycle`) that can delegate to the legacy `run_unified_collectors` or the modular `pipeline.run_pipeline` without callers handling feature flags. This enables incremental rollout and live A/B parity validation.

Location:
```
src/orchestrator/facade.py
```
Public Function:
```
run_collect_cycle(index_params, providers, csv_sink, influx_sink, metrics, *,
                  mode='auto', parity_check=False, **kwargs) -> dict
```

Mode Resolution:
- `mode='legacy'` – Force legacy unified collectors path.
- `mode='pipeline'` – Force new pipeline orchestrator.
- `mode='auto'` (default) – Select pipeline iff `G6_PIPELINE_COLLECTOR` is truthy; otherwise legacy.

Parity Check:
When `parity_check=True` and the effective mode is pipeline, the facade executes:
1. Pipeline run (authoritative return value).
2. A secondary legacy run (with a deep-copied `index_params`).
3. Builds parity snapshots of both results using `collectors.parity_harness.capture_parity_snapshot` and compares SHA256 hashes.
4. Logs a warning on mismatch; if `G6_FACADE_PARITY_STRICT=1` the mismatch raises a `RuntimeError` (intended for CI canaries / strict rollouts).

Environment Variables (documented in `env_dict.md`):
| Variable | Purpose | Default |
|----------|---------|---------|
| `G6_PIPELINE_COLLECTOR` | Enables pipeline when mode=auto. | off |
| `G6_FACADE_PARITY_STRICT` | Escalate parity mismatch to exception. | off |

Return Shape:
Matches legacy result contract (keys: `status`, `indices_processed`, `have_raw`, `snapshots`, `snapshot_count`, `indices`, `partial_reason_totals`). Parity mode does not mutate the pipeline result; legacy run is side-effect only for hash comparison.

Testing:
- `tests/test_facade_parity.py` validates hash parity pipeline vs legacy and auto+parity path behavior.
- Fixture in the same test ensures `G6_PIPELINE_COLLECTOR` flag is restored to avoid leakage side effects across unrelated tests (prevents false negatives in parallel collection and harness stability tests).

Operational Guidance:
1. Initial rollout: use `mode='auto'` with `G6_PIPELINE_COLLECTOR=1` and `parity_check=True` in staging to surface divergences without aborting.
2. Promote to strict: set `G6_FACADE_PARITY_STRICT=1` in CI once hashes remain stable for N consecutive runs.
3. Full cutover: remove flag from environment; keep facade interface stable for callers.
4. Decommission legacy: once metrics & parity stable, shrink `unified_collectors.py` further or replace its body with a call to pipeline (tracked in future Phase 7 cleanup).

Limitations / Current Differences:
- Pipeline currently omits some deep partial reason tallies (initialized to zero) and certain structured events still emitted only by the legacy path; parity harness scope intentionally excludes those for now. Any addition to parity scope must be documented and gated to avoid noisy hash churn.

Future Enhancements:
- Extend parity harness to include summarized anomaly metrics for a richer equivalence assertion.
- Optional diff artifact emission on mismatch (`parity_diff_<ts>.json`) for rapid triage.
- Graceful downgrade logic if pipeline encounters a catastrophic exception mid-cycle (flagging and auto-falling back to legacy for next invocation with exponential backoff).

| Metrics label change accidental | 5 | Alert panel breaks | Metrics golden test | Missing expected label |
| Synthetic ordering nondeterminism | 4 | Snapshot diffs | Sort before output | Flaky parity test |
| Developer confusion in transition | 1–4 | Slow velocity | Living doc + path map | Repeated PR review confusion |

---
## 14. Rollback Strategy
Each phase PR retains a feature flag / branch strategy:
- Maintain `LEGACY_PIPELINE_ENABLED=1` override until Phase 6 complete.
- Keep legacy functions unmodified for at least one phase after extraction (soft-deprecated comment header).
- If parity fails in staging: revert orchestrator wiring only (modules remain for incremental retry).

---
## 14a. Phase 6 Scaffold Status (Pipeline Orchestrator)

Status: INITIAL SEQUENCING IMPLEMENTED (2025-09-29)

Highlights:
- `modules/pipeline.py` now performs real staged sequencing (expiry map -> strikes -> coverage -> adaptive -> benchmark) instead of pure legacy delegation.
- Legacy `run_unified_collectors` still guards activation via `G6_PIPELINE_COLLECTOR=1` and recursion sentinel `G6_PIPELINE_REENTRY=1`.
- Benchmark artifact emission routed through pipeline output (unchanged semantics, anomaly detection intact).
- Extracted quote enrichment to `modules/enrichment.py`; pipeline now supplies enriched quote map to field coverage metrics (synthetic fallback & preventive validation still legacy until next extraction step).
- Extracted synthetic quote fallback to `modules/synthetic_quotes.py` and integrated into pipeline (generates synthetic quotes when enrichment returns empty; metrics updated best-effort).
- Extracted preventive validation stage to `modules/preventive_validate.py`; pipeline now cleans enriched data and emits optional debug snapshots (G6_PREVENTIVE_DEBUG) before field coverage metrics.

Current Behavior:
- Functional near-parity: certain deep partial_reason classifications and enrichment specifics are placeholders (set to None/zero) and will be backfilled.
- Metrics & anomaly / benchmark paths remain via `benchmark_bridge.py`; artifact digest stability preserved.

Next Steps (Planned):
1. Fill enrichment placeholder with extracted quote merge logic.
2. Implement detailed partial_reason computation parity and update `partial_reason_totals` accumulation.
3. Add pipeline parity pytest(s) comparing a golden index summary vs legacy.
4. Integrate greeks/IV stage (optional, gated) to reduce remaining legacy responsibilities.
5. Shrink `unified_collectors.py` below target LOC threshold (<150) and move remaining inline helpers.
6. Update Section 17 env var mapping once additional stages (persist, snapshots) migrate.

Risk Mitigation in Scaffold Phase:
- Delegation gated & off by default (flag opt-in).
- Internal recursion guard ensures accidental nested delegation cannot deadlock or loop indefinitely.
- Env var documented; coverage test enforces presence. No new tests added yet (zero logic delta) to avoid brittle temporary assertions.

Rollback:
- Remove delegation block (single guarded `if`) to revert instantly; scaffold module can remain harmlessly for next attempt.

Telemetry Considerations:
- Future: add a one-shot info log when pipeline mode active (suppressed in tests) to aid field debugging.

---

## 14b. Per-Index Processor Extraction

Status: IMPLEMENTED (2025-09-29)

Purpose: Isolate the large legacy `_process_index` function from `unified_collectors.py` into a dedicated module `modules/index_processor.py` to reduce the monolith size and enable future fine‑grained extraction of the per‑expiry loop while preserving 100% behavior parity.

Location:
```
src/collectors/modules/index_processor.py
```
Export:
```
process_index(ctx, index_symbol, params, *, compute_greeks, estimate_iv, greeks_calculator,
              mem_flags, concise_mode, refactor_debug, build_snapshots, risk_free_rate,
              metrics, parity_accum, snapshots_accum, dq_enabled, dq_checker, deps) -> dict
```

Dependency Injection Contract (`deps` mapping):
| Key | Type / Shape | Responsibility |
|-----|--------------|----------------|
| `TRACE_ENABLED` | bool | Enables structured trace hooks (no-op if false) |
| `trace` | callable(msg, **fields) | Structured tracing adaptor from legacy context |
| `AggregationState` | class | Carries rolling aggregation attributes (snapshot timing, representative window) |
| `build_strikes` | callable(atm, itm, otm, index, scale=None) -> list[float] | Legacy strike universe builder (optional; preferred path now via `strike_depth.compute_strike_universe`) |
| `synth_index_price` | callable(index, raw_index_price, atm) -> (index_price, atm, used_synth: bool) | Synthetic strategy index price adjuster |
| `aggregate_cycle_status` | callable(expiry_details:list[dict]) -> str | Computes overall cycle status label (ok/partial/bad) |
| `process_expiry` | callable(**kwargs) -> dict | Legacy per‑expiry worker (still inline in legacy module; next extraction target) |
| `run_index_quality` | callable(dq_checker, index_price, index_ohlc) -> (ok:bool, issues:list) | Data quality check for the index quote |

Fallback Behavior:
- Each dependency is required for strict parity. For defensive robustness the module creates a minimal stub for `AggregationState` (exposes `snapshot_base_time` & `representative_day_width`) if absent to avoid attribute errors.
- Other missing callables degrade to harmless no‑ops returning conservative defaults (empty lists / failure tags). This prevents hard crashes in partial import scenarios but is not expected in normal operation; a future hardening step may elevate missing critical dependencies to explicit errors once rollout confidence is high.

Notable Internal Safeguards:
- ATM strike derivation now includes a guarded fallback using index LTP and step metadata identical to legacy path.
- Expiry map build is wrapped with iterable validation to avoid silent TypeErrors if provider returns a non‑iterable sentinel.
- Strike clustering diagnostics wrapped in best‑effort try/except block; emits structured `STRUCT strike_cluster` line on fallback.
- Aggregation overview emission keeps original ordering and snapshot writing semantics; on emitter failure it reverts to direct CSV/Influx writes mirroring legacy code.

Parity Validation:
| Test | Result |
|------|--------|
| `tests/test_parity_harness_basic.py` | PASS |
| `tests/test_parity_harness_multi.py` | PASS |
| `tests/test_facade_parity.py` | PASS (2 tests) |
| Full Suite | 421 passed, 23 skipped, 0 failures |

Risk Assessment:
| Risk | Mitigation |
|------|------------|
| Silent drift due to fallback lambdas | Parity tests exercised immediately; future TODO to assert all critical deps present in prod mode |
| AggregationState stub masking real import issue | Stub is only instantiated if dependency missing; logging can be added in strict mode flag later |
| Future per‑expiry extraction altering control flow | Establish contract for `process_expiry` before moving to ensure argument parity & return dict shape hashing captured |

---
## 14c. Expiry Helper Primitives Extraction

Status: IMPLEMENTED (2025-09-29)

Purpose: Isolate low-level, side-effect tolerant primitives used by the per‑expiry pipeline so that subsequent refactors (synthetic fallback, preventive validation, metrics shaping) can evolve independently of the legacy `unified_collectors.py` monolith. The extracted functions were previously private-style helpers (`_resolve_expiry`, `_fetch_option_instruments`, `_enrich_quotes`, `_synthetic_metric_pop`).

Location:
```
src/collectors/modules/expiry_helpers.py
```
Exports (public names map 1:1 to legacy helpers without leading underscore):
| Function | Responsibility | Notes |
|----------|----------------|-------|
| `resolve_expiry` | Determine concrete expiry date from rule (ISO short-circuit → optional expiry_service → provider fallback) | Preserves service candidate trace logging gated by `G6_TRACE_EXPIRY` |
| `fetch_option_instruments` | Retrieve option instrument universe for (index, expiry); emit structured error hooks | Reports via `error_bridge` when available; swallows and logs unexpected exceptions |
| `enrich_quotes` | Perform quote enrichment; on structured quote errors triggers error_bridge; returns mapping symbol→data | Leaves synthetic fallback decision to caller |
| `synthetic_metric_pop` | Emit synthetic quote usage metrics from provider primary driver (if implemented) | No-op safe; defensive error handling |

Behavioral Guarantees:
1. Code path is a verbatim copy (whitespace-normalized) of legacy implementations to ensure zero drift.
2. All logging messages, metric call names, and error handling semantics retained.
3. Return shapes identical (types: `date`, `list[dict]`, `dict[str, Any]`, or `None`).

Metrics & Observability:
- Continues to call `metrics.mark_api_call(success=..., latency_ms=...)` if present on provided metrics object (matching previous behavior).
- Trace logging of expiry candidate lists retained and still gated by `G6_TRACE_EXPIRY`.

Compatibility Shim:
During extraction a regression surfaced in `test_legacy_expiry_service_integration.py` which monkeypatches the legacy module global `_EXPIRY_SERVICE_SINGLETON`. The helper-level cache moved to the new module, breaking attribute patching. To preserve the historical patch surface:
1. Reintroduced a shadow `_EXPIRY_SERVICE_SINGLETON` variable in `unified_collectors.py`.
2. Updated the `_resolve_expiry` wrapper to forward any monkeypatched singleton into `expiry_helpers` before invocation.
3. Exported the shadow variable via `__all__` so `monkeypatch.setattr` sees it as an assignable attribute.

Test Adjustments:
- Added `tests/test_expiry_helpers_unit.py` covering success, provider failure propagation, instrument fetch, quote enrichment, and synthetic metrics no-op safety.
- Updated `tests/test_expiry_processor_unit.py` metrics stub to implement `mark_api_call` explicitly and tightened success path assertions (fail closed instead of pass-on-empty).
- Legacy integration test now passes using the restored shim (full suite: 442 passed / 23 skipped / 0 failed at extraction commit).

Risk & Mitigation:
| Risk | Mitigation | Status |
|------|-----------|--------|
| Hidden divergence in expiry resolution sequencing | Verbatim copy; parity suite exercises resolution paths | Covered |
| Missed monkeypatch surfaces (singleton) | Back-compat shim + export in `__all__` | Fixed |
| Future drift after refactors to service selection logic | Unit tests isolate `resolve_expiry` including explicit ISO shortcut and provider fallback | In place |

Next Refactor Candidates (post-helpers):
1. Preventive validation & synthetic fallback logic (move from expiry processor to dedicated module; decouple synthetic generation trigger conditions).
2. Metrics aggregation around per-option processing (extract counters/gauges wiring to reduce branching in `process_expiry`).
3. Finalization & status labeling harmonization (co-locate `_compute_expiry_status` & classification logic with result shaping).

Decommission Plan:
- Once downstream stages (preventive validation, synthetic fallback, finalize) are extracted, the per‑expiry processor can be simplified to a pure orchestrator calling stateless primitives, enabling reuse inside an eventual asynchronous or batched processing model.

Parity Verification Snapshot:
- No dedicated new parity test added (logic unchanged); relied on existing full-suite invariants plus new unit tests for isolation. Should parity drift be suspected in future edits, introduce a golden snapshot test for expiry resolution using a controlled provider fixture.

---

Next (Planned) Extraction: Per‑Expiry Processor
Target Module: `modules/expiry_processor.py`

Proposed Contract (draft):
```
process_expiry(ctx, *, index_symbol, expiry_rule, atm_strike, concise_mode,
               precomputed_strikes, expiry_universe_map, allow_per_option_metrics,
               local_compute_greeks, local_estimate_iv, greeks_calculator,
               risk_free_rate, per_index_ts, index_price, index_ohlc, metrics,
               mem_flags, dq_checker, dq_enabled, refactor_debug,
               parity_accum, snapshots_accum, build_snapshots,
               allowed_expiry_dates, pcr_snapshot, aggregation_state) -> dict
```
Return Dict (unchanged from legacy):
`{ success: bool, option_count: int, failure_reason: str|None, expiry_rec: dict, human_row: tuple|None }`

Acceptance Criteria for Extraction:
1. Byte/semantic parity of `expiry_rec` objects (deep-sorted JSON hash) across sample runs.
2. Aggregated `option_count` and `failure_reason` tallies identical for each index & expiry rule.
3. No change in `pcr_snapshot` key set or representative day/window data.
4. Parity harness & facade parity tests remain green.
5. Full suite passes without modification to existing tests.

Planned Steps:
1. Isolate current per‑expiry block from `unified_collectors.py` (search for loop producing `expiry_outcome`).
2. Create `modules/expiry_processor.py` with pure logic function; inject required side-effect helpers (parity accumulation, snapshot writer) via arguments (avoid new global deps mapping initially).
3. Replace legacy body with delegator; keep fallback try/except returning original dict on import error.
4. Run parity tests; if drift found, diff JSON of `expiry_rec` and strike list ordering to identify root cause.
5. Document section 14c with contract + validation results.

Deferred Hardening:
- Enforce presence of all critical deps (raise on missing) once pipeline path fully adopted.
- Introduce lightweight dataclass wrappers (`IndexProcessResult`, `ExpiryProcessResult`) for stronger static typing once extraction set complete.

Rollforward / Rollback:
- Rollforward: proceed to per‑expiry extraction only after 2 consecutive green parity cycles in CI.
- Rollback: revert delegator commit (single patch) leaving module unused; no data migration needed.

Observability TODO:
- Add trace hook points at: `expiry_start`, `option_batch_processed`, `expiry_summary` within future `expiry_processor`.
- Emit gauge/histogram for per‑expiry option processing seconds to refine SLA dashboards.

Summary: The index-level extraction achieved zero drift and reduces the remaining high‑complexity surface inside `unified_collectors.py`. Per‑expiry extraction is now lower risk with a clear contract and validation plan.

---

## 14c. Per-Expiry Processor Extraction

Status: IMPLEMENTED (2025-09-29)

Objective: Move the large `_process_expiry` function into `modules/expiry_processor.py` as `process_expiry` to further shrink `unified_collectors.py` and isolate expiry-scoped concerns (instrument fetch, enrichment, validation, coverage metrics, IV/greeks, persistence, adaptive post hooks, snapshot building, concise formatting, parity accumulation).

Location:
```
src/collectors/modules/expiry_processor.py
```
Export:
```
process_expiry(ctx=..., index_symbol=..., expiry_rule=..., atm_strike=..., concise_mode=...,
               precomputed_strikes=[...], expiry_universe_map=..., allow_per_option_metrics=...,
               local_compute_greeks=..., local_estimate_iv=..., greeks_calculator=..., risk_free_rate=...,
               per_index_ts=..., index_price=..., index_ohlc=..., metrics=..., mem_flags=...,
               dq_checker=..., dq_enabled=..., refactor_debug=..., parity_accum=[...], snapshots_accum=[...],
               build_snapshots=..., allowed_expiry_dates=set(), pcr_snapshot=dict(), aggregation_state=obj) -> dict
```

Design Notes:
- Implements identical logic; only structural change is delegation & lazy import of legacy helpers (`_resolve_expiry`, `_fetch_option_instruments`, etc.) to avoid circular import at module load.
- Maintains all try/except boundaries and logging wording (avoids parity hash churn).
- AggregationState interactions unchanged; metrics payload pass-through identical.
- Parity accumulation list receives the same dict shape (ordering preserved) when `G6_COLLECTOR_REFACTOR_DEBUG=1`.

Validation:
| Test | Result |
|------|--------|
| `tests/test_parity_harness_basic.py` | PASS |
| `tests/test_parity_harness_multi.py` | PASS |
| `tests/test_facade_parity.py` | PASS |
| Full Suite | 421 passed / 23 skipped |

No new tests required because existing parity harness already diff-covers expiry output (status, counts, strike selection, synthetic fallback markers). A future enhancement may add a targeted JSON hash assertion for individual `expiry_rec` objects to catch accidental field omission before commit.

Risk & Mitigations:
| Risk | Mitigation |
|------|------------|
| Silent divergence if helper import path changes | Lazy imports raise and trigger delegator fallback (logged) – parity tests fail in CI if persistent |
| Missed attribute added to expiry_rec in future PR inside legacy file only | Extraction documented; reviewers instructed to modify `expiry_processor` going forward |
| Fallback path masks real failure in production | Future hardening flag (e.g., `G6_STRICT_MODULE_IMPORTS=1`) can escalate fallback to exception |

Next Extraction Candidates:
1. Aggregation & snapshot overview emission (move remaining overview logic into `aggregation_overview.py`).
2. Synthetic strike clustering diagnostics (optional isolation; currently inline in index processor).
3. Memory pressure flag application + adaptive scaling logic (split from index processor into `memory_adjust.py`).

Post-Extraction LOC Impact:
- (Capture optionally in future commit once measured) Goal: progressive reduction toward <150 lines at completion.

Planned Hardening (Deferred):
- Introduce dataclass wrappers `ExpiryProcessResult` and `IndexProcessResult` once all imperative logic extracted to stabilize return schemas.
- Add explicit dependency presence assertions in non-test runs (raise if a critical helper missing).

Telemetry TODO:
- Add per-expiry histogram metric: `expiry_option_processing_seconds` (success-labelled) sourced from existing timing phases.
- Structured event `STRUCT expiry_summary` to accompany human concise row (exposes coverage + synthetic flags + dq issue counts).

Outcome: The per-expiry extraction preserved behavior (parity tests green) and unlocks finer-grained future refactors (aggregation & adaptive separation) with reduced risk.

---

## 14d. Aggregation Overview Module Rename

Status: IMPLEMENTED (2025-09-29)

Goal: Rename and position the previously extracted `aggregation_emitter` logic under a clearer, extensible module name `aggregation_overview`. The functionality emits per-index overview snapshots (PCR snapshot + representative day width / base timestamp) to CSV and optionally Influx sinks.

Changes:
1. New module `modules/aggregation_overview.py` containing `emit_overview_aggregation` (logic copied verbatim from prior `aggregation_emitter`).
2. Legacy `aggregation_emitter.py` converted into a backward compatibility shim re-exporting the same symbol to avoid breaking any in-flight branches or unrefactored imports.
3. Updated `index_processor.py` to import from `aggregation_overview` directly.

Behavior / Semantics: No changes; identical try/except boundaries, log messages, and return tuple `(representative_day_width, snapshot_base_time)`.

Parity Validation:
| Test | Result |
|------|--------|
| Parity basic | PASS |
| Parity multi | PASS |
| Facade parity | PASS |
| Full test suite | 421 passed / 23 skipped |

Rationale for Rename:
- Future roadmap includes adding aggregated per-expiry rollups, normalization spans, and potentially summary histograms; `aggregation_overview` better conveys surface area than `emitter`.
- Avoids confusion with other emitters (metrics, struct events) already present.

Deprecation Plan:
- Keep shim for minimum of two release cycles; add log warning behind `G6_REFACTOR_DEBUG` flag if direct import from `aggregation_emitter` detected (TODO if needed).
- Remove shim once code search shows no remaining direct imports outside migration history.

Next Opportunities:
- Split PCR computation logic (if/when expanded) into `pcr_metrics.py` with deterministic ordering and unit tests.
- Add optional structured event `STRUCT overview_snapshot` for downstream streaming consumers (guarded by debug flag initially).

Risk: Very low (rename only with shim). Any accidental import typo would raise immediately and parity tests would fail.

Outcome: Naming alignment completed; groundwork for richer aggregation layer established without behavioral drift.

---

## 14e. Memory & Adaptive Scaling Extraction

Status: IMPLEMENTED (2025-09-29)

Objective: Isolate memory pressure driven strike depth scaling and adaptive passthrough logic from `index_processor` into `modules/memory_adjust.py` to reduce cognitive load and prepare for future adaptive heuristics evolution.

Module: `src/collectors/modules/memory_adjust.py`
Export:
```
apply_memory_and_adaptive_scaling(effective_itm, effective_otm, mem_flags, ctx, *, compute_greeks, estimate_iv)
 -> (itm, otm, allow_per_option_metrics, local_compute_greeks, local_estimate_iv, passthrough_scale_factor|None)
```

Behavior Parity:
- Logic copied verbatim (scale min clamp=2; flags: skip_greeks, drop_per_option_metrics; env `G6_ADAPTIVE_SCALE_PASSTHROUGH`).
- Returned `scale_factor` directly passed to strike universe builder; previous inline conditional (`if passthrough else None`) preserved through function’s return contract (returns None when not active).
- No change to logging surfaces or metrics side-effects (none existed in original block besides a debug on failure).

Validation:
| Test | Result |
|------|--------|
| Parity basic | PASS |
| Parity multi | PASS |
| Facade parity | PASS |
| Full suite | 421 passed / 23 skipped |

Rationale:
- Centralizes environment + flag interplay so future adaptive algorithm can be swapped or extended (e.g., dynamic target option budget) without touching index orchestration code.
- Improves unit testability (future small tests can directly drive mem_flags combinations).

Next Enhancements (Deferred):
1. Add unit tests for memory_adjust (parametrize over depth_scale, skip_greeks, drop_per_option_metrics, adaptive passthrough) – out of scope for current mechanical extraction wave.
2. Introduce optional metric gauges (`memory_depth_scale_applied`, `adaptive_scale_factor`) when refactor debug flag enabled.
3. Extend contract to optionally return a structured reason list for applied adjustments (useful for future observability dashboards).

Risk: Minimal – pure relocation; if import fails, Python would raise at module load causing parity tests to fail immediately (none observed).

Outcome: Further reduction of inline branching in `index_processor` and clearer separation of adaptive heuristics from core per-index workflow.

---

---
## 15. Migration Guidelines
- New logic additions during refactor window must target **extracted module** if that concern already migrated; otherwise rejected in review.
- No cross-module imports except through approved interfaces (documented in section 6).
- Shared constants live in `modules/constants.py` (introduced only if >2 modules require them).

---
## 16. Code Style & Naming Conventions
- Module names: lowercase with underscores; verbs avoided (prefer nouns: `expiry_universe`).
- Functions: `verb_noun` e.g., `build_expiry_map`, `evaluate_coverage`.
- Data structures: dataclasses; prefer explicit types over `dict[str, Any]` unless truly dynamic.
- Logging: Structured: `logger.info("stage=coverage decision=%s ratio=%.3f", decision, ratio)`.
- No global mutable state; historical state passed explicitly (ring buffer object) to adaptive module.

---
## 17. Environment Variable Mapping
| Env Var | Module Touchpoint | Action |
|---------|-------------------|--------|
| G6_CONTRACT_* (example) | adaptive_adjust.py | Read once into config object |
| G6_SYNTHETIC_* | synthetic_strategy.py | Parameterize generation |
| G6_BENCHMARK_* | benchmark_bridge.py | Toggle annotation path |
| G6_BENCHMARK_ANNOTATE_OUTLIERS | benchmark_bridge.py | Controls anomaly annotate call |
| G6_COLLECTOR_REFACTOR_DEBUG | pipeline.py / metrics_emit.py | Enables debug instrumentation |
| G6_OUTPUT_SINKS | persist.py | Decide write destinations |
| G6_PREFILTER_DISABLE | prefilter_flow.py / prefilter.py | Bypass instrument clamp logic entirely |
| G6_PREFILTER_MAX_INSTRUMENTS | prefilter_flow.py / prefilter.py | Upper bound on instrument count (subject to 50-item safety floor) |
| G6_PREFILTER_CLAMP_STRICT | prefilter_flow.py / prefilter.py | Promote clamp overflow to warning / future error path |
| G6_ENABLE_DATA_QUALITY | data_quality_flow.py | Toggle data quality (option + consistency) evaluation |
| G6_EXPIRY_SERVICE | expiry_helpers.py | Select expiry resolution strategy (legacy compat hook) |
| G6_TRACE_EXPIRY | expiry_helpers.py / expiry_processor.py | Verbose tracing for expiry processing stages |

Rule: All env access centralized in context construction; modules receive already-parsed config subset.

---
## 18. Acceptance Criteria per Phase (Detailed)
| Phase | Detailed Criteria |
|-------|-------------------|
| 0 | Added timers; produced baseline snapshot + stored under `parity_snapshots/baseline.json`; no test changes needed |
| 1 | All functions accept `CollectorContext`; zero logic changes (AST diff shows only signature + pass-through) |
| 2 | `expiry_universe.py` unit tests: min 3 scenarios; parity diff empty |
| 3 | Strike depth logic pure & test for symmetric depth, clamp behavior, empty edge; coverage metrics stable |
| 4 | Synthetic generation isolated; deterministic ordering (sorted keys); contraction decisions reproducible |
| 5 | Persistence atomic write abstraction; metrics emission moved; golden metrics test passes |
| 6 | Legacy file <150 LOC; orchestrator in `pipeline.py`; all CI green |
| 7 | Dead code removed; docs & diagrams updated; feature flags cleaned |

---
## 19. Implementation Checklist (Living)
(Will be migrated to issue tracker / todo system)
- [ ] Capture baseline parity snapshot
- [ ] Introduce `context.py` & refactor signatures
- [ ] Add parity harness skeleton
- [ ] Extract expiry map + tests
- [ ] Extract strike depth + coverage eval + tests
- [ ] Extract adaptive adjustment + synthetic strategies + tests
- [ ] Extract persistence + metrics emission
- [ ] Introduce pipeline orchestrator & shrink legacy file
- [ ] Final cleanup & doc refresh

---
## 20. Open Questions
| Question | Proposed Resolution Path |
|----------|-------------------------|
| Should adaptive history persist across runs? | Keep in-memory only now; future optional state store | 
| Need plugin architecture for strategies? | Defer; simple registry dict suffices initially |
| Benchmark annotation sync vs async? | Stay synchronous (I/O cost low) |
| Introduce pydantic for data validation? | Defer; dataclasses + type checks adequate |

---
## 21. Appendix: Data Shape Evolution Trace
Provide (in commits) a markdown table capturing each phase's context dataclass fields & module diffusion; ensures historical traceability & audit.

Template entry example:
```
| Phase | Context Fields Added | Modules Added | Legacy LOC | Parity Hash |
|-------|----------------------|---------------|-----------:|-------------|
| 0 | now, env, config, logger, metrics_sink | (none) | 820 | abc123... |
```

---
## 22. Next Immediate Action
If approved: execute Phase 0 (instrument timing + capture baseline snapshot) and open tracking issue list referencing this blueprint.

---
## 23. Summary
This blueprint decomposes the collector monolith into stable, testable, observable modules with a controlled, reversible path. Success hinges on strict parity enforcement, incremental extraction, and disciplined environment / context handling.

---
## 23.a Recent Targeted Extractions (2025-09-29)

Objective: Reduce per-expiry function complexity (previously accumulating synthetic fallback, prefilter clamp, and data quality checks inline) while guaranteeing zero behavior drift. Each extraction followed the pattern: (1) Identify tightly scoped block, (2) Introduce pure/side-effect-contained helper module, (3) Wrap legacy code with thin delegator preserving signatures & logging, (4) Add focused unit tests exercising success + failure + flag permutations, (5) Run full suite for parity.

### A. Synthetic Fallback (`modules/synthetic_fallback.py`)
- Function: `ensure_synthetic_quotes(quotes, ctx, trace)` returns `(quotes_enriched, early_return_flag)`.
- Responsibility: Guarantee downstream assumes presence of synthetic markers even if real quotes absent; previously an inline try/except block.
- Invariants Preserved:
    * No change to quote ordering (stable sort maintained)
    * Early-return semantics identical when fallback path taken
    * Logging keys: `stage=synthetic_fallback` unchanged
- Tests Added: `test_synthetic_fallback_unit.py` covering (a) no-op pass-through, (b) fallback insertion, (c) exception resilience (ensures graceful degrade not crash).

### B. Prefilter Clamp Flow (`modules/prefilter_flow.py`)
- Function: `run_prefilter_clamp(instruments, ctx, trace)` wraps existing `apply_prefilter_clamp` adding environment flag branching + defensive error isolation.
- Enhancements:
    * Centralizes env flag triad: `G6_PREFILTER_DISABLE`, `G6_PREFILTER_MAX_INSTRUMENTS`, `G6_PREFILTER_CLAMP_STRICT`.
    * Enforces 50-item safety floor (was implicit constant—now documented & unit tested).
    * Standardizes clamp outcome structure (count_before, count_after, clamped, reason) for future metrics emission.
- Tests Added: `test_prefilter_flow_unit.py` validating: (a) disable flag bypass, (b) standard clamp within bounds, (c) enforcement of 50-item minimum, (d) strict vs non-strict paths.
- Fixed Prior Assumption Bug: Original failing assertion expected clamp below floor; corrected to reflect enforced minimum.

### C. Data Quality Flow (`modules/data_quality_flow.py`)
- Function: `apply_data_quality(expiry_ctx, option_chain, ctx, trace)` populates `dq_issues`, `dq_consistency` fields; integrates two lower-level bridges (`run_option_quality`, `run_expiry_consistency`).
- Behavior: No effect unless `G6_ENABLE_DATA_QUALITY` (or equivalent internal toggle) set; default is parity (no-op). Injected fields only added when enabled, avoiding schema drift in baseline path.
- Error Handling: Exceptions in either sub-check captured and converted to issue entries with `source=exception` to prevent pipeline abort.
- Tests Added: `test_data_quality_flow_unit.py` for: (a) clean chain, (b) option issues present, (c) consistency discrepancy, (d) exception raised by underlying checker.

### D. Expiry Helpers Compatibility (`modules/expiry_helpers.py` + `unified_collectors.py` shim)
- Reintroduced shadow `_EXPIRY_SERVICE_SINGLETON` in legacy orchestrator to restore external integration relying on previous import location; wrapper delegates to new helper ensuring import paths continue functioning (mitigated failing integration test observed mid-refactor).

### E. Refactored `expiry_processor.py`
- Replaced inline blocks with calls to: `ensure_synthetic_quotes`, `run_prefilter_clamp`, `apply_data_quality`.
- Net Result: Cognitive load and local cyclomatic complexity reduced (exact measurement pending metrics script). Diff verified to be structural only (logic parity confirmed via unchanged test expectations outside newly added targeted cases).

### F. Risk Mitigation Tactics
- Thin Delegators: Kept original logging messages & key-value schema to avoid dashboard regression.
- Progressive Tests: Each new module introduced simultaneously with its unit test file—prevents untested abstractions.
- Parity Discipline: Full test suite executed after each extraction; failures only due to test assumption (prefilter floor) not logic drift.

### G. Follow-Up Actions (Doc-Specific)
- Add diagram illustrating updated per-expiry pipeline with new modular callouts.
- Introduce metrics naming plan (e.g., `prefilter.clamp.count_before`) once metrics stage extraction occurs.
- Capture complexity delta once instrumentation script lands.

### H. Persistence Flow Extraction (2025-09-29 Later)

Module: `modules/persist_flow.py` exposing `run_persist_flow`.

Moved Logic:
- Pre-write record count logging
- `allowed_expiry_dates` attribute assignment on CSV sink
- Wrapper call constructing ExpiryContext (still built in caller) invoking `persist_with_context`
- Structured trace event `persist_done`

Rationale:
- Shrinks `expiry_processor` complexity and isolates I/O heavy segment for future enhancements (async, retries, batching) behind stable API.
- Central point to introduce per-sink timers and advanced error classification without touching orchestration logic.

Parity Guarantees:
- Logging verbatim (message text & levels)
- Trace event name & fields identical
- Failure path still yields `failed=True` when CSV write errors occur
- Metrics emission + Influx side effects unchanged (delegated to existing helper)

Unit Tests Added: `test_persist_flow_unit.py` (success path, CSV failure, Influx failure non-fatal, per-option metrics disabled case).

Defensive Fallback:
- If module import or execution fails, caller falls back to direct `persist_with_context`; worst-case surrogate object with `failed=True` returned to preserve control flow.

Future Enhancements Candidates:
- Sub-phase timing instrumentation (`persist_csv`, `persist_influx`, `persist_metrics`)
- Optional asynchronous flush behind `G6_ASYNC_PERSIST`
- Retry with exponential backoff for transient disk or network errors
- Structured error codes for downstream alerting


---
## 24. Progress Tally (Live Update – 2025-09-29)

Status Snapshot:

| Area | Baseline (Pre-Refactor) | Current State | Notes |
|------|-------------------------|---------------|-------|
| Monolith LOC (`unified_collectors.py`) | (original large; record pending) | Reduced via `_process_index` + `_process_expiry` helpers | Further shrink once pipeline fully adopted |
| Per-Index Loop | Inline, deeply nested | Extracted to `_process_index` | Cyclomatic complexity lowered (exact metric pending tooling) |
| Per-Expiry Logic | Inline inside per-index loop | Extracted to `_process_expiry` | Behavioral parity confirmed by full test suite (417 pass / 23 skip) |
| Concise Human Row Formatting | Inline tuple assembly in `_process_expiry` | Extracted to `modules/formatters.py::format_concise_expiry_row` | Pure formatting; parity run green |
| Data Quality Integration | Not present | Added `data_quality_bridge.py` gated by `G6_ENABLE_DATA_QUALITY` | Flag documented; default off ensures parity |
| Memory Pressure Handling | Inline heuristics | Bridge module `memory_pressure_bridge` | Abstracted evaluation, leaves decisions separate |
| Status Finalization | Inline | In `modules/status_finalize.py` (previous phase) | Called inside expiry processing helper |
| Persistence IO | Mixed inline & helper | Using `persist_with_context` / extracted helpers | Full extraction of pipeline-wide persistence still TODO |
| Structured Events Emission | Interleaved | Consolidated via `struct_events_bridge` (earlier extraction) | Emission sites remain stable |
| Adaptive Summary & Adjust | Inline | `adaptive_summary` + `adaptive_adjust` modules | Post-expiry adjustment call isolated |
| Benchmark / Anomaly Bridge | Inline originally | (Planned / partially scaffolded) | Bridge file referenced in blueprint; verify presence before next phase |
| Pipeline Orchestrator | Not active | Flag `G6_PIPELINE_COLLECTOR` path present (delegating) | Full sequencing & removal of recursion guard still pending |
| Parity Harness | Not implemented | Pending | Needed before aggressive pruning of legacy code |
| Snapshot Building | Inline inside loop | Extracted to `modules/snapshots.py` (build_expiry_snapshot) | Helper now called from `_process_expiry` |
| Preventive Validation | Inline | Extracted (`preventive_validate`) and invoked | Issues & dropped counts logged |
| Greeks / IV | Inline logic wrappers | Partially modular (`greeks_compute`, `iv_estimation`) | Further consolidation possible |
| Strike Depth | Fallback + build util | Partially modular (`strike_depth` + fallback) | Consider centralizing scale/passthrough logic |
| Expiry Map | Inline build | Modular (`expiry_universe.build_expiry_map`) | Map stats & timing hooked |

Recently Added Helpers:
- `_process_index(...)`: encapsulates per-index orchestration (fetch index price, build strikes, iterate expiries, aggregate status & human output).
- `_process_expiry(...)`: pure per-expiry pipeline (resolve, instruments fetch/filter, enrichment, preventive validation, coverage metrics, IV/Greeks, persist, finalize, adaptive adjust, snapshot option objects, human row assembly).

Parity Validation:
- Full test run: 417 passed / 23 skipped / 0 failures after both helper extractions and env var documentation addition.
- Env var coverage: `G6_ENABLE_DATA_QUALITY` documented; test green.

Risk / Debt Items Remaining:
1. (RESOLVED) Snapshot aggregation state previously used temporary global holder lambdas (`_rdw_tmp`, `_sbt_tmp`). Replaced with `AggregationState` dataclass (fields: `representative_day_width`, `snapshot_base_time`) captured during `_process_expiry` aggregation.
2. Type variance warning (float vs int strikes) surfaced in editor diagnostics; consider adjusting `finalize_expiry` signature to accept `Sequence[float]`.
3. Pipeline orchestrator not yet the default; parity harness required before enabling by default.
4. Persistence & metrics emission still partially interleaved in `_process_expiry`; candidate for a `modules/persist.py` stage function.
5. Lack of cyclomatic complexity measurement baseline; add lightweight script (`scripts/complexity_report.py`) optionally in future.

Immediate Next Recommendations:
1. Introduce an `AggregationState` dataclass to carry `pcr_snapshot`, `representative_day_width`, `snapshot_base_time` instead of ad-hoc holders.
2. Add minimal parity harness capturing index → expiry status summary & option symbol set for two consecutive cycles to lock behavior.
3. Migrate snapshot object construction to `modules/snapshots.py` for isolation and easier testing.
4. Gradually move preventive validation and synthetic fallback into pipeline path when pipeline flag enabled (currently legacy path wrappers used).

Decision Log (since blueprint publication):
- Chose function extraction before pipeline activation to reduce diff blast radius.
- Added optional data quality layer gated by env var to future-proof validation without impacting baseline.

Tracking Metrics To Capture Next:
- Pre vs post extraction cycle wall time (mean, p95) under a fixed test dataset.
- Per-expiry processing time distribution (to validate no regression in new helper overhead).

Exit Criteria Alignment Check:
- Phase 0–3 style extractions effectively in place for several concerns (though numbering shifted slightly from original blueprint sequencing). Need explicit parity snapshot artifact to formally claim Phase 0 completion per doc.

---
_This section is living; update after each significant extraction or when enabling the pipeline orchestrator path._
