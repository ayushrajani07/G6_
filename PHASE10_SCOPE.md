# Phase 10 Scope & Success Metrics

Date: 2025-09-30
Status: Draft (baseline committed)
Owner: TBD (Pipeline Rollout Lead)
Version: 1.0

## 1. Objectives
Phase 10 moves the modular pipeline from optional to default while deepening observability, expanding alert quality signals, and introducing adaptive behavior grounded in measured coverage and liquidity. All changes must preserve structural parity and avoid material performance regressions.

## 2. Deliverable Summary
| ID | Area | Deliverable | Description | Flags / Env |
|----|------|-------------|-------------|-------------|
| D1 | Rollout | Shadow Dual-Run Comparator | Run legacy + pipeline concurrently (shadow) and produce structured diff artifacts + metrics. | `G6_PIPELINE_ROLLOUT=shadow` |
| D2 | Rollout | Mode Gating Layer | Switch between shadow / primary / legacy-only execution paths. | `G6_PIPELINE_ROLLOUT` (values: `legacy`, `shadow`, `primary`) |
| D3 | Schema | Inline Alerts | Move alert_* fields into `snapshot_summary.alerts` (or `snapshot_summary.alerts_summary`) canonical block; maintain shim for top-level fields during transition. | `G6_ALERTS_EMBED_LEGACY=1` (optional fallback) |
| D4 | Metrics | Core Operational Metrics | Prometheus: cycle latency histogram/summary, per-phase timers, strike cache hits/misses, alert counts by category, provider latency distribution. | `G6_METRICS_ENABLE=1` |
| D5 | Strikes | Adaptive Strike Policy v2 | Policy plugin adjusts OTM depth & step based on realized coverage & volatility buckets. | `G6_STRIKE_POLICY=adaptive_v2` |
| D6 | Alerts | Taxonomy Expansion | Add `liquidity_low`, `stale_quote`, `wide_spread` alerts with tunable thresholds. | `G6_ALERT_LIQ_MIN_RATIO`, `G6_ALERT_STALE_SEC`, `G6_ALERT_SPREAD_PCT` |
| D7 | Status | Partial Reason Hierarchy | Group partial reasons (e.g. data_quality/*, coverage/*) + emit both grouped & flat forms. | `G6_PARTIAL_REASON_HIERARCHY=1` |
| D8 | Parity | Harness v3 | Extend parity harness to include latency aggregates, grouped reasons, embedded alerts; versioned signature. | N/A |
| D9 | Instrument | Latency Profiling | Per-phase timing (enrichment, finalize, alerts, adaptive). Adds `diagnostics` block in benchmark artifact (optional). | `G6_LATENCY_PROFILING=1` |
| D10 | Validation | Extended Stability Runs | Automated multi-cycle drift analysis & summary report (JSON + human). | Script: `scripts/pipeline_shadow_validate.py` |
| D11 | Docs | Migration & Metrics Docs | `PHASE10_MIGRATION.md`, metrics reference update, README sections. | N/A |
| D12 | Rollout | Default Promotion | Pipeline becomes default (`G6_PIPELINE_ROLLOUT=primary` assumed); legacy becomes opt-out. | Target Date T+? |
| D13 | Cleanup | Legacy Prune Plan | Remove redundant legacy-only branches after stabilization window. | N/A |

## 3. Success Metrics
| Metric | Target | Rationale |
|--------|--------|-----------|
| Structural drift (non-whitelisted fields) | <= 1% over rolling 500 shadow cycles | Ensures parity stability before promotion |
| Alert parity (existing categories) | 100% match (except adaptive coverage flagged) | Prevent regressions during schema move |
| Mean pipeline cycle latency regression vs Phase 9 | < +10% | Accept overhead for metrics & adaptivity |
| Strike cache hit rate | >= 80% (normal volatility); alert if <60% 15m window | Detect mis-specified policy or volatility shock |
| False positives (new alerts) | <5% during tuning | Maintain operator trust |
| Partial reason cardinality | <= Phase 9 baseline | Hierarchy shouldn’t inflate noise |
| Adaptive policy effect | Coverage improvement for low coverage cases +10–20% with <5% latency impact | Demonstrate value |

## 4. Rollout Phases
1. Shadow (Weeks 1–2): Collect diffs + metrics; no external behavior change.
2. Soft Primary (Week 3): Pipeline output becomes canonical while still running legacy for comparison (background diff only).
3. Hard Primary (Week 4): Disable legacy path by default; warnings if forced.
4. Deprecation (Week 6+): Remove dual-run scaffolding if drift remains within target for continuous 2-week window.

## 5. Shadow Comparator Design
- Execution: Legacy and pipeline run sequentially in-memory; pipeline designated candidate.
- Diff Dimensions: counts, coverage aggregates, alert set, partial reasons, structural schema.
- Output: Structured dict with categorized diffs + severity classification (info / warn / critical). Prometheus counters for critical drift.
- Storage: Optional JSON lines file (`data/shadow_diffs.jsonl`) with truncation retention (e.g., last 10k entries).

## 6. Adaptive Strike Policy v2 (Concept)
Inputs: previous coverage ratios, recent implied step (derived from ATM tier), historical volatility bucket.
Logic: widen (increase otm span or finer step) when strike coverage < target; narrow when coverage >> target and latency budget tight.
Safeguards: Min/max bounds, change dampening (don’t oscillate >1 tier per 5 cycles), metrics export for decisions.

## 7. Partial Reason Hierarchy
Example grouping:
- data_quality/* (e.g., missing_ltp, bad_spread)
- coverage/* (e.g., empty_expiry, low_fields)
- structural/* (e.g., zero_options_pruned)
Emission: `partial_reason_totals_flat`, `partial_reason_groups` (nested counts), plus normalized ordering for parity hash.

## 8. Alert Expansion Notes
- liquidity_low: ratio = total_volume / expected_volume_baseline (historical percentile or config). Trigger if < threshold.
- stale_quote: max(last_update_age) > threshold.
- wide_spread: (ask - bid)/mid > threshold for configurable % of strikes.
Add severity levels in summary (future-proof for alert routing).

## 9. Metrics Inventory (Prometheus)
- g6_pipeline_cycle_duration_seconds (Histogram/Summary)
- g6_pipeline_phase_duration_seconds{name=phase}
- g6_provider_enrichment_latency_seconds{index}
- g6_strike_universe_cache_total{state=hit|miss}
- g6_alerts_active_total{category}
- g6_shadow_drift_events_total{severity}
- g6_adaptive_strike_actions_total{action=widen|narrow|stable}
- g6_partial_reason_cardinality

## 10. Backward Compatibility Strategy
- Keep top-level alert_* during transition; mark deprecated in CHANGELOG once inlined version stable.
- Provide environment bypass for adaptive policy (fallback to fixed) if drift or latency regression observed.
- Parity harness v3 computes signatures for both (legacy vs new schema) enabling safe A/B.

## 11. Risk Matrix
| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Adaptive oscillation | Latency/instability | Medium | Rate limit policy adjustments + hysteresis |
| Metric overhead inflation | Performance | Low | Lazy instrumentation + sampling knobs |
| Alert expansion noise | Operator fatigue | Medium | Start in observe-only mode (logs/metrics, no severity escalation) |
| Drift false positives | Rollout delay | Low | Whitelist adaptive-caused field changes in comparator |
| Hierarchy confusion | Misinterpretation | Low | Dual emission (flat + grouped) + docs |

## 12. Acceptance Criteria (Promotion Gate)
- All success metrics satisfied for two consecutive shadow windows (>=500 cycles each).
- No critical drift events in last 100 cycles prior to promotion decision.
- Average CPU & memory overhead increase <10% vs Phase 9 baseline under comparable load.
- Documentation (migration + metrics) merged and referenced in CHANGELOG.

## 13. Out of Scope (Phase 10)
- Multi-process or distributed enrichment scaling.
- Full real-time anomaly ML models (beyond current robust stats).
- Advanced volatility surface modeling for strike selection (reserved for Phase 11+).

## 14. Tracking & Reporting
Weekly summary auto-generated: counts of drift events, adaptive actions, cache efficiency, alert volume breakdown.
Optional script: `scripts/report_phase10_status.py` (to be added) emitting Markdown + JSON.

## 15. Next Immediate Tasks
1. Implement shadow dual-run comparator (D1).
2. Introduce rollout gating flag + decision layer (D2).
3. Add minimal metrics skeleton (counters + cycle timer) to establish baseline prior to adaptive/enrichment changes (subset of D4).

---
End of Phase 10 Scope Document.
