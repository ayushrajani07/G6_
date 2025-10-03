# Governance Metrics & Guards

This document summarizes the internal governance / integrity layers applied to the metrics subsystem.
Each guard is lightweight, environment‑controlled, and fails safe (never raising during normal operation unless an explicit *fail* flag is set).

## Overview

Guards currently implemented:

| Guard | Purpose | Key Metrics | Primary Env Controls |
|-------|---------|-------------|----------------------|
| Cardinality Guard | Prevent unbounded growth in labeled series groups | (varies – guard inspects registry); `cardinality_guard_trips_total` (orchestrator) | `G6_CARDINALITY_SNAPSHOT`, `G6_CARDINALITY_BASELINE`, `G6_CARDINALITY_ALLOW_GROWTH_PERCENT`, `G6_CARDINALITY_FAIL_ON_EXCESS` |
| Duplicate Guard | Detect multiple registry attributes pointing to the same collector (aliases / shadowing) | `g6_metric_duplicates_total` | `G6_DUPLICATES_FAIL_ON_DETECT`, `G6_DUPLICATES_LOG_DEBUG` |
| Fault Budget Tracker | Convert raw cycle SLA breach counter into rolling SLO window & budget exhaustion signals | `g6_cycle_fault_budget_remaining`, `g6_cycle_fault_budget_breaches_window`, `g6_cycle_fault_budget_window_seconds`, `g6_cycle_fault_budget_consumed_percent` | `G6_FAULT_BUDGET_ENABLE`, `G6_FAULT_BUDGET_WINDOW_SEC`, `G6_FAULT_BUDGET_ALLOWED_BREACHES`, `G6_FAULT_BUDGET_STRICT`, `G6_FAULT_BUDGET_LOG_DEBUG` |

A unified helper `MetricsRegistry.governance_summary()` returns a JSON‑serializable snapshot:
```jsonc
{
  "duplicates": { /* duplicate guard summary or null */ },
  "cardinality": { /* cardinality guard summary or null */ },
  "fault_budget": {
     "window_sec": 3600.0,
     "allowed": 60,
     "within": 3,
     "remaining": 57,
     "consumed_percent": 5.0,
     "exhausted": false
  }
}
```

## 1. Cardinality Guard

Controls growth of metric series counts by comparing current grouped series counts against a baseline snapshot.

Environment flags:
- `G6_CARDINALITY_SNAPSHOT=path.json` – Write a fresh baseline of grouped series counts.
- `G6_CARDINALITY_BASELINE=path.json` – Compare against an existing baseline.
- `G6_CARDINALITY_ALLOW_GROWTH_PERCENT` (default 10) – Percentage growth allowed before violation.
- `G6_CARDINALITY_FAIL_ON_EXCESS=1` – Raise `RuntimeError` if excess growth detected.

Typical workflow:
1. In a controlled environment (e.g., staging), set `G6_CARDINALITY_SNAPSHOT=cardinality_base.json` and run the process once to emit the baseline.
2. Commit or archive the snapshot file.
3. In CI or production preflight, set `G6_CARDINALITY_BASELINE=cardinality_base.json` (and optionally the fail flag) to enforce the limit.

PromQL monitoring ideas (examples depend on naming of application metrics):
```promql
# Example: sudden explosion in series for a family (replace label selectors as relevant)
count by (__name__) ({job="g6"}) > 1000
```

Structured log events (grep friendly):
- `metrics.cardinality.snapshot_written`
- `metrics.cardinality.guard`
- `metrics.cardinality.guard_ok`

## 2. Duplicate Guard

Detects multiple registry attributes referencing the same Prometheus collector (aliasing / accidental double registration).

Environment flags:
- `G6_DUPLICATES_FAIL_ON_DETECT=1` – Raises `RuntimeError` if duplicates found.
- `G6_DUPLICATES_LOG_DEBUG=1` – Emit per-group debug lines (otherwise only a capped summary warning).

Metric:
- `g6_metric_duplicates_total` – Count of duplicate collector groups (not total extra attributes).

Structured log event:
- `metrics.duplicates.detected`

PromQL alert example:
```promql
# Fire if any duplicate groups present for 5m
max_over_time(g6_metric_duplicates_total[5m]) > 0
```

## 3. Fault Budget Tracker

Transforms cumulative cycle SLA breach counter (`g6_cycle_sla_breach_total` internal counter attribute `cycle_sla_breach`) into rolling SLO consumption signals.

Environment flags:
- `G6_FAULT_BUDGET_ENABLE=1` – Enable tracking.
- `G6_FAULT_BUDGET_WINDOW_SEC` (default 3600) – Rolling window length in seconds.
- `G6_FAULT_BUDGET_ALLOWED_BREACHES` (default 60) – Budget units allowed within window.
- `G6_FAULT_BUDGET_STRICT=1` – Log ERROR (instead of WARNING) on first exhaustion event.
- `G6_FAULT_BUDGET_LOG_DEBUG=1` – Emit per-update debug logs.

Metrics:
- `g6_cycle_fault_budget_remaining`
- `g6_cycle_fault_budget_breaches_window`
- `g6_cycle_fault_budget_window_seconds`
- `g6_cycle_fault_budget_consumed_percent`

Log events:
- `metrics.fault_budget.exhausted`
- `metrics.fault_budget.recovered`
- `metrics.fault_budget.update` (debug only)

Example PromQL alerts:
```promql
# A. Exhausted fault budget (remaining == 0) continuously for 2 minutes
min_over_time(g6_cycle_fault_budget_remaining[2m]) == 0

# B. Early warning: >80% consumed for sustained 5 minutes
max_over_time(g6_cycle_fault_budget_consumed_percent[5m]) > 80

# C. High breach rate trend: slope of breaches in window (heuristic)
(deriv(g6_cycle_fault_budget_breaches_window[10m]) > 0.1)
```

## 4. Governance Summary Helper

Call `registry.governance_summary()` for an aggregated view (useful in a diagnostic endpoint or health report). Safe to call anytime; missing components appear as `null`.

## 5. Operational Recommendations

- Run duplicate & cardinality guards in CI to detect regressions early.
- Enable the fault budget tracker in staging first; tune `ALLOWED_BREACHES` to historical p95 breach counts + headroom.
- Pair fault budget exhaustion alerts with cardinality growth alerts to correlate systemic load regressions with reliability degradation.

## 6. Failure Safety

All guards swallow unexpected internal exceptions to avoid impacting core metric emission. Only explicit fail-on flags cause process exceptions.

## 7. Future Enhancements (Ideas)

- Add pre‑exhaustion multi-threshold alert gauges (e.g., 50%, 80%, 95%).
- Unified governance Prometheus exposition (single JSON -> info metric mapping).
- Optional export of governance summary via HTTP debug endpoint.

---
Generated: Automated documentation scaffold (update as features evolve).
