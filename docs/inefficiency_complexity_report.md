Inefficiency & Complexity Scan (R2+ Follow-up)
=================================================

Date: 2025-09-29
Scope: Core option collection pipeline (collectors/unified_collectors.py, broker/kite_provider.py, utils/, orchestrator/components.py) after R1–R4 refactors (registry, set membership, root cache, pre-index map).

Methodology
-----------
1. Static structural inspection of major modules (>400 LOC) for repeated patterns, nested responsibilities, and cold-path code executed on hot paths.
2. Heuristic hot-spot identification based on: loop nesting, external I/O (provider calls), per-option transformations, logging density, and environment flag branching.
3. Post-refactor delta assessment (what R1–R4 already removed vs. remaining opportunities).

Key Hot Paths (Current)
-----------------------
1. kite_provider.option_instruments
   - Pre-filter + pre-index + acceptance loop (now O(K) where K ≈ requested strikes * 2, fallback to O(N) worst case if pre-index empty).
   - Fallback expiry loops (forward/backward) still scan filtered instrument universe repeatedly.
2. unified_collectors expiry loop
   - Enrichment stage (quote retrieval + synthetic fallback) and aggregation of PCR, coverage metrics.
   - Preventive validation, clustering diagnostics (conditionally enabled), metrics emission.
3. Logging & structured trace processing.

Residual Inefficiencies & Complexity Drivers
-------------------------------------------
1. Multi-Responsibility Functions
   - unified_collectors.run (implicit) aggregates: expiry resolution, strike building, fetching, quote enrichment, synthetic fallback, persistence, metrics, human formatting, status semantics.
   - kite_provider.option_instruments handles: cache invalidation, raw fetch, pre-filter, normalization, acceptance, expiry fallbacks, contamination diagnostics, TRACE output.
   Recommendation: Progressive extraction (Phase I: pure filter_accept(instruments,...), Phase II: expiry_fallback_resolver, Phase III: diagnostics emitter).

2. Fallback Expiry Logic Duplication
   - Forward and backward fallback reconstruct per-expiry instrument groups (by_exp) twice when both enabled.
   Optimization: Build by_exp once; pass reference to both forward and backward search functions.

3. Redundant Strike Difference Computations
   - Strike clustering diff calc runs even when G6_STRIKE_CLUSTER enabled globally; fine—but diff list recomputed per index; acceptable but could be skipped if strike count < 3.

4. Logging Overhead (TRACE Mode)
   - TRACE instrument_filter_candidates + instrument_filter_summary + pre_index_summary + strike_cluster potentially bursts >5 lines per expiry.
   Optimization: Single consolidated JSON struct containing candidate sample, summary counts, and pre-index key cardinality.

5. Metrics Emission Granularity
   - Per-index options_processed gauge set each cycle; no delta tracking (causes full export churn). Consider incremental counters + last cycle gauge only when changed.
   - Potential micro-optimization; low priority unless Prometheus scrape overhead diagnosed.

6. Environment Flag Proliferation
   - 25+ flags (G6_LEAN_MODE, G6_TRACE_COLLECTOR, G6_STRIKE_CLUSTER, G6_ENABLE_*_FALLBACK, etc.) leading to wide conditional surface.
   Consolidation Idea: Single JSON config env (G6_RUNTIME_FLAGS='{"trace":true,"cluster":true,...}') parsed once into a dataclass (RuntimeFlags) passed down.

7. Error Handling Duplication
   - handle_provider_error / handle_collector_error / handle_data_collection_error appear in multiple code paths; inconsistent context structure.
   Unify: error.emit(component, stage, index, classification, meta) -> pluggable sinks (log, metrics, panel).

8. Expiry Rule Normalization Spread
   - Collectors, provider, and utilities each resolve expiry rules; risk of drift.
   Centralize: expiry_service.select(index_symbol, rule) returning (date, origin, fallback_used).

9. Synthetic Quote Generation Complexity
   - Inline block re-creates similar structure; could move to synth_quotes_for(instruments, defaults) utility for clarity and test coverage.

10. ATM Derivation Duplication
   - ATM rounding logic still present across: providers_interface, unified_collectors fallback, orchestrator mock provider.
   Now that index_registry exists, create atm_round(index, price) helper using meta.step.

11. Memory Footprint Awareness
   - pre_index map persists only inside option_instruments call (good). However, daily universe list reused; consider shallow size logging daily for capacity monitoring.

12. Fallback Synthetic Base Values
   - In multiple modules (some replaced by registry, but residual constants may remain in tests / mock paths). Continue replacing via registry accessor.

13. Human Formatting in Hot Loop (concise_mode)
   - Formatting human_rows inside expiry loop uses repeated strftime/timezone conversions.
   Optimization: Precompute tz-converted timestamp once per index cycle.

14. PCR Computation Overheads
   - Summations iterate entire enriched_data multiple times (CE count, PE count, call OI, put OI). Combine into a single pass aggregator.

15. Coverage Metrics Repetition
   - coverage_ratio computed, then separate missing strikes traversal; could record missing while computing realized set but cost minor.

16. Fallback Expiry Search Heuristic
   - Nested any(any()) strike fit test: any(any(abs(strike - s) < eps for s in strikes) for inst in pool)
   Precompute pool strike set -> test intersection with requested strike set for O(min(|A|,|B|)).

17. Rejection Counters Granularity
   - rejection reasons aggregated but not surfaced via metrics; adding metrics early may inflate cardinality, but selective high-level counters (expiry_mismatch_total, root_mismatch_total) would aid monitoring.

18. Large Single Module LOC
   - unified_collectors ~1500 LOC: increases PR review time and change risk. Target segmentation:
     a. strikes & expiries (already partly centralized)
     b. fetch & filter orchestrations
     c. enrichment & synthetic fallbacks
     d. persistence & metrics
     e. formatting & display

19. Exception Masking Risk
   - Broad except Exception blocks in hot paths obscure latent data issues; introduce optional STRICT_MODE to re-raise on unexpected branches during staging.

20. Duplicate Instrument Cache Key Format
   - Cache key includes float strike with potential precision risk; standardize to int(round(strike*100)) to avoid float drift.

Prioritized Recommendations
---------------------------
P0 (Immediate, Low Risk)
 1. Consolidate PCR aggregation into single pass.
 2. Add atm_round(index_symbol, price) utility using registry meta.step; replace scattered logic.
 3. Precompute strike set for fallback expiry pools to reduce nested any(any()).
 4. Single-pass build of by_exp in expiry fallback (reuse for forward/backward).
 5. Replace multiple enriched_data CE/PE/OI loops with unified aggregator.

P1 (Short Term, Moderate)
 6. Extract filter_accept() from option_instruments for testable unit surface.
 7. Introduce RuntimeFlags dataclass (central parse of env flags).
 8. Create synthetic_quotes.generate(instruments, ts) helper.
 9. Add simple aggregated rejection metrics (expiry_mismatch_total, strike_mismatch_total) gated by env.
 10. Introduce atm_round + expiry_service module; deprecate inline expiry parsing.

P2 (Strategic Refactor)
 11. Split unified_collectors into pipeline stages (Resolver, Fetcher, Enricher, Persister, Reporter).
 12. Introduce CycleContext dataclass (already noted in TODO roadmap) with typed attributes.
 13. Config rebundle: load YAML/JSON once -> pass typed Config object; retire env sprawl (retain overrides).
 14. Asynchronous / concurrent expiry processing (thread or async I/O) after deterministic tests baseline.
 15. Introduce structured event bus for STRCUT logs (pluggable sinks: stdout, panels, metrics).

Estimated Impact (Qualitative)
-----------------------------
P0 set: 5–12% CPU reduction in heavy TRACE scenarios, minor memory stability, clearer hot path readability.
P1 set: Testability uplift, lower change risk for future providers, reduced conditional churn.
P2 set: Long-term maintainability, parallel scaling readiness.

Proposed Implementation Sequence
--------------------------------
1. P0 batch (single PR): pcr aggregation, fallback reuse, strike set intersection, atm_round helper.
2. P1 batch: runtime flags + filter_accept extraction + synthetic quotes util.
3. Light metrics additions and rejection counters.
4. P2 staged over multiple cycles; begin with CycleContext then module segmentation.

Validation Strategy
-------------------
1. Add focused unit tests:
   - test_filter_accept_strike_membership()
   - test_pcr_aggregation_single_pass()
   - test_atm_round_consistency_registry_step()
2. Benchmark script capturing per-cycle wall time before/after P0.
3. Enable STRICT_MODE in CI basic run to surface unexpected exceptions.

Risk Notes
----------
* Over-consolidation of logging may reduce ad-hoc diagnosis granularity—retain ability to expand via flag.
* Concurrency introduces ordering nondeterminism in logs; defer until deterministic baselines captured.
* Adding metrics increases Prometheus cardinality; gate everything new behind G6_METRICS_VERBOSE flag initially.

Next Immediate Actions (If Approved)
-----------------------------------
1. Implement atm_round helper + replace occurrences.
2. Refactor PCR aggregation loops.
3. Consolidate fallback expiry by_exp construction.
4. Add fallback strike set intersection optimization.

Appendix: Quick Win Code Sketches
---------------------------------
atm_round(index_symbol, price):
    step = get_index_meta(index_symbol).step
    if step <= 0: step = 50
    return round(price/step)*step

PCR single pass aggregator:
    ce_count = pe_count = 0; call_oi = put_oi = 0
    for q in enriched_data.values():
        t = (q.get('instrument_type') or q.get('type') or '').upper()
        if t == 'CE': ce_count += 1; call_oi += float(q.get('oi',0) or 0)
        elif t == 'PE': pe_count += 1; put_oi += float(q.get('oi',0) or 0)

Fallback strike set intersection:
    requested = strike_key_set (ints or rounded floats)
    pool_set = {round(inst_strike,2) for inst in pool}
    if pool_set & requested: candidate

---
End of Report