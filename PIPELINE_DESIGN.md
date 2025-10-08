# Pipeline Design & Cutover Criteria

_Last updated: 2025-10-08_

This document codifies the authoritative expiry processing pipeline design, phase contracts, observability surfaces, parity & performance thresholds, and the controlled cutover / rollback procedure from the legacy imperative implementation to the modular phased pipeline.

## 1. Objectives
1. Deterministic, inspectable progression of an `ExpiryState` through discrete, composable phases.
2. Minimize implicit global state and ad‑hoc environment parsing (centralize in `CollectorSettings`).
3. Provide complete operational visibility (structured events + metrics + diagnostics snapshot) to allow evidence‑based cutover.
4. Establish objective cutover gates and a fast, low‑risk rollback path.

## 2. Core State Model
`ExpiryState` (selected fields):
```
index: str                  # e.g. NIFTY
rule: str                   # resolution / selection rule token
expiry_date: date|None      # resolved target expiry
strikes: list[int|float]    # strike ladder (ordered)
instruments: list[dict]     # raw instrument metadata (provider normalized)
enriched: dict[str, dict]   # keyed by instrument identifier -> enriched quote/analytics
expiry_rec: dict            # summary record / snapshot for persist & classify
errors: list[str]           # phase-tagged error markers
flags: dict[str, Any]       # transient markers (fabricated, salvaged, recovered, etc.)
```

### State Invariants
| Invariant | Introduced By | Rationale |
|-----------|---------------|-----------|
| `expiry_date` non-null after `resolve` OR `flags['fabricated']` set | resolve/fabricate | Downstream analytics require a target maturity |
| `strikes` strictly ascending | resolve/prefilter | Simplifies coverage & interpolation logic |
| `enriched` keys subset of `instruments` identifiers | enrich | Prevent orphan analytics |
| No duplicate instrument identifiers | fetch | Cache / metrics correctness |
| Terminal phases do not mutate prior phase data (idempotent view) | all | Replay & auditability |

## 3. Phase Inventory & Contracts
Each phase: `(ctx, settings, state) -> state` (returns same or new instance). Failures raise categorized exceptions OR append structured error markers.

| Phase | Purpose | Inputs (read) | Outputs (write) | Primary Events | Failure Category Examples |
|-------|---------|---------------|------------------|----------------|---------------------------|
## 4. Wave 1 Additions (2025-10-08)

### 4.1 Structured Phase Logging (Initial)
Logging helper `PhaseLogger` introduced (`src.collectors.pipeline.logging_schema`).

Event name grammar:
```
expiry.<phase>.<outcome>
```
Outcome in {`ok`,`warn`,`fail`,`skip`}.

Required keys per line: `phase, dt_ms, index, rule, outcome`.
Optional keys (current usage):
- strike_universe: `strike_count`, `strikes_itm`, `strikes_otm`
- enrich: `async_enabled`, `enriched_count`
- coverage: `strike_cov`, `field_cov`
- finalize: `partial`

Dedup suppresses identical consecutive WARN/FAIL records unless `G6_PIPELINE_LOG_DEDUP_DISABLE=1`.

### 4.2 Error Taxonomy (Skeleton)
`PhaseAbortError`, `PhaseRecoverableError`, `PhaseFatalError` defined (not yet fully wired into every phase – slated Wave 2 to replace broad exception blocks). Mapping plan:
- Abort -> INFO, skip downstream phases for that expiry.
- Recoverable -> WARNING, expiry excluded from final metrics but pipeline continues.
- Fatal -> ERROR, expiry annotated; may influence alert surface.

### 4.3 Parity Scoring Heuristic v1
Module: `src.collectors.pipeline.parity.compute_parity_score`.
Components (equal weight when present):
- `index_count` (length difference normalized)
- `option_count` (total options difference normalized; derived from per-index option_count when explicit missing)
- `alerts` (1 - symmetric difference / union of alert tokens)

Score output JSON shape:
```
{
  version: 1,
  score: <float 0..1>,
  components: { index_count: X, option_count: Y, alerts: Z },
  details: { indices: (L_legacy, L_pipeline), options_total: (O_legacy, O_pipeline), alerts: { union: U, sym_diff: D } },
  missing: [...],
  weights: { ... }
}
```

Promotion readiness provisional target: rolling 200-cycle score >= 0.995.

### 4.4 Benchmark Harness Skeleton
Script `scripts/bench_collectors.py` (dummy provider) produces relative p50/p95 deltas:
```
{
  config: {...},
  legacy: {p50_s, p95_s, mean_s, ...},
  pipeline: {...},
  delta: {p50_pct, p95_pct, mean_pct}
}
```
Expected stabilization criteria to adopt in Wave 2:
- p50 latency delta <= +5%
- p95 latency delta <= +10%

### 4.5 Pending (Wave 2 / 3)
- Replace broad try/except with taxonomy exceptions + outcome mapping.
- Add structured log coverage tests (assert every configured phase emitted per expiry).
- Extend parity scoring with optional strike coverage distribution component (behind flag `G6_PARITY_EXTENDED=1`).

## 5. Revised Promotion Gates (Draft)
1. Parity score threshold: >=0.995 (base components) for rolling window (N=200 cycles).
2. Performance: pipeline p50 <= legacy p50 * 1.05, p95 <= legacy p95 * 1.10.
3. Error taxonomy adoption: <2% of expiries marked fatal in observation window.
4. Alert parity: symmetric difference ratio < 0.02.
5. Rollback drill documented & validated (automated script TBD).

## 6. Next Documentation Updates
- Add detailed phase table enumerating phase ordering, outcome semantics, emitted metrics, and retry policy.
- Capture rollback procedure (environment flip + detection of legacy re-entry) with timeline.
- Insert metrics inventory section (existing + planned pipeline-specific histograms/counters).

| resolve | Determine target expiry (or fabricate candidate) | index, rule, provider expiries | expiry_date, flags.fabricated? | `expiry.resolve.ok|fabricated` | missing symbol (abort) |
| fetch | Retrieve raw instruments / quotes | expiry_date, provider client | instruments | `expiry.fetch.count` / `expiry.fetch.empty` | provider error (recoverable) |

## 7. Wave 2 Additions (2025-10-08)

### 7.1 Taxonomy Integration
The error taxonomy introduced in Wave 1 is now enforced in the orchestrator:

| Exception | Scope | Logging Outcome | Effect |
|-----------|-------|-----------------|--------|
| `PhaseRecoverableError` | Expiry-level phase (e.g. finalize) | `outcome=fail` (WARN) | Marks expiry failed; pipeline continues other expiries & indices |
| `PhaseFatalError` | Index-level critical (e.g. instrument universe failure) | `outcome=fatal` (ERROR) | Index marked failed; processing for that index halts |

Guidelines:
1. Prefer raising `PhaseRecoverableError` if subsequent expiries / indices can still provide value.
2. Escalate to `PhaseFatalError` only when upstream preconditions (instrument universe, expiry map) are invalid.
3. Avoid broad bare `except:` blocks; wrap and re-raise as taxonomy exception preserving original message context.

### 7.2 Phase Duration Metrics
Environment flag `G6_PIPELINE_PHASE_METRICS=1` enables histogram observation of per-phase wall durations via histogram `pipeline_phase_duration_seconds{phase=<name>}` (labels: phase). Failures and warnings still record duration.

### 7.3 Parity Scoring Invocation
When `G6_PIPELINE_PARITY_LOG=1` and a legacy baseline snapshot (`legacy_baseline`) is passed to `run_pipeline`, a structured parity score event is emitted with logger name `src.collectors.pipeline` and message `pipeline_parity_score`. Extra record fields: `score`, `components`, `missing`.

Invocation contract (minimal baseline):
```
legacy_baseline = { 'indices': [ {'index': 'NIFTY', 'status': 'OK', 'option_count': 123}, ... ] }
pipeline_result.indices -> collected indices_struct
```

### 7.4 Rollback Drill Script
Script: `scripts/rollback_drill.py`

Modes:
- Dry-run (default): enumerates intended actions.
- Execute (`--execute`): sets env flag `G6_PIPELINE_COLLECTOR=0` (in-memory prototype), performs legacy warm-run placeholder, emits structured completion log.

Planned Enhancements (Wave 3):
1. Persist pre-rollback parity score + anomaly summary to timestamped artifact.
2. Invoke actual legacy collector entrypoint with timeout & success criteria.
3. Metrics counter increment `pipeline_rollback_total`.

### 7.5 Test Coverage (Wave 2)
Added tests:
- `test_pipeline_logging.py`: validates phase logging presence, parity score emission, fatal vs success paths.
- `test_pipeline_taxonomy.py`: asserts recoverable (`finalize` injected) vs fatal (instrument fetch) behaviors and log patterns.

### 7.6 Operational Playbook Updates
Operator actions for parity investigation:
1. Enable parity logging: `export G6_PIPELINE_PARITY_LOG=1` (or Windows equivalent) and pass baseline snapshot to orchestrator wrapper.
2. Enable phase metrics: `export G6_PIPELINE_PHASE_METRICS=1` and ensure metrics facade histogram instantiation succeeds.
3. If elevated fatal rates (>2%), run rollback drill in dry-run then execute mode to validate path while pipeline still active.

### 7.7 Promotion Gate Status (Post Wave 2)
| Gate | Status | Notes |
|------|--------|-------|
| Parity score >= 0.995 | In progress | Emission added; baseline feed integration pending |
| Performance deltas | Pending | Benchmark harness exists; needs automated comparison harness (Wave 3) |
| Taxonomy adoption (<2% fatal) | Partial | Taxonomy applied to key early phases; remaining broad exceptions to refine |
| Alert parity | Pending | Alert aggregation intact; parity component uses alerts set if present |
| Rollback drill | Prototype | Script skeleton implemented; artifact persistence TBD |

---
_End Wave 2 additions_
| prefilter | Apply volume/OI/percentile/domain filters | instruments, settings | instruments (reduced), strikes | `expiry.prefilter.applied` | filter eliminates all (recoverable) |
| enrich | Build enriched analytics payload | instruments, strikes | enriched | `expiry.enrich.count` | calculation error (recoverable) |
| validate | Preventive data quality checks | enriched, settings | errors (maybe), flags.validation_failed? | `expiry.validate.fail|pass` | hard schema mismatch (abort) |
| salvage | Attempt foreign expiry salvage / recovery strategy | state + recovery strategy | flags.salvaged?, enriched | `expiry.salvage.applied` | salvage failure (recoverable) |
| coverage | Compute coverage ratios (strike completeness etc.) | strikes, enriched | expiry_rec.coverage | `expiry.coverage.metrics` | insufficient ladder (recoverable) |
| iv | Implied volatility calculations | enriched | enriched (iv fields) | `expiry.iv.metrics` | numerical fail (recoverable) |
| greeks | Greeks derivation | enriched | enriched (delta,gamma,theta,vega) | `expiry.greeks.metrics` | math domain error (recoverable) |
| persist | Persist snapshot (sim or real sink) | expiry_rec, enriched | side effects, flags.persisted? | `expiry.persist.ok|fail` | sink write fail (fatal) |
| classify | Tag expiry category / regime | expiry_rec, coverage | expiry_rec.classification | `expiry.classify.ok` | rule mismatch (recoverable) |
| snapshot | Build public snapshot structure | prior state | expiry_rec.snapshot | `expiry.snapshot.ok` | serialization fail (recoverable) |
| summarize | Final log & metrics emission | entire state | none (terminal) | `expiry.complete` | aggregate metrics fail (ignore) |

## 4. Error Taxonomy (Planned Application)
| Exception | Semantics | Handling |
|-----------|----------|----------|
| PhaseRecoverableError | Phase failed but pipeline can proceed or salvage | Record error, attempt salvage/continue |
| PhaseAbortError | Expected abort (e.g., no viable instruments) | Stop further phases, treat gracefully |
| PhaseFatalError | Unexpected invariant violation | Terminate processing, escalate metrics/alert |

## 5. Feature Flag Matrix
| Flag | Purpose | Modes |
|------|---------|-------|
| `G6_COLLECTOR_PIPELINE_V2` | Enable shadow phased pipeline execution | 0/1 |
| `G6_COLLECTOR_PIPELINE_AUTHORITATIVE` | Make phased pipeline authoritative for outputs | 0/1 |
| `G6_COLLECTOR_PIPELINE_LEGACY_FORCE` | Force legacy even if authoritative flag set (rollback) | 0/1 |
| `G6_RECOVERY_STRATEGY_LEGACY` | Wire RecoveryStrategy into legacy path | 0/1 |
| `G6_BENCH_WRITE` | Allow writing benchmark artifacts | 0/1 |
| `G6_TRACE_COLLECTOR_FORCE_WARN` | Promote trace debug lines to WARN | 0/1 |

Rollback recipe: set `G6_COLLECTOR_PIPELINE_LEGACY_FORCE=1` (takes precedence), optionally disable authoritative flag, preserving shadow run for diagnostics.

## 6. Metrics Specification (Key Subset)
| Metric | Type | Labels | Description | Cutover Watch |
|--------|------|--------|-------------|---------------|
| `collector_expiry_count` | Counter | index, mode(legacy|v2) | Number of expiries processed | Ratio ≈1:1 |
| `collector_option_count` | Counter | index, mode | Total option instruments considered | Delta pct |
| `collector_option_enriched` | Counter | index, mode | Options with enrichment complete | Coverage delta |
| `collector_salvage_applied_total` | Counter | index, mode | Salvage operations executed | No unexpected spike |
| `collector_recovery_invoked_total` | Counter | index, mode | RecoveryStrategy invocations | Stable/low |
| `collector_phase_latency_ms` | Histogram | phase, mode | Per-phase latency | Compare medians |
| `collector_cycle_latency_ms` | Histogram | mode | End-to-end cycle latency | +5% budget |
| `collector_phase_fail_total` | Counter | phase, category | Phase failures by taxonomy | No new fatal |
| `collector_memory_rss_mb` | Gauge | mode | RSS snapshot (optional) | < +10MB delta |

## 7. Structured Events (Schema)
Format: `event_name key=value ...` (single line). Naming: `expiry.<phase>.<outcome>` or `provider.<domain>.<action>`.

Examples:
```
expiry.resolve.ok index=NIFTY rule=next_week expiry=2025-10-09 fabricated=0
expiry.fetch.count index=NIFTY rule=next_week instruments=354 ms=18.5
expiry.prefilter.applied index=NIFTY before=354 after=280 removed=74 volume_min=1000 oi_min=500
expiry.validate.fail index=BANKNIFTY issues=missing_iv,low_strike_coverage
expiry.salvage.applied index=NIFTY reason=foreign_expiry delta_options=24
expiry.complete index=NIFTY options=280 enriched=270 salvage=1 ms=152.3
```

## 8. Parity Gates (Authoritative Cutover Thresholds)
All thresholds evaluated over rolling window (≥ 3 trading days) per index.
| Dimension | Metric / Computation | Threshold |
|-----------|----------------------|-----------|
| Option universe size | `abs(v2_options - legacy_options) / legacy_options` | < 1.0% |
| Enrichment coverage | `(v2_enriched / v2_options) - (legacy_enriched / legacy_options)` | ±0.5 pp |
| Salvage frequency | `v2_salvage_rate - legacy_salvage_rate` | ≤ +0.2 pp |
| Phase fatal errors | count(v2_fatal) | 0 (sustained) |
| Median cycle latency | `median_ms_v2 - median_ms_legacy` | ≤ +5% |
| 95p phase latency | per phase delta | ≤ +10% (exceptions: enrich ≤ +15%) |
| Memory RSS delta | `rss_v2 - rss_legacy` | ≤ +10 MB |

## 9. Performance Baseline Capture
Procedure:
1. Enable shadow (`G6_COLLECTOR_PIPELINE_V2=1`) in staging for full market session.
2. Run benchmarking harness (`scripts/benchmarks/provider_parity.py`) capturing sizes 50/200/500.
3. Store JSON artifact (if `G6_BENCH_WRITE=1`) for regression comparison.
4. Populate dashboard panels: cycle latency (median & 95p), per-phase latency, option count delta, enrichment coverage delta.

## 10. Cutover Checklist

### Historical Note (Synthetic Phase Removal – Oct 2025)
The previously documented `synthetic` phase (responsible for injecting fabricated quotes on empty enrichment results) was removed to eliminate silent data fabrication. Empty `enriched` sets now flow directly into coverage and alert logic. Any historical references to `expiry.synthetic.applied` events or `flags.synthetic` markers should be considered obsolete.
Pre-Cutover (all MUST be true):
1. All parity gates (Section 8) satisfied for 3 consecutive sessions.
2. No v2-exclusive fatal errors in last 3 sessions.
3. Dashboard panels green: option count delta <1%, enrichment delta within ±0.5pp.
4. Alert rules configured (Section 11) and silent (no unresolved pages) for 2 sessions.
5. Rollback drill executed in staging (flip legacy force flag & observe recovery < 1 cycle).
6. Documentation updated (`rational.md` + this file) with current hash of benchmark artifact.
7. Test suite green; added tests for any newly introduced invariants.

Activation Steps:
1. Set `G6_COLLECTOR_PIPELINE_AUTHORITATIVE=1` (retain shadow for 1 day by also keeping `G6_COLLECTOR_PIPELINE_V2=1`).
2. Monitor high-frequency dashboard for first 30 mins (option count & latency charts).
3. If stable after 1 full session, remove legacy shadow invocation (unset `G6_COLLECTOR_PIPELINE_V2`).

## 11. Rollback Plan
Trigger Conditions:
- Option count delta breaches 2% (5-minute moving window) OR
- Any PhaseFatalError rate > 0 OR
- Median cycle latency regression >15% sustained 15 minutes OR
- Enrichment coverage drops >1 pp vs legacy.

Actions (in order):
1. Set `G6_COLLECTOR_PIPELINE_LEGACY_FORCE=1` (immediate take effect next cycle).
2. Keep v2 shadow for diagnostics (leave `G6_COLLECTOR_PIPELINE_V2=1`).
3. Capture diagnostic snapshot & recent logs; open incident ticket with metrics screenshots.
4. Triage root cause; patch behind feature flag; re-run parity window.

Recovery SLO: < 5 minutes from detection to legacy enforcement.

## 12. Alerting Rules (Indicative Prometheus)
```
ALERT OptionCountParityDrift
  IF abs(collector_option_count{mode="v2"} - collector_option_count{mode="legacy"}) / collector_option_count{mode="legacy"} > 0.02
  FOR 5m
  LABELS { severity="page" }
  ANNOTATIONS { summary="Option count parity drift >2%" }

ALERT V2FatalErrors
  IF increase(collector_phase_fail_total{category="fatal"}[5m]) > 0
  FOR 0m
  LABELS { severity="page" }
  ANNOTATIONS { summary="V2 fatal phase errors detected" }

ALERT CycleLatencyRegression
  IF (quantile_over_time(0.5, collector_cycle_latency_ms{mode="v2"}[15m]) - quantile_over_time(0.5, collector_cycle_latency_ms{mode="legacy"}[15m])) / quantile_over_time(0.5, collector_cycle_latency_ms{mode="legacy"}[15m]) > 0.15
  FOR 10m
  LABELS { severity="warn" }
  ANNOTATIONS { summary="Median cycle latency regression >15%" }
```

## 13. Post-Cutover Decommission
| Step | Description | Flag / Action | Timing |
|------|-------------|---------------|--------|
| 1 | Remove legacy salvage inline logic | Drop dead code | +1 week |
| 2 | Remove dynamic metrics fallbacks | Delete compatibility shim | +1 week |
| 3 | Retire legacy provider shims | Remove deprecated exports | +2 weeks |
| 4 | Remove shadow invocation path | Delete branching code | +2 weeks |
| 5 | Final metrics cardinality audit | Confirm no orphan metrics | +2 weeks |

## 14. Risks & Mitigations (Focused)
| Risk | Mitigation | Metric / Event |
|------|------------|----------------|
| Hidden dependency on legacy log string parsing | Dual emit during transition | event translation counters |
| Salvage logic behavioral drift | Explicit salvage rate metric & diff | salvage delta panel |
| Latency inflation from phase churn | Per-phase histogram + gating | phase_latency_ms 95p |
| Memory growth due to state copies | RSS gauge periodic sample | memory_rss_mb delta |

## 15. Implementation Tracking (Living)
| Item | Status | Notes |
|------|--------|-------|
| Phase contracts documented | DONE | This file |
| Benchmark harness | DONE | scripts/benchmarks/provider_parity.py |
| Metrics spec alignment | PARTIAL | Some collectors metrics pending rename |
| Structured events complete | PARTIAL | Need remaining phase events (iv, greeks, persist) |
| Error taxonomy applied | PLANNED | Exceptions mapped but not raised yet |

## 16. References
- `rational.md` – strategic rationale & phased roadmap
- `scripts/benchmarks/provider_parity.py` – parity & performance harness
- Provider modular components in `src/provider/`

---
This document is authoritative for go/no-go decisions; updates require code review + observability sign-off.
