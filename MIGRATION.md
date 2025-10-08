# Migration Guide

This guide documents schema, configuration, and behavioral changes introduced in the recent platform evolution so existing users can upgrade smoothly.
> HISTORICAL: This section documents completed removals. Older rows may be pruned or archived if this table grows large.

## Scope
Applies to deployments moving from the legacy multi‑row overview & no‑Greeks system to the unified orchestrator with IV estimation, Greeks, and aggregated overview snapshots.

## Summary of Changes
| Area | Change | Type | Action Required |
|------|--------|------|-----------------|
| Overview snapshots | Consolidated to one row/point per index per cycle | Behavioral | Adjust any tooling expecting multiple rows |
| Expiry completeness | Added `expected_mask`, `collected_mask`, `missing_mask`, plus counts | Additive | Optional: leverage for data quality checks |
| CSV columns | Added `rho`, clarified naming (internal mapping of legacy `strike`->`index_price`) | Additive / Clarifying | Update downstream parsers if reading new columns |
| IV estimation | Added Newton–Raphson solver (configurable) | Additive | Enable via `greeks.estimate_iv` |
| Greeks computation | Added delta, gamma, theta, vega, rho | Additive | Enable via `greeks.enabled` |
| Influx fields | Added iv + Greeks fields on `option_data` | Additive | Update dashboards to include new series |
| Metrics | Added IV success/failure counters & avg iterations gauge | Additive | Scrape new metrics endpoints |
| CLI flags | Deprecated for greeks/IV control | Breaking (soft) | Remove reliance on CLI flags; use JSON config |
| Orchestrator runner | New preferred entry `scripts/run_orchestrator_loop.py` with generalized `run_loop` + `G6_LOOP_MAX_CYCLES` | Additive | Migrate any automation from legacy `unified_main` / `run_live.py` |
| Legacy loop deprecation | One-time warning on legacy `collection_loop` usage | Deprecation | Plan removal after 2 stable releases |
| `scripts/run_live.py` | Removed | Removal | Use orchestrator runner (`scripts/run_orchestrator_loop.py`) |

### Phase 0 Configuration Rationalization (Completed)
Introduced `CollectorSettings` (`src/collectors/settings.py`) providing a single-pass hydration of env-driven collector knobs:
`G6_FILTER_MIN_VOLUME`, `G6_FILTER_MIN_OI`, `G6_FILTER_VOLUME_PERCENTILE` (stub), `G6_FOREIGN_EXPIRY_SALVAGE`, `G6_DISABLE_SALVAGE`, `G6_RETRY_ON_EMPTY`, `G6_TRACE_COLLECTOR`, `G6_DOMAIN_MODELS`.

Integration Details:
- Hydrated once per cycle inside `run_unified_collectors` and attached to cycle context (`ctx.collector_settings`).
- `expiry_processor.process_expiry` consumes settings for basic filtering & salvage gating; retains legacy env fallback if settings absent.
- Salvage logic prefers `foreign_expiry_salvage` then falls back to broader `salvage_enabled` to preserve prior behavior when only the generic flag existed.
- Local ad-hoc env parsing removed from expiry path (except fallback guard) reducing repeated `os.getenv` overhead and divergence risk.

Behavior Parity:
- If the settings module import fails, legacy behavior (direct env lookups) continues—no hard dependency introduced.
- Filter order unchanged (applied before data quality checks as previously).
- Percentile threshold currently inert unless explicitly set; cutoff computation guarded for low sample sizes.

Next Steps (Phase 1 Preview):
- Thread settings into forthcoming shadow pipeline phases for strike span heuristics & advanced salvage tuning.
- Add metrics surfacing active thresholds and salvage decisions for observability.
- Deprecate direct env lookups after stable soak (target: remove fallback guards post 2 release cycles).

### Phase 1 Shadow Pipeline (Historical)
Shadow execution scaffolding added under `src/collectors/pipeline/`:
- `state.py` (`ExpiryState`) captures structural fields for parity comparison.
- `phases.py` implements four initial phases: resolve, fetch, prefilter clamp reuse, enrich.
- `shadow.py` orchestrates and logs either `expiry.shadow.ok` or a compact `expiry.shadow.diff` with differing core counts.

Activation Flag: set `G6_COLLECTOR_PIPELINE_V2=1` (hydrates `CollectorSettings.pipeline_v2_flag`). Legacy path remains authoritative; shadow errors are swallowed after DEBUG log.

Current Diff Surface: `expiry_date`, `strike_count`, `instrument_count`, `enriched_keys`, plus strike list (length + identity) logged when mismatched.

Upcoming (Phase 2) original plan (historical): layer synthetic fallback, preventive validation, salvage & recovery strategy abstraction. (Synthetic fallback portion was later removed entirely in Oct 2025; remaining items proceeded without it.)

### Phase 2 Shadow Pipeline Enhancements (Completed; synthetic later removed)
Added preventive validation (`preventive_validate`) and salvage rehydration logic (synthetic fallback was temporarily present in this phase but has since been removed). Key behaviors (synthetic bullets removed):
- Preventive validation runs even on empty enriched sets capturing issues like `foreign_expiry` or insufficient strike coverage.
- Salvage attempts rehydration of a small set (<=3) of foreign-expiry rows without marking salvage when disabled, preserving parity neutrality.
<!-- (Removed Oct 2025) Synthetic fallback previously injected a minimal enriched row when enrichment returned empty. Eliminated to avoid silent fabricated data; empty states now surface directly to coverage/alert logic. -->
Parity hash introduced (initial version) to compactly fingerprint core structural fields for logging/metrics correlation.

### Phase 3 Shadow Pipeline Observational Extensions (In Progress)
New downstream observational (non-authoritative) phases appended after enrichment (synthetic fallback removed):
- `coverage`: computes basic strike/field coverage metrics stored under `meta['coverage']`.
- `iv`: placeholder IV estimation metadata under `meta['iv_phase']` (delegates to modular or legacy helpers as available).
- `greeks`: placeholder Greeks computation metadata under `meta['greeks_phase']`.
- `persist_sim`: simulated persistence summary (option count, synthetic PCR) under `meta['persist_sim']` (no side-effects).

Parity Hash v2:
- Extended hash payload now incorporates coverage and simulated persistence derived metrics plus a truncated head of strikes for limited identity signal.
- Stored in `meta['parity_hash_v2']` (16 hex chars) with deterministic defaults (0 for missing optional metrics) to avoid None/absence drift.
- Logging lines `expiry.shadow.ok` / `expiry.shadow.diff` now include the v2 hash; existing diff surface fields unchanged (`DIFF_FIELDS` remains minimal to reduce log noise).

Rationale:
- Observational phases allow early detection of divergence in downstream analytics readiness before activating the shadow pipeline as a functional replacement.
- Versioned hash ensures future additions (e.g., IV or Greeks counts) can evolve without destabilizing existing log parsers.

Next (Phase 4 Preview):
- Potential expansion of diff surface to include select coverage metrics once stability confirmed.
- Metrics emission for shadow vs legacy structural parity rates (synthetic fallback frequency metric removed post-removal).
- Gradual gating option for switching authoritative path after sustained parity confidence.

### Phase 4 Shadow Pipeline Gating & Promotion (Active / Incremental)
Focus: Turning structural parity confidence into actionable promotion decisions with staged safety (dry run → canary → full promotion) and hysteresis.

Implemented Components:
- Parity hash v2 strike canonicalization (sorted head) ensuring deterministic structural fingerprint.
- Structural diff metadata: `meta['parity_diff_fields']`, `meta['parity_diff_count']` consumed by gating.
- Gating controller modes: `off`, `dryrun`, `canary`, `promote`.
- Rolling window parity ratio tracking with configurable window & minimum sample gate.
- Canary & promotion thresholds with separate targets (`canary_target` < `parity_target`).
- Hysteresis via consecutive ok/fail streak counters (`ok_streak`, `fail_streak`) to avoid flapping.
- Protected field enforcement: diffs on `expiry_date` or `instrument_count` block promotion.
- Decision schema (stored under `meta['gating_decision']`):
  ```json
  {
    "mode": "dryrun|canary|promote|off",
    "promote": false,
    "canary": false,
    "parity_ok_ratio": 0.992,
    "window_size": 187,
    "diff_count": 0,
    "protected_diff": false,
    "ok_streak": 42,
    "fail_streak": 0,
    "reason": "canary_active|parity_target_met|waiting_hysteresis|..."
  }
  ```

Environment Flags (current):
- `G6_SHADOW_GATE_MODE` = `off|dryrun|canary|promote`
- `G6_SHADOW_PARITY_WINDOW` (int, default 200)
- `G6_SHADOW_PARITY_MIN_SAMPLES` (int, default 30)
- `G6_SHADOW_PARITY_CANARY_TARGET` (float 0-1, default 0.97)
- `G6_SHADOW_PARITY_OK_TARGET` (float 0-1, default 0.99)
- `G6_SHADOW_PARITY_OK_STREAK` (int, default 10) consecutive ok samples required for promotion
- `G6_SHADOW_PARITY_FAIL_STREAK` (int, default 5) consecutive fails to clear canary/promotion
 - `G6_SHADOW_CANARY_INDICES` (comma list allowlist; if set overrides percentage sampling)
 - `G6_SHADOW_CANARY_PCT` (float 0-1 subset sampling when allowlist not provided; default 1.0)

Promotion Logic Summary:
1. Samples < `min_samples` → `reason=insufficient_samples` (no canary/promo).
2. Ratio ≥ `canary_target` and no protected diff → `canary=true` (modes: canary/promote).
3. In `promote` mode: require (a) `canary=true`, (b) ratio ≥ `parity_target`, (c) `ok_streak` ≥ `ok_hysteresis`, (d) no protected diff → `promote=true`.
4. Any protected diff immediately blocks promotion (`reason=protected_block`).
5. `fail_streak` ≥ `fail_hysteresis` while in canary/promote downgrades / prevents advancement (`reason=fail_hysteresis`).
6. Else remain observing (`reason=waiting_hysteresis`).

Not Yet Implemented (Planned Enhancements):
- Canary subset scoping via adaptive dynamic lists (current static allowlist & pct implemented).
- Metrics emission for gating decisions (counters + histograms).
  * Implemented: `g6_shadow_gating_decisions_total{index,rule,mode,reason}` and `g6_shadow_gating_promotions_total{index,rule}` counters; parity ratio/window gauges already present. Future: histograms / churn.
- Hash churn metric (distinct parity hashes per window) for structural volatility.
- Rollback diff threshold flag for automatic demotion.
- Extended protected field override flag (`G6_SHADOW_PROTECTED_FIELDS`).

Operational Rollout Recommendation:
1. Start with `dryrun` for ≥ full trading day; record baseline parity ratio & streak distribution.
2. Move to `canary` targeting a small, stable index set (temporary manual allowlist until flag lands) validating no protected diffs emerge.
3. Enable `promote` only after sustained ratio ≥ target and stable ok streak; monitor for immediate fail streak regressions.
4. Keep rollback procedure documented (set `G6_SHADOW_GATE_MODE=off`) during initial promotion release.

Testing:
- Added unit tests covering dryrun, canary activation, promotion hysteresis, and protected field blocking.
- Future tests planned for rollback & churn metrics once implemented.

Rollback Safety:
Leaving `G6_SHADOW_GATE_MODE` unset or `off` keeps behavior identical to prior phase (gating decision inert).

Next Steps:
- Add decision log line `shadow.gate.decision` (structured) for audit.
- Wire metrics adapter for parity_ok/ diff counters + streak gauges.
- Implement canary subset env parsing and safe allowlist enforcement.

### Phase 5 Shadow Gating Churn & Rollback (Active)
Focus: Introduce structural volatility insight and automatic rollback guardrails to further de-risk promotion.

New Decision Fields (added to `meta['gating_decision']`):
- `protected_in_window`: Count of samples in rolling window whose diff touched a protected field.
- `hash_distinct`: Number of distinct parity hashes observed in the current window.
- `hash_churn_ratio`: `hash_distinct / window_size` (volatility indicator 0-1).

Rollback Logic:
- Env `G6_SHADOW_ROLLBACK_PROTECTED_THRESHOLD` (int, default effectively disabled with large sentinel) triggers an immediate rollback decision (`reason=rollback_protected`) when the count of protected diffs within the active window reaches or exceeds the threshold.
- Rollback short-circuits promotion and canary flags for the cycle (promotion remains false even if parity targets & hysteresis satisfied).

Churn Metric Rationale:
- High churn (many distinct hashes relative to window) can signal unstable structural footprint even if diff count is frequently zero (e.g., rapid strike list oscillation with salvage/synthetic interplay). Operators can watch `g6_shadow_hash_churn_ratio` to tune window size or investigate upstream volatility.

Prometheus Metrics Added:
- Gauge `g6_shadow_hash_churn_ratio{index,rule}`: distinct parity hash ratio (0-1).
- Counter `g6_shadow_rollbacks_total{index,rule,reason}`: counts rollback events (currently reason `rollback_protected`).

Environment Flag Summary (additions):
- `G6_SHADOW_ROLLBACK_PROTECTED_THRESHOLD`: Integer >=1 to enable rollback after that many protected diffs within the rolling parity window.

Operational Guidance:
1. Start with threshold unset (disabled) while observing churn ratios; establish baseline (expect low churn for stable expiries; modest churn during high turnover periods).
2. Set a conservative rollback threshold (e.g., 3) only after confirming protected diffs are rare (should usually be 0 across window).
3. Alert on any increment of `g6_shadow_rollbacks_total`; couple with log sampling of `expiry.shadow.diff` for root cause.
4. If churn ratio persistently approaches 1.0 yet parity ratio remains high, consider investigating strike universe feeding logic or salvage oscillation rather than tightening thresholds prematurely.

Testing Additions:
- `test_shadow_gating_churn.py` validates churn ratio and distinct hash accounting across cycles.
- `test_shadow_gating_rollback.py` simulates protected diffs breaching threshold to assert rollback decision semantics.

Backward Compatibility:
- If the new env flag is not set, existing Phase 4 behavior remains unchanged (rollback path inert; decision fields still surfaced but purely observational).

Next (Potential Phase 6 Preview):
- Expand rollback triggers to include hash churn spike thresholds.
- Expose decision log line for external auditing (`shadow.gate.decision`).
- Configurable protected field set (`G6_SHADOW_PROTECTED_FIELDS`).

### Phase 6 Shadow Gating Dynamic Protection & Churn Rollback (Active / Incremental)
Focus: Operator-configurable protection surface and proactive rollback on structural volatility.

Enhancements:
- Structured decision log line emitted: `shadow.gate.decision index=... rule=... {json}` (DEBUG level) summarizing mode, ratio, streaks, diff_count, protected stats, churn, reason.
- Dynamic protected fields via `G6_SHADOW_PROTECTED_FIELDS` (comma list) merged with defaults (`expiry_date`, `instrument_count`). Any diff touching an added field sets `protected_diff` and blocks promotion.
- Churn-based rollback: `G6_SHADOW_ROLLBACK_CHURN_RATIO` (0-1) triggers `reason=rollback_churn` when `hash_churn_ratio` >= threshold (evaluated after min_samples, before canary/promote logic). Default sentinel (>1) disables.
- Decision schema additions already present in Phase 5 leveraged for rollback determination (no schema change required this phase).

New Environment Flags:
| Flag | Default | Description |
|------|---------|-------------|
| `G6_SHADOW_PROTECTED_FIELDS` | (empty) | Comma list of extra structural fields to treat as protected for gating decisions |
| `G6_SHADOW_ROLLBACK_CHURN_RATIO` | 2.0 | Set to <=1.0 to enable churn rollback when distinct-hash ratio exceeds threshold |

Behavioral Notes:
- Churn rollback fires prior to canary evaluation ensuring volatile structural phases do not enter canary/promotion even if parity diffs are zero most cycles.
- Dryrun mode will surface `rollback_churn` reason observationally but naturally leaves `promote=False`.
- Protected field expansion is idempotent; duplicates ignored; whitespace trimmed.

Operational Guidance:
1. Observe baseline `hash_churn_ratio` for several sessions before setting a rollback threshold.
2. Start with a conservative threshold (e.g., 0.85) if volatility correlates with downstream issues.
3. Keep protected field set minimal—over-protection can cause persistent promotion starvation.
4. Monitor `g6_shadow_rollbacks_total` alongside decision logs for early warning.

Testing Additions (Phase 6):
- `test_shadow_gating_protected_env.py` validates dynamic protected field blocking.
- `test_shadow_gating_churn_rollback.py` exercises churn rollback path.

Future Considerations:
- Separate window for churn evaluation (if hash volatility patterns diverge from parity OK sampling).
- Metric for protected field incidence rate per field (label cardinality constraints pending evaluation).

### Phase 7 Shadow Gating Operationalization (In Progress)
Goals: Bridge from observational + promotion readiness to controlled activation hooks and richer safety controls.

Enhancements:
- Separate churn window (`G6_SHADOW_CHURN_WINDOW`) enabling volatility tracking on a shorter horizon without shrinking parity confidence window.
- Authoritative promotion flag (`authoritative` in decision) surfaced when `G6_SHADOW_AUTHORITATIVE=1` and promotion criteria met (no automatic switch yet—flag only).
- Manual demotion override (`G6_SHADOW_FORCE_DEMOTE`) forces `promote=false` (reason=`forced_demote`) regardless of ratio/streak status.
- Optional per-protected-field diff counters via `G6_SHADOW_PROTECTED_METRICS_FIELDS` (comma list or `*`). Emits `g6_shadow_protected_field_diff_total{index,rule,field}`.
- Decision bus emission (if implemented earlier) can be paired with authoritative flag for downstream orchestration tooling.

New Environment Flags (Phase 7):
| Flag | Default | Description |
|------|---------|-------------|
| `G6_SHADOW_CHURN_WINDOW` | -1 | Independent hash churn window size (<=0 disables; falls back to parity window) |
| `G6_SHADOW_AUTHORITATIVE` | (unset) | When truthy, mark decisions with `authoritative=true` on successful promotion |
| `G6_SHADOW_FORCE_DEMOTE` | (unset) | Force demotion (promotion disabled, reason `forced_demote`) |
| `G6_SHADOW_PROTECTED_METRICS_FIELDS` | (empty) | Allowlist of protected fields to emit per-field diff counters (`*` => all protected) |
| `G6_SHADOW_GATE_EVENT_BUS` | (unset) | (If present) publish gating decisions to in-memory bus (event type `shadow.gate.decision`) |

Decision Additions:
- `churn_window_size`: sample count used for distinct hash churn ratio when separate window active.
- `authoritative`: boolean (only when authoritative flag enabled and promote path satisfied).

Operational Guidance:
1. Start with `G6_SHADOW_CHURN_WINDOW` small (e.g., 20% of parity window) to surface rapid oscillations without destabilizing parity evaluation.
2. Enable `G6_SHADOW_AUTHORITATIVE` only after rollback counters stable and no protected diffs for sustained period.
3. Use `G6_SHADOW_FORCE_DEMOTE` as a circuit breaker during live incidents (fast rollback) instead of changing gating mode.
4. Scope `G6_SHADOW_PROTECTED_METRICS_FIELDS` narrowly to avoid label cardinality growth (prefer explicit list over `*`).
5. If emitting decisions to the bus, subscribe with a filter on `shadow.gate.decision` to drive external dashboards or auto-remediation hooks.

Testing:
- `test_shadow_gating_phase7.py` validates churn window behavior, authoritative flag presence, and forced demotion override.

Next (Phase 8 Preview):
- Actual authoritative switching logic gating legacy vs shadow output behind dual-write safety.
- Field-level protected diff alerting integration.
- Churn spike adaptive backoff (dynamic thresholding).


## Versioning Assumptions
If you previously ran without an explicit semantic version, treat your state as "pre‑analytics" baseline. After migration, tag your deployment to reflect the new analytics feature set (e.g. `v1.0.0-analytics`).

## Detailed Changes
### 1. Aggregated Overview
Previously: Up to four per‑expiry rows every cycle.
Now: Single aggregated row consolidating PCR metrics across tracked expiries.
Impact: Downstream scripts should group by `index`+`timestamp` only (no longer need per‑expiry disambiguation for overview table).

### 2. Expiry Masks & Counts
Fields:
- `expiries_expected`, `expiries_collected`
- `expected_mask`, `collected_mask`, `missing_mask`
Bit values: `this_week=1`, `next_week=2`, `this_month=4`, `next_month=8`.
Use Case: Detect partial collection (non‑zero `missing_mask`).

### 3. CSV Column Evolution
- Added: `delta`, `gamma`, `theta`, `vega`, `rho` (conditional when Greeks enabled)
- Rho persisted as `ce_rho`, `pe_rho` when side‑specific columns are written.
- Legacy parsing: If your parser expected `strike` meaning option strike, that remains; new internal logic also stores underlying index price separately where relevant (ensure you inspect headers to adapt if needed).

### 4. Implied Volatility Solver
Configuration keys under `greeks`:
```
enabled: bool          # compute Greeks
estimate_iv: bool      # attempt IV estimation when iv <= 0
iv_max_iterations: int # default 100 (or your configured)
iv_min: float          # lower bound (e.g. 0.01)
iv_max: float          # upper bound (e.g. 5.0)
iv_precision: float    # convergence tolerance (price error)
risk_free_rate: float  # annualized
```
Failure Handling: On failure, IV omitted (or left <=0) and Greeks fallback to using default implied vol (commonly 0.25) unless customized.

### 5. Greeks
Computed post IV estimation using Black‑Scholes (European options): delta, gamma, theta (per day), vega (per 1% vol), rho.
If IV missing and estimation disabled/fails: Greeks use fallback implied volatility (documented in code; configurable by adjusting logic if needed).

### 6. InfluxDB Additions
Measurement `option_data` new fields when available: `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`.
Dashboards: Add conditional queries to only plot Greeks where present to avoid sparse noise.

### 7. Metrics Enhancements
Prometheus additions:
- `g6_iv_estimation_success_total{index,expiry}`
- `g6_iv_estimation_failure_total{index,expiry}`
- `g6_iv_estimation_avg_iterations{index,expiry}` (updated once per cycle)
Consider alerting if failure counter increases rapidly or average iterations approaches `iv_max_iterations` (solver stress indicator).

### 8. Deprecation of CLI Flags
Flags formerly controlling Greeks/IV are now no‑ops with warnings. Source of truth: JSON config `greeks` block.
Action: Remove obsolete command line usage in scripts / systemd units. Ensure `config/g6_config.json` contains the intended analytics settings.

## Migration Steps
1. Pull updated code.
2. Backup existing `data/` directory (CSV snapshots) and config JSON.
3. Add a `greeks` block to `config/g6_config.json` if absent (see example below).
4. (Optional) Enable Influx in `storage.influx` section to persist Greeks & IV.
5. Restart the service using the new orchestrator runner:
  ```
  python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 0
  ```
  (Use `--cycles N` for bounded dev loops; sets `G6_LOOP_MAX_CYCLES` internally.)
6. Validate Prometheus endpoint exposes new metrics.
7. Update downstream analytics: adjust overview expectations (single row) & include new columns/fields.
8. (Completed) `scripts/run_live.py` removed. Ensure automation uses orchestrator runner.

Example greeks block:
```json
"greeks": {
  "enabled": true,
  "estimate_iv": true,
  "risk_free_rate": 0.055,
  "iv_max_iterations": 150,
  "iv_min": 0.005,
  "iv_max": 3.0,
  "iv_precision": 1e-5
}
```

## Validation Checklist
- [ ] Overview CSV has exactly one row per index per minute (no duplicate per-expiry rows)
- [ ] Columns for Greeks appear only when enabled
- [ ] `missing_mask` remains 0 during normal operation
- [ ] Prometheus shows IV success > 0 and failures stable/low
- [ ] Influx `option_data` points include Greeks fields matching CSV rows
- [ ] Orchestrator runner (`scripts/run_orchestrator_loop.py`) in use; no new logs from legacy loop warning; `run_live.py` not used in automation

## Rollback Plan
If issues arise:
1. Disable Greeks (`enabled=false`, `estimate_iv=false`).
2. Revert to prior code tag (pre‑analytics) while retaining new CSV files (extra columns are typically ignored by older parsers, but verify).
3. Restore previous config file from backup.

## Notes
- Solver precision too strict can increase iteration count; relax `iv_precision` if near iteration cap.
- Outlier options (deep OTM) may fail IV convergence—expected behavior; monitor failure metric trend not absolute count.

## FAQ
Q: Why is IV zero for some options after enabling estimation?
A: Solver failed within bounds/iterations; inspect `failure_total` metric and consider widening `iv_min`/`iv_max` or increasing iterations.

Q: Theta sign seems inverted vs broker UI.
A: Platform reports theta (option value decay) per day; some UIs show per-calendar-day or use opposite sign convention—confirm downstream normalization.

Q: Can I add custom expiries (e.g., mid-week events)?
A: Extend expiry resolution logic (see collectors) and update masks table if introducing new categories.

---
End of Migration Guide.
\n## Legacy Removal Changelog (Historical)
### Summary Dashboard Unification (2025-10-03)
The legacy `scripts/summary_view.py` entrypoint was removed. All invocations must migrate to:
```
python -m scripts.summary.app --refresh 1
```
Key changes:
* Plain fallback + StatusCache paths merged into unified app.
* Diff suppression for plain mode always on (former `G6_SUMMARY_PLAIN_DIFF` flag removed).
* SSE publisher no longer gated by `G6_SSE_ENABLED`; constructing the unified app with `G6_SSE_HTTP=1` enables streaming automatically.
* Resync HTTP endpoint auto-enabled alongside SSE (`G6_SUMMARY_RESYNC_HTTP` removed; opt-out via `G6_DISABLE_RESYNC_HTTP=1`).

Action checklist:
1. Replace any `python scripts/summary_view.py` usages in automation with module form.
2. Remove deprecated env exports: `G6_SSE_ENABLED`, `G6_SUMMARY_REWRITE`, `G6_SUMMARY_PLAIN_DIFF`, `G6_SUMMARY_RESYNC_HTTP`.
3. Validate dashboards / scripts still function (no behavioral flag toggles required).
4. If custom wrappers existed, update help text to reference unified module.

Rollback guidance: Re-introducing the legacy script is NOT recommended; instead, file an issue if a missing capability is identified so it can be added to the unified app.

| Date | Change | Rationale | Safeguards |
|------|--------|-----------|------------|
| 2025-09-28 | `src/unified_main.py` removed (fail-fast stub) | Consolidated execution paths under orchestrator loop | Import-time hard failure + safeguard test |
| 2025-09-28 | Deprecated flags removed (`G6_ENABLE_LEGACY_LOOP`, etc.) | Eliminate dead branching | Safeguard test scans active src |
| 2025-09-28 | Archived stubs raise with guidance | Preserve messaging without code path risk | Archived excluded from scans |
| 2025-09-28 | Docs updated to new runner | Single canonical invocation | Planned doc lint (future) |
| 2025-09-28 | Added `test_safeguard_legacy_loop_removed.py` | Prevent resurrection | Targeted pattern scan |
| 2025-10-01 | Removed legacy unified snapshot assembler | Reduce dual maintenance surface | Parity test + model adoption |

### Upgrading Automation
If any scheduler invokes `python -m src.unified_main`, update to:
```
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60
```
Fail-fast stub ensures misconfigurations surface early.

### Adding New Entrypoints Going Forward
Add thin wrappers under `scripts/` over orchestrator APIs; avoid new monolithic module entrypoints in `src/`.

### Safeguard Test Maintenance
Keep legacy pattern assertions narrow; relocate historical text to docs instead of broadening allowlist.

## Deferred Unified Follow-Ups (Planned Work)
| Area | Item | Description | Planned Artifact / Location |
|------|------|-------------|-----------------------------|
| SSE Events | Classification tests | Validate full vs diff event tagging + metrics | `tests/test_sse_event_classification.py` |
| SSE Merge | Diff merge helper (IMPLEMENTED) | `merge_panel_diff` merges `panel_diff` into memory panels | `src/web/dashboard/diff_merge.py` |
| Curated Layout | Model-first rewire | Use `UnifiedStatusSnapshot` directly | `src/summary/curated_layout.py` |
| Rolling Stats | Model integration | Add rolling success/error & latency percentiles | `src/summary/unified/model.py` |
| Plugins | WebSocket broadcaster | Real-time push (diff/full multiplex) | `scripts/summary/plugins/websocket.py` |
| Plugins | Dossier rolling windows | Multi-cycle trend aggregation | `scripts/summary/plugins/dossier.py` |
| Metrics | Plugin scheduling metadata | Per-plugin cadence control | Loop + plugin contract |

Tracking: Remove related TODO anchors & add dated row here on completion.
| 2025-09-28 | Added `tests/test_safeguard_legacy_loop_removed.py` | Prevent accidental reintroduction of removed flags/entrypoint | Test scans only active `src/` (excludes archived & stub) |
| 2025-10-01 | Removed legacy unified snapshot assembler (`src/summary/unified/snapshot.py`) and tests | Native model builder fully adopted; eliminates dual maintenance & reduces surface | New parity test `test_model_snapshot_parity.py`; full suite green post-removal |
| 2025-10-01 | Dual emission enabled in unified loop | Begin Phase 2: attach `snapshot.model` each cycle | Backward compatible (plugins opt-in) |
\n+### Upgrading Automation
If any external scheduler (systemd, Windows Task Scheduler, cron) still invokes `python -m src.unified_main`, update it to:
```
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60
```
The stub will now fail fast; do not suppress the error—fix the caller instead.
\n+### Adding New Entrypoints Going Forward
Add new specialized runners under `scripts/` and keep them thin wrappers around orchestrator APIs (`bootstrap_runtime`, `run_loop`, `run_cycle`). Avoid resurrecting module-level monoliths inside `src/`.
\n+### Safeguard Test Maintenance
If you intentionally reintroduce historical strings (e.g., in a retrospective doc), ensure they live in docs or `src/archived/`. Do not widen the test allowlist for convenience—relocate the text instead.
\n+## Streaming Bus Prototype (Migration Phase 3 - PARTIAL)
Date: 2025-10-04

Status: Prototype in-memory event bus implemented with foundational metrics & dashboard. External pluggable backends (e.g., Redis / NATS) and durability not yet in scope; this phase establishes the contract & observability.

### Summary
An in-process ring-buffer based event bus (`src/bus/in_memory_bus.py`) has been added to decouple future streaming publishers (e.g., snapshot diffs, analytics plugin emissions) from downstream consumers. The design emphasizes minimal allocation overhead and first-class instrumentation.

### Event Envelope
`Event` (`src/bus/event.py`):
| Field | Type | Description |
|-------|------|-------------|
| id | int | Monotonic sequence id per bus |
| ts | float | Publish time (epoch seconds) |
| type | str | Event type/classifier (e.g., `snapshot.diff`) |
| key | str | Optional grouping key (index, panel, etc.) |
| payload | dict | JSON-serializable body (opaque to bus) |
| meta | dict | Free-form metadata (reserved for future routing / tracing) |

### Metrics Added (bus family)
| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| g6_bus_events_published_total | counter | bus | Publish volume tracking |
| g6_bus_events_dropped_total | counter | bus,reason | Overflow / rejection accounting |
| g6_bus_queue_retained_events | gauge | bus | Current ring buffer occupancy |
| g6_bus_subscriber_lag_events | gauge | bus,subscriber | Backpressure signal per subscriber |
| g6_bus_publish_latency_ms | histogram | bus | Latency of publish critical path (ms) |

Histogram Buckets (ms): 0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50 (focus on sub-50ms path; revise when external transports introduced).

### Dashboard
New Grafana dashboard: `grafana/dashboards/g6_bus_health.json` featuring:
* Stat + timeseries: publish rate & drop rate
* Retained events gauge
* Top subscriber lag (topk(5))
* Publish latency p95 + heatmap distribution

### Overflow & Backpressure Semantics
* Ring buffer (deque) `max_retained` (default from class constant) caps memory usage.
* On overflow: oldest events dropped (reason=`overflow_oldest`) and drop counter increments.
* Subscriber lag computed as `last_published_id - last_consumed_id` per subscriber; updated on every poll and publish.

### Guarantees (Current Prototype)
* Ordering: Per-bus FIFO sequencing (monotonic id)
* At-Most-Once: Dropped events are not retried
* In-Memory Only: No persistence or replay across process restarts
* Single-Process Scope: Not safe for multi-process fan-out yet

### Non-Goals (Deferred)
* Cross-process / distributed transport
* Durable persistence / replay
* Exactly-once or at-least-once delivery semantics
* Per-subscriber selective filtering (future optimization)

### Testing
Added `tests/test_in_memory_bus.py` covering:
* Publish ordering & id continuity
* Overflow drop behavior and head advancement
* Subscriber lag via partial poll sequencing

### Upgrade / Adoption Guidance
No action required for existing deployments unless integrating early with bus. Early adopters can publish experimental events by obtaining a bus via `from src.bus.in_memory_bus import get_bus` and invoking `publish(type, payload, key=...)`.

### Forward Roadmap (Next Steps)
| Item | Description | Planned Metric / Artifact |
|------|-------------|---------------------------|
| External backend abstraction | Interface for alternative transports (Redis, NATS) | Potential: `g6_bus_transport_latency_ms` |
| Durable queue option | Pluggable persistence with replay window | Replay counters / lag histogram |
| Subscriber filtering | Predicate-based routing to reduce deserialization cost | Filter miss counter |
| End-to-end tracing hooks | Inject trace/span ids for cross-service correlation | Trace enrichment metrics |
| Backpressure policy | Dynamic publisher throttling on sustained lag | Throttle activation counter |

### Rollback
Remove imports/usages of `get_bus` and delete the bus dashboard. No schema changes; metrics family removal would require Prometheus rule/dashboard cleanup if reverted.

---
End Phase 3 (Prototype) notes.
\n+### Bus Alert Runbook (Initial)
Alert Glossary:
| Alert | Trigger | First Actions |
|-------|---------|---------------|
| G6BusDropRateElevated | drop rate >5 eps 10m | Inspect `topk` lag; confirm consumer health; consider raising `max_retained` temporarily |
| G6BusDropRateCritical | drop rate >20 eps 5m | Immediate: throttle publishers or shard; capture pprof / stack traces |
| G6BusPublishLatencyHigh | p95 >10ms 10m | Check lock contention, recent deployment diffs, payload size growth |
| G6BusPublishLatencyCritical | p95 >25ms 5m | Enable profiler, isolate hot path; consider temporary feature flag reduction |
| G6BusSubscriberLagHigh | lag >5000 15m | Identify subscriber (label); assess throughput; add filtering or spin new consumer instance |
| G6BusQueueSaturationHigh | occupancy >90% 10m | Preempt overflow: increase capacity or reduce publish rate bursts |
| G6BusQueueSaturationCritical | occupancy >97% 5m | Emergency: pause non-critical publishers; drain backlog; raise capacity cautiously |

Mitigation Heuristics:
* Drops + High Lag: Prefer fixing slow consumer vs. unbounded capacity growth.
* Latency + No Lag: Indicates internal critical path overhead (serialization or locking) rather than backpressure.
* Saturation without Drops Yet: Safe window to profile before data loss begins.

Future Integration: When external transports added, latency & drop thresholds will be re-baselined; update this table accordingly.
