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

| Phase | Purpose / Contract Summary | Inputs (read) | Outputs / State Mutations | Primary Structured Events (examples) | Failure Category Examples | Retry / Gating Notes |
|-------|-----------------------------|---------------|---------------------------|--------------------------------------|---------------------------|----------------------|
| resolve | Determine target expiry; fabricate if provider gap. Ensures `expiry_date` or sets `flags.fabricated`. | index, rule, provider expiries catalogue | `expiry_date` (non-null) OR `flags.fabricated=1`; may seed initial `strikes` list. | `expiry.resolve.ok`, `expiry.resolve.fabricated`, `expiry.resolve.abort` | Abort: no viable expiries; Recoverable: transient provider error; Fatal: invalid rule mapping | No retry inside phase (idempotent); upstream loop may re-enter next cycle. |
| fetch | Pull raw instrument & quote universe (option chain). Must preserve ordering & uniqueness. | expiry_date, provider client/session, index metadata | `instruments` list (deduped, ordered), may annotate `errors` on soft gaps | `expiry.fetch.count`, `expiry.fetch.empty` | Recoverable: provider timeout/partial; Fatal: structural schema mismatch | Single attempt; upstream may implement exponential backoff across cycles. |
| prefilter | Reduce universe by liquidity / domain rules; maintain consistent ladder shape. | instruments, settings thresholds | filtered `instruments`, pruned `strikes` list | `expiry.prefilter.applied` | Recoverable: filter eliminates all (empty ladder) | If empty result, downstream may salvage (salvage phase) before abort. |
| enrich | Build analytics payload (greeks-ready enriched quotes). | instruments (filtered), strikes | `enriched` mapping keyed by instrument id | `expiry.enrich.count`, `expiry.enrich.partial` | Recoverable: calculation subset failures; Fatal: systemic calculator init failure | Partial progress allowed; failures recorded per instrument. |
| validate | Enforce data quality & structural invariants (strike continuity, coverage). | enriched, strikes, settings | `errors` appended; may set `flags.validation_failed` | `expiry.validate.pass`, `expiry.validate.fail` | Recoverable: coverage shortfall; Abort: fabricated path invalid; Fatal: invariant corruption | No mutation rollback; downstream phases may consult flags. |
| salvage | Attempt recovery (foreign expiry mapping, synthetic ladder). | state (possibly failed), recovery strategy impl | Potentially adjusted `strikes`, additional `enriched` entries, `flags.salvaged` | `expiry.salvage.applied`, `expiry.salvage.skip` | Recoverable: salvage attempt fails; Fatal: corrupt intermediate state | Guarded by strategy availability; executes only if prior deficiencies detected. |
| coverage | Compute strike / field coverage metrics; populate summary record. | strikes, enriched | `expiry_rec.coverage` dict | `expiry.coverage.metrics` | Recoverable: insufficient ladder; Fatal: impossible metrics math | Pure read/derive; no retries needed. |
| iv | Implied volatility estimations; tolerant of per-instrument math errors. | enriched (prices, strikes) | augmented `enriched` (iv fields) | `expiry.iv.metrics` | Recoverable: engine numeric failure; Fatal: misconfigured model params | Per-instrument guarded; continues on individual failures. |
| greeks | Derive standard greeks; similar tolerances to iv phase. | enriched (with iv) | augmented `enriched` (delta,gamma,theta,vega) | `expiry.greeks.metrics` | Recoverable: divide-by-zero / math domain | Per-instrument guarded; continues on failures. |
| persist | Emit snapshot to storage / sink (simulation or real). | expiry_rec, enriched snapshot | side effects; may set `flags.persisted` | `expiry.persist.ok`, `expiry.persist.fail` | Recoverable: transient sink error; Fatal: serialization corruption | Optional internal retry (short) if sink transient flagged. |
| classify | Apply regime / category tags for expiry analytics. | expiry_rec.coverage, enriched stats | `expiry_rec.classification` | `expiry.classify.ok`, `expiry.classify.fail` | Recoverable: rules mismatch; Fatal: classifier config missing | Deterministic; no internal retry. |
| snapshot | Construct outward-facing payload structure. | prior state (expiry_rec, enriched) | `expiry_rec.snapshot` structure | `expiry.snapshot.ok`, `expiry.snapshot.fail` | Recoverable: serialization corner-case | One-shot JSON build; upstream may still finalize partial. |
| summarize | Final aggregation + metrics emission + parity hook. | entire state, metrics facade, legacy baseline (optional) | metrics side effects; parity log event (if enabled); final `errors` consolidated | `expiry.complete`, `pipeline_parity_score` (conditional) | Recoverable: metrics emission failure; Fatal: none (should degrade gracefully) | Last phase; never retries; ensures cleanup logging. |
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

### 4.6 Retry Policy & Backoff Strategy (Wave 4 – W4-17)

This section codifies per-phase retry expectations, metrics, and operator tuning levers formalized in Wave 4.

#### Principles
1. Avoid hidden unbounded loops inside phases; prefer single attempt or per-instrument guards.
2. Surface every retry via explicit metrics (attempt, retry, backoff histogram) for tuning & anomaly detection.
3. Exponential backoff + jitter + ceiling (5s) preserves responsiveness while dampening transient bursts.

#### Metrics
| Metric | Purpose |
|--------|---------|
| `g6_pipeline_phase_attempts{phase}` | Total phase invocations (attempt 1 + retries) |
| `g6_pipeline_phase_retries{phase}` | Retry attempts only (attempt >1) |
| `g6_pipeline_phase_retry_backoff_seconds{phase}` | Distribution of applied sleep delays |
| `g6_pipeline_phase_last_attempts{phase}` | Attempts used in most recent cycle |
| `g6_pipeline_phase_outcomes{phase,final_outcome}` | Outcome distribution (ok|fail|fatal|abort) |

#### Environment
| Env Var | Default | Description |
|---------|---------|-------------|
| `G6_RETRY_BACKOFF` | 0.2 | Base backoff seconds feeding exponential schedule (capped) |

(Jitter amplitude & cap currently fixed; future flags may expose.)

#### Phase Policies
| Phase | Internal Retries? | Mode | Notes |
|-------|-------------------|------|-------|
| resolve | No | Single | Deterministic; re-run needs fresh provider state |
| fetch | Yes (exp backoff) | Whole-phase | Transient provider/network issues only; fatal schema aborts |
| prefilter | No | Transform | Deterministic filtering |
| enrich | Per-instrument guards | Sub-unit | Each instrument independent; failing ones skipped |
| validate | No | Check | Invariants deterministic |
| salvage | No | Strategy | Idempotent; repeat adds no value |
| coverage | No | Derive | Pure compute |
| iv/greeks | Per-instrument guards | Sub-unit | Numeric instability isolated |
| persist | Optional bounded | Whole-phase | Short retry for transient IO only |
| classify | No | Deterministic | Stable rule eval |
| snapshot | No | Serialize | Deterministic JSON assembly |
| summarize | No | Aggregate | Final stage should degrade gracefully |

#### Backoff Mechanics
Delay = base * 2^(attempt-1) + jitter (0..base) capped at 5s. Observed in `g6_pipeline_phase_retry_backoff_seconds`.

#### Taxonomy Interaction
- `PhaseFatalError` aborts immediately (no retries).
- `PhaseRecoverableError` may trigger retry (fetch) or be logged & skipped (enrich per-instrument).
- Abort conditions (e.g. empty viable expiries) bypass retries; external state must change.

#### Operator Guidance
1. Watch sustained growth in `pipeline_phase_retries{phase="fetch"}` + latency drift.
2. Adjust `G6_RETRY_BACKOFF` cautiously; too low amplifies provider pressure, too high increases recovery latency.
3. Track p95 of backoff histogram for early provider responsiveness signals.
4. Correlate retries with outcome counters to distinguish systemic vs transient issues.

#### Future Enhancements
- Configurable jitter & cap.
- Adaptive scaling based on recent failure ratio.
- Structured anomaly on retry density spikes.

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
4. Alert parity: weighted alert mismatch fraction < 0.02 (see Wave 3 alert weighting); fallback symmetric diff ratio < 0.02 if weighting disabled.
5. Rollback drill documented & validated (automated script + artifact & counter emitted).

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

## 8. Wave 3 Additions (2025-10-08)

### 8.1 Extended Parity (Version 2)
Feature flag: `G6_PARITY_EXTENDED=1` enables parity score version `2` adding `strike_coverage` component (average strike coverage similarity). If disabled, version `1` emitted. Existing components unchanged.

### 8.2 Rolling Parity Window
Env flag: `G6_PARITY_ROLLING_WINDOW=<N>` (N>1) records recent parity scores and logs rolling average (`rolling_avg`, `rolling_count`, `rolling_window`). When metrics available a gauge `g6_pipeline_parity_rolling_avg` is emitted.

### 8.3 Benchmark Delta Automation
Script: `scripts/bench_delta.py`
Runs internal benchmark harness, computes p50/p95/mean deltas, enforces thresholds (env override or CLI), optional metrics emission (flag `G6_BENCH_METRICS=1`), and writes JSON artifact. Supports CI gating.

#### 8.3.1 Runtime Benchmark Cycle Integration (Wave 4 – W4-09)
Rationale: Continuous visibility into performance deltas during normal operation without waiting for scheduled CI runs. Provides early detection of regressions introduced by configuration or market regime shifts.

Implementation: Helper `_maybe_run_benchmark_cycle` invoked at the end of each pipeline cycle (post main work, pre-return). It executes a lightweight in-process run of `scripts.bench_collectors` with a small cycle count and emits Gauges mirroring those produced by `bench_delta`.

Environment Flags:
- `G6_BENCH_CYCLE=1` – master enable (disabled by default)
- `G6_BENCH_CYCLE_INTERVAL_SECONDS` – minimum seconds between benchmark executions (default 300)
- `G6_BENCH_CYCLE_INDICES` – indices spec (default `NIFTY:1:1`)
- `G6_BENCH_CYCLE_CYCLES` – measurement cycles (default 8, capped at 40)
- `G6_BENCH_CYCLE_WARMUP` – warmup cycles (default 2, capped at 10)

Metrics Emitted (Gauge):
- `g6_bench_legacy_p50_seconds`
- `g6_bench_legacy_p95_seconds`
- `g6_bench_pipeline_p95_seconds`
- `g6_bench_delta_p50_pct`
- `g6_bench_delta_p95_pct`
- `g6_bench_delta_mean_pct`

Safety & Overhead:
- Timestamp guard prevents re-run before interval elapses.
- All failures suppressed with debug logs (no impact to main cycle path).
- Upper bounds on cycles/warmup minimize latency impact (< few ms typical under dummy provider scenario).

Test: `tests/test_bench_cycle_integration.py` uses monkeypatch to simulate harness & prometheus client ensuring gauges populated with expected values.

#### 8.3.2 Benchmark P95 Regression Threshold Alert (Wave 4 – W4-10)
Purpose: Automated early warning when pipeline p95 latency regresses beyond an operator-configured percentage relative to legacy collector baseline.

Environment Flag:
- `G6_BENCH_P95_ALERT_THRESHOLD` – Numeric (float) percentage allowed regression (e.g., `25` for 25%). When set, a gauge `g6_bench_p95_regression_threshold_pct` is emitted each benchmark cycle or eagerly created if the cycle is skipped due to interval gating.

Metrics Consumed:
- `g6_bench_delta_p95_pct` (positive means pipeline slower; negative implies improvement)
- `g6_bench_p95_regression_threshold_pct` (configured threshold)

Prometheus Alert Rule (`prometheus_alerts.yml`):
```
alert: BenchP95RegressionHigh
expr: (g6_bench_delta_p95_pct > g6_bench_p95_regression_threshold_pct) and (g6_bench_p95_regression_threshold_pct >= 0)
for: 5m
labels:
  severity: warning
  category: performance
```

Behavior:
* Fires if the delta remains above threshold for 5 minutes (scrape interval aggregated via Prometheus for() semantics).
* Guard term `(g6_bench_p95_regression_threshold_pct >= 0)` prevents accidental firing when threshold unset or negative due to misconfiguration.

Implementation Notes:
* Threshold gauge created early on `_maybe_run_benchmark_cycle` invocation to allow alert to evaluate even during intervals without a fresh benchmark run (delta gauge retains last value).
* Gauge value updated only if env var parses as float; parse failures logged at debug and skipped.

Testing:
Future Enhancements:
* Extend to p50 and mean thresholds with independent env vars.
* Add CI pre-merge gate reading last N minutes of scraped metrics to block merges crossing threshold prior to deploy.
* Adaptive thresholding (dynamic baseline window) if legacy path retired.

### 8.4 Rollback Drill Enhancements
`scripts/rollback_drill.py` now:
- Persists artifact (parity snapshot + anomaly summary) to timestamped file (`--artifact-dir`).
- Increments counter `g6_pipeline_rollback_drill_total` (name via metrics facade).
- Attempts parity snapshot capture before disabling pipeline.

### 8.5 Taxonomy Counters Exposure
Added counters:
- `pipeline_expiry_recoverable_total`
- `pipeline_index_fatal_total`
Public facade helpers `dump_metrics` / `get_counter` ensure tests can discover these even if registry initialization race occurs.

### 8.6 Alert Parity Weighting & Detailed Component
Parity scorer now consumes structured alert categories when available (snapshot `alerts` block). Environment variable `G6_PARITY_ALERT_WEIGHTS` allows severity weighting (format: `cat1:2,cat2:0.5`). Weighted normalized difference becomes alert parity component (0 perfect). Details surface per-category legacy vs pipeline counts, weight, and normalized diff. If weights or structured categories absent, symmetric difference fallback used.

New gauge: `g6_pipeline_alert_parity_diff` (weighted normalized alert mismatch fraction) emitted when parity logging enabled and metrics available.

### 8.7 Documentation & Phase Contract Table
Inserted comprehensive phase contract table (Section 3) enumerating inputs, mutations, primary events, failure categories, and retry/gating notes.

### 8.8 Promotion Gate Adjustments
- Alert parity gate updated to use weighted mismatch fraction when weighting enabled.
- Rolling parity average (window 200 target) emphasized for readiness evaluation.

### 8.9 Pending (Wave 4 Preview)
- Alert taxonomy severity normalization & UI surfacing.
- Phase-level retry/backoff strategy tuning & metrics.
- Metrics cardinality audit + pruning unsupported legacy shims.
## 4. Error Taxonomy (Planned Application)
| Exception | Semantics | Handling |
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
