## Collector Pipeline: Completed Milestones & Active Backlog

Date: 2025-09-29 (Pruned & Prioritized Backlog Edition)

This trimmed document summarizes what is DONE and focuses only on the next high‑leverage enhancements. Full historical detail archived in `collector_patch_archive_2025-09-29.md`.

### Completed (Locked)
The following are considered stable and out of scope for further modification unless a defect surfaces:
1. Modularization Wave (coverage, validation, iv/greeks, synthetic, persistence helpers) – R1.5–R1.9
2. Greeks extraction & ExpiryContext (R1.10–R1.11)
3. Status reducer + coverage integration (R1.12)
4. Structured observability events (R1.13)
5. Adaptive strike depth retry (R1.14)
6. PARTIAL reason tagging + structured propagation (R1.15)
7. StrikeIndex + root cache + env‑tunable thresholds (R2/R4 portions)

No further roadmap capacity will be spent expanding these areas beyond bug fixes or instrumentation polish explicitly requested.

---

### Active Backlog (Prioritized)

| Pri | Key | Title | Goal (One Line) | Success Metrics | Notes |
|-----|-----|-------|-----------------|-----------------|-------|
| P1 | B1 | Pre‑Index Expiry Map | Build expiry→instrument list once to remove repeated scans. | >=40% reduction in per-cycle instrument filter CPU vs current baseline profiling harness. | Lays groundwork for later contraction logic accuracy. |
| P1 | B2 | Partial Reason Rollup | Aggregate per-cycle counts per partial_reason. | cycle_status_summary adds reason_totals; new lazy counter g6_partial_expiries_total already per-expiry. | Enables alerting without log parsing. |
| P1 | B3 | Central Index Metadata Registry | Single source for step size, base ATM, symbol roots. | All references use registry; no hardcoded steps in collectors/providers. | Ensures consistency before adding new indices. |
| P2 | B4 | Synthetic Strategy Unification | Consolidate synthetic instrument + quote heuristics. | One module API (build_synthetic_expiry, apply_synth_quotes); legacy paths removed. | Simplifies future multi-model experiments. |
| P2 | B5 | Adaptive Contraction (Hysteresis) | Shrink strikes_itm/otm after N healthy cycles. | Depth returns toward configured baseline without oscillation (<=1 expansion/contraction flip per 10 cycles). | Build on existing adaptive expansion. |
| P3 | B6 | Prefilter Safety Valve Refinement | Prevent over-broad scans while avoiding data starvation. | Introduce clamp logic + structured event when valve triggers; zero increase in ZERO_DATA events in test sim. | Guardrail for truncated universes. |
| P3 | B7 | Benchmark Baselines Persistence | Persist lightweight CPU/time + coverage stats snapshot. | JSON artifact per run (profiling harness) with timestamp + diff utility script. | Enables regression detection. |

Legend: P1 = immediate next sprint focus, P2 = queued, P3 = opportunistic / after P1/P2 completion.

---

### Detailed Scopes

#### B1 Pre‑Index Expiry Map (P1)
Contract:
- Input: Raw provider instrument universe (list of symbols/metadata).
- Output: dict[expiry_date] -> list[InstrumentRecord].
- Integration: Replace repeated grouping logic inside option_instruments path.
- Non‑Goals: Cross‑index sharing, persistence of map between cycles (initial iteration is per cycle rebuild).
Edge Cases:
- Instruments with missing or unparsable expiry → counted & logged (structured event future optional) but skipped.
- Mixed weekly/monthly same date collision – rely on existing expiry rule normalization.
Acceptance:
- Profiling harness shows reduced cumulative time in filtering/grouping functions by target >=40%.
- No change in collected option counts (byte‑for‑byte equality on sample cycle diff).

#### B2 Partial Reason Rollup (P1)
Additions:
- Extend cycle_status_summary with: partial_reason_totals {low_strike, low_field, low_both, unknown}.
- Optional: Add per-index reason_totals (kept small; omit if increases payload >10%).
- Prometheus: Expose a gauge or counter family ONLY if cardinality remains fixed (4 labels) – g6_partial_cycle_reasons_total{reason}.
Risks: Double-counting (ensure counted once per expiry per cycle).
Acceptance: New fields appear; tests assert presence and correct sums vs per-expiry list.

#### B3 Central Index Metadata Registry (P1)
Scope:
- New module (e.g., helpers/index_meta.py) with dataclass IndexMeta(step, base_atm, symbol_root, weekly_expiry_wd, display_name,...).
- Replace hardcoded literals in collectors + synthetic + strike building.
Acceptance:
- Grep for previous literals (50, 100, 24800, 54000) inside collectors/providers returns only registry references.
- Tests unchanged; add new test asserting registry completeness (NIFTY, BANKNIFTY).

#### B4 Synthetic Strategy Unification (P2)
Scope:
 - Central module `src/synthetic/strategy.py` providing:
	 - `synthesize_index_price(symbol, index_price, atm_strike)` -> (index_price, atm_strike, used_synthetic)
	 - `build_synthetic_index_context(symbol)` consolidating registry lookups (step, base ATM)
	 - `build_synthetic_quotes(instruments)` deterministic placeholder quotes (replaces ad hoc generate_synthetic_quotes usage on unified path)
 - Heuristic constants (base ATM and step) sourced from index registry; no new literals introduced in collectors.
 - Unified integration: `collectors/unified_collectors.py` now calls strategy instead of inline fallback block (removed legacy SYNTH_INDEX_FALLBACK dict & rounding logic there).
 - Trace event `synthetic_index_price` now emits `strategy=True` when unified path triggers (retains existing fields).
 Remaining (post initial integration) TODOs:
	 - Deprecate and remove `generate_synthetic_quotes` after confirming no external imports (add warning stub first).
	 - Expand tests for multi-index deterministic synthetic ATM matrix & quote value stability (baseline snapshot).
 Acceptance (phase 1 complete): Inline fallback removed; single strategy module authoritative; existing tests pass (plus new `test_synthetic_strategy.py`).

#### B5 Adaptive Contraction (P2)
Scope:
- Track consecutive OK cycles per index; after M (env, default 5) with no PARTIAL low_strike triggers & current depth > baseline, decrement by step.
- Hysteresis: Do not contract if last action was contraction < K cycles ago (env guard).
Acceptance: Simulation with forced expansions then OK cycles shows depth returning toward baseline.

#### B6 Prefilter Safety Valve Refinement (P3)
Scope:
- Add upper bound clamp on candidate instruments per index per expiry (env, default large).
- Structured event when clamp triggers (include counts, sample, reason clamp_exceeded).
Acceptance: No increase in zero_data events in regression tests; clamp event visible when synthetic oversized test universe fed.

#### B7 Benchmark Baselines Persistence (P3)
Scope:
- Lightweight JSON dump (cpu_time_by_section, strike_cov, field_cov, partial_reason_counts) at end of profiling harness run.
- Provide diff script comparing two artifacts producing delta % report.
Acceptance: Artifact produced; diff script outputs human readable table.

---

### Execution Order (Initial Sprint Plan)
1. B1 Pre‑Index Expiry Map
2. B2 Partial Reason Rollup
3. B3 Index Metadata Registry
(Re-evaluate before moving to P2 set.)

### Deferrals / Explicit Non-Goals
- Multi-band PARTIAL classification (minor/major) – defer until rollup proves stable.
- Real-time latency histograms – wait for baseline persistence (B7) to quantify hotspots.
- Prometheus event emission counters – only if ingestion lag debugging becomes necessary.

### Quality & Guardrails
- Each backlog item must ship with: unit tests, (if structural) a before/after micro-benchmark or profiling note, and zero change in option counts for nominal cycles.
- New environment flags documented in README_comprehensive instrumentation section.

---

### Change Log (Backlog Edition)
2025-09-29: Pruned historical narrative; introduced backlog table (B1–B7) and detailed scopes for P1/P2/P3 items.
2025-09-29: B1 helper (expiry_map) added with integration + tests + profiling hook; pending real provider universe wiring (guarded by get_option_instruments_universe).
2025-09-29: B2 partial_reason rollup implemented: cycle_status_summary now includes partial_reason_totals and return object mirrors; Prometheus counters g6_partial_expiries_total + g6_partial_cycle_reasons_total added (lazy). Tests: test_partial_reason_rollup.py.
2025-09-29: B3 index metadata registry introduced (src/utils/index_registry.py) centralizing step size, weekly expiry weekday, synthetic ATM; unified_collectors synthetic fallback & ATM derivation logic refactored to use registry (removing scattered 50/100 & 24800/54000 literals on primary path). Added tests/test_index_registry.py covering core indices, env override, unknown fallback.
2025-09-29: B3 follow-up: migrated remaining step conditionals in orchestrator/components.py, collectors/parallel_collector.py, analytics/option_chain.py, and unified_collectors fallback strike builder to registry lookups (with defensive legacy fallback kept only in deep fallback paths). Registry now authoritative for strike step selection.
2025-09-29: B4 phase 1: Introduced unified synthetic strategy module (`src/synthetic/strategy.py`) and refactored `unified_collectors` to use `synthesize_index_price` & `build_synthetic_quotes`; removed legacy inline synthetic fallback dict & rounding block. Added initial tests (`test_synthetic_strategy.py`). Follow-ups: deprecate old `generate_synthetic_quotes`, broaden deterministic scenario tests, document strategy meta fields if expanded.
2025-09-29: B4 follow-up: Deprecated legacy `collectors.helpers.synthetic.generate_synthetic_quotes` (wrapper now warns & delegates to `build_synthetic_quotes`). Expanded multi-index synthetic tests; added retry safeguard to env var documentation test for intermittent false negatives.
2025-09-29: B5 phase 1: Implemented adaptive contraction hysteresis in `unified_collectors` – per-index healthy_streak, baseline snapshot, cooldown & step tunables via env vars (G6_CONTRACT_OK_CYCLES, G6_CONTRACT_COOLDOWN, G6_CONTRACT_STEP). Emits `strike_depth_adjustment` events with reason='contraction'. Tests & simulation harness scenarios pending.
2025-09-29: B6 Prefilter Safety Valve refinement implemented (clamp + strict mode) with env vars G6_PREFILTER_MAX_INSTRUMENTS, G6_PREFILTER_CLAMP_STRICT, G6_PREFILTER_DISABLE and structured event `prefilter_clamp`. Added tests/test_prefilter_clamp.py.
2025-09-29: B7 Benchmark baseline persistence added (env G6_BENCHMARK_DUMP) writing per-cycle lightweight JSON artifacts + diff utility script `scripts/bench_diff.py`; test `test_benchmark_dump.py` added.
2025-09-29: Added adaptive contraction behavior test scaffold `tests/test_adaptive_contraction.py` validating contraction toward baseline under healthy cycles (hysteresis env tunables).
2025-09-29: B8 Benchmark artifact lifecycle enhancements: added optional compression (G6_BENCHMARK_COMPRESS) producing `.json.gz` artifacts and retention pruning (G6_BENCHMARK_KEEP_N) to cap stored cycles. Updated `unified_collectors` benchmark dump block, extended `scripts/bench_diff.py` to read `.json.gz`, added `tests/test_benchmark_dump_retention.py` covering compression + pruning, documented new env vars in `env_dict.md`.


