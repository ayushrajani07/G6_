# Migration Guide

This guide documents schema, configuration, and behavioral changes introduced in the recent platform evolution so existing users can upgrade smoothly.

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
5. Restart the service using the unified entrypoint.
6. Validate Prometheus endpoint exposes new metrics.
7. Update downstream analytics: adjust overview expectations (single row) & include new columns/fields.

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
