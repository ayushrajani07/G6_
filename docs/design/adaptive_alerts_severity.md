# Adaptive Alerts Severity & Color Mapping Design

_Last updated: 2025-09-27_

## 1. Overview
Introduce a severity classification layer (info/warn/critical) for adaptive analytics alerts to improve operator triage in panels, terminal summary, and future web UI, while maintaining backward compatibility and avoiding unnecessary Prometheus cardinality expansion.

## 2. Goals / Non-Goals
### Goals
- Consistent severity taxonomy across diverse alert types.
- Configurable thresholds & palette via environment / optional JSON override.
- Zero breaking change for existing panel consumers.
- Lightweight computation (O(1) per alert) and deterministic outcomes.
- Extensible structure for future states (resolved, suppressed, decay/downgrade).

### Non-Goals (Initial Phase)
- Emitting separate Prometheus metrics for severity counts.
- Direct adaptive controller decision integration (future consideration).
- Historical persistence or time-window aggregation beyond in-memory counters.

## 3. Current State (Baseline)
Adaptive alerts panel today:
```
{
  "total": <int>,
  "by_type": {"type": count, ...},
  "recent": [...],
  "last": {...}
}
```
Alert objects contain fields like `type`, `timestamp`, and type-specific numeric attributes (e.g., `interpolated_fraction`, `drift_pct`, `utilization`).

## 4. Proposed Enhancements
Augment panel (when enabled) with severity enrichment fields and per-type breakdown:
```
{
  "total": 11,
  "by_type": {"interpolation_high": 5, "risk_delta_drift": 4, "bucket_util_low": 2},
  "severity_counts": {"info": 4, "warn": 5, "critical": 2},
  "by_type_severity": {
    "interpolation_high": {"last_severity": "warn", "counts": {"info": 1, "warn": 4, "critical": 0}},
    "risk_delta_drift": {"last_severity": "critical", "counts": {"info": 2, "warn": 1, "critical": 1}},
    "bucket_util_low": {"last_severity": "info", "counts": {"info": 1, "warn": 0, "critical": 1}}
  },
  "recent": [ { ... , "severity": "warn" }, ... ],
  "last": { ... , "severity": "critical" }
}
```
If disabled, structure remains unchanged (all new keys omitted).

## 5. Classification Rules (Default Thresholds)
| Alert Type | Inputs | info | warn | critical |
|------------|--------|------|------|----------|
| interpolation_high | interpolated_fraction f | f < 0.50 | 0.50 ≤ f < 0.70 | f ≥ 0.70 |
| risk_delta_drift | abs(drift_pct) d | d < 0.05 | 0.05 ≤ d < 0.10 | d ≥ 0.10 |
| bucket_util_low | utilization u | u ≥ 0.75 | 0.60 ≤ u < 0.75 | u < 0.60 |
| bucket_coverage_drop (future) | coverage_delta c | c > -0.05 | -0.15 < c ≤ -0.05 | c ≤ -0.15 |
| vol_quality_degrade (future) | quality_score q | q ≥ 0.60 | 0.40 ≤ q < 0.60 | q < 0.40 |

Edge inclusion: boundary values (== warn lower bound) escalate to warn; (== critical lower bound) escalate to critical.

## 6. Environment / Config Controls
| Variable | Default | Description |
|----------|---------|-------------|
| G6_ADAPTIVE_ALERT_SEVERITY | 1 | Master enable (0 disables all severity logic/fields) |
| G6_ADAPTIVE_ALERT_SEVERITY_RULES | (unset) | JSON inline or file path with per-type {warn,critical} thresholds |
| G6_ADAPTIVE_ALERT_COLOR_INFO | #6BAF92 | Terminal/web color for info |
| G6_ADAPTIVE_ALERT_COLOR_WARN | #FFC107 | Terminal/web color for warn |
| G6_ADAPTIVE_ALERT_COLOR_CRITICAL | #E53935 | Terminal/web color for critical |
| G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK | 1 | Minimum consecutive trigger count before upgrading above info |
| G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES | 0 | If >0, downgrade severity one level after N idle cycles (no repeats) |
| G6_ADAPTIVE_ALERT_SEVERITY_FORCE | 0 | Overwrite existing `severity` field on alerts if present |

Rules override precedence: ENV JSON > built-in defaults. Unspecified types fall back to defaults. Invalid JSON logged once (warn) then ignored.

## 7. Internal Modules & API Surface
New module: `src/adaptive/severity.py`
Functions:
- `load_rules() -> Dict[str, Dict[str, float]]` (cached; supports file or inline JSON)
- `classify(alert: Dict[str, Any]) -> str` (pure, deterministic)
- `enrich_alert(alert: Dict[str, Any]) -> Dict[str, Any]` (adds severity if enabled)
- `aggregate(alerts: List[Dict[str, Any]]) -> Tuple[panel_fields...]` (builds counts for panel assembly)

No new external dependencies required.

## 8. Data Flow Integration Points
1. Alert generation site(s) (where adaptive alerts appended to status) calls `enrich_alert` if feature enabled.
2. Panel factory (`panels/factory.py`) consumes enriched alerts and constructs new aggregation keys.
3. Summary view (`scripts/summary_view.py`) optionally displays severity aggregate: `Adaptive alerts: <total> [C:<critical> W:<warn>]`.

## 9. Performance Considerations
- Classification is constant-time numeric comparisons.
- Aggregation: single pass O(N) over recent alerts list (already iterated today for counts) adding negligible overhead.
- Memory: Additional dicts (severity_counts, by_type_severity) proportional to distinct alert types (small set). Acceptable.

## 10. Backward Compatibility & Fallbacks
- Disabled mode returns current structure; callers not checking new keys remain unaffected.
- Try/Except isolation: if classification raises unexpectedly, log & default to info (fail-soft).
- No Prometheus metric proliferation (severity summarization remains panel/UI only initially).

## 11. Testing Strategy
| Test | Purpose |
|------|---------|
| `test_severity_thresholds.py` | Boundary classification per alert type |
| `test_severity_overrides.py` | JSON override shifts thresholds |
| `test_severity_disabled.py` | Feature off -> no severity keys present |
| `test_severity_bad_json.py` | Invalid override logs warning & uses defaults |
| `test_severity_min_streak.py` | Streak gating prevents premature escalation |
| `test_severity_decay.py` | Decay logic downgrades after idle cycles (if enabled) |
| `test_summary_badge_severity.py` | Badge augmented with C/W counts |

Mocks: Provide crafted alert sequences with controlled numeric values.

## 12. Implementation Ticket Checklist
(Each line can map to an issue / PR task)
1. Create `adaptive/severity.py` module with rule loading + classify() skeleton & defaults.
2. Implement rule override loader (inline JSON vs file path detection).
3. Add environment variable documentation (`docs/env_dict.md`).
4. Integrate enrichment call at alert creation point(s).
5. Extend panel factory aggregation for severity fields (guarded by enable flag).
6. Add summary badge enhancement (rich + plain modes) with conditional counts.
7. Implement min streak escalation logic (counter per (type) since last emit).
8. Implement decay logic (if DECAY_CYCLES > 0) with per-type last seen cycle tracking.
9. Write threshold boundary tests.
10. Write override & invalid JSON tests.
11. Write disabled mode test (ensures absence of new keys).
12. Write streak & decay tests (skip decay if feature disabled by config).
13. Write summary badge severity test (counts formatting & suppression when zero).
14. Update `docs/future_enhancements.md` Section 16 to summary + link to this doc.
15. Update `METRICS.md` cross-reference (panel severity note, no metrics emitted phase 1).
16. Update `CHANGELOG` / roadmap log with feature addition.
17. Run env doc generation script & update baseline tests if needed.
18. Final lint & full test suite pass.

## 13. Rollout Phases
- Phase 1 (MVP): Steps 1–9, 11, 13–18 (no decay) – severity & badge counts.
- Phase 2 (DELIVERED 2025-09-27): Implements decay & resolved semantics. Each alert type tracks last active cycle and active severity. If `G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES > 0`, inactivity triggers severity downgrades at N-cycle granularity (multi-step if gap spans multiple windows). When an elevated severity (warn/critical) decays back to info without a new triggering alert, a one-time `resolved: true` flag is emitted on the decaying alert object and panel aggregation increments `resolved_total`. Summary badge now suppresses `[C:x W:y]` when both are zero and appends `(stable)` marker to signal all alerts are at baseline.
- Phase 3 (DELIVERED 2025-09-27): Controller feedback integration & palette exposure. Adaptive controller now consumes active severity state (critical triggers immediate demotion; warn can block promotions) via new env flags: G6_ADAPTIVE_CONTROLLER_SEVERITY, G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES, G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES. Panel severity_meta includes palette (color overrides) and active_counts snapshot. Helper APIs added: get_active_severity_state(), get_active_severity_counts(). Tests: test_adaptive_severity_controller_integration.py.
 - Phase 3.1 (DELIVERED 2025-09-27): Trend smoothing & theme endpoint. Added severity trend ring buffer + smoothing env flags (G6_ADAPTIVE_SEVERITY_TREND_*), controller now optionally uses ratio thresholds for demotion/promotion gating. New HTTP route /adaptive/theme returns palette, active_counts, and trend stats for web dashboard theming.

## 14. Open Questions
- Should repeated critical alerts escalate to separate operator event channel? (Deferred)
- Need for suppression window (deduplicate same severity spam)? (Future.)

## 15. Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Incorrect overrides causing silent misclassification | Validate numeric ranges & log anomalies |
| Alert object already has `severity` | Respect unless FORCE set |
| Threshold churn increasing operator confusion | Provide single source of truth doc & embed active thresholds in panel footer (future) |

## 16. Acceptance Criteria (Phase 1 & Phase 2)
Phase 1:
- Panel contains severity_* fields when enabled; absent when disabled.
- Classification matches documented thresholds & override tests pass.
- Summary badge includes severity counts when >0.
- No new metric families introduced.
- All new env vars documented & env doc coverage test passes.

Phase 2 (fulfilled):
- Decay reduces inactive severities after configured idle cycles (multi-level downgrades supported when gaps > N).
- Resolved flag only appears on a decay transition from warn/critical → info (never on active trigger or disabled decay).
- Panel aggregation exposes per-type `active_severity` and `last_change_cycle`; adds `resolved_total` counter.
- Summary badge adds resolved count (R:n) when >0 and `(stable)` marker when no active warn/critical severities remain.
- Existing Phase 1 tests remain green; new decay/resolution tests cover critical→warn→info path, inverted rule decay, disabled decay, and resolved emission predicate.

---
Prepared for implementation; see checklist (Section 12) for task decomposition.

Cheat Sheet: See `docs/cheatsheets/adaptive_alerts_badge.md` for operator-facing badge interpretation examples. On-call escalation quick guide: `docs/cheatsheets/oncall_adaptive_alerts_runbook.md`.
