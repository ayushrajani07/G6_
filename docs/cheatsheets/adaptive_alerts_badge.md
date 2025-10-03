# Adaptive Alerts Badge Cheat Sheet

Quick reference for interpreting the adaptive alerts severity badge (terminal summary / future UI widgets).

## Badge Patterns
| Pattern | Meaning | Action Bias |
|---------|---------|-------------|
| `Adaptive alerts: 7 [C:2 W:1]` | 2 critical + 1 warn active | Investigate critical sources first |
| `Adaptive alerts: 5 [W:2]` | Only warning-level issues (no critical) | Monitor; escalate if persists or trends up |
| `Adaptive alerts: 9 R:1 (stable)` | All previously elevated severities decayed to info; 1 resolution this cycle | Low urgency; verify underlying recovery if recent incident |
| `Adaptive alerts: 12` (no bracket & no stable) | Severity feature disabled OR all severities info without resolution tracking | Confirm config if unexpected |
| `Adaptive alerts: 3 R:2 (stable)` | Two separate alert types resolved simultaneously | Check for systemic transient (e.g., short provider blip) |

## Field Reference
- `C:x` – Count of currently critical-classified alerts
- `W:y` – Count of currently warn-classified alerts
- `R:n` – Number of types that decayed from warn/critical → info this cycle
- `(stable)` – No active warn/critical after decay evaluation

## Resolution Lifecycle
1. Alert type escalates (warn or critical) when classification rules + streak conditions met.
2. Inactivity window (N cycles) passes (`G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES`).
3. Severity decays one level (multi-step allowed if gap spans multiple windows).
4. When final decay reaches info from an elevated state: emit `resolved` flag and increment `resolved_total` (reflected as `R:n`).

No resolution emitted if:
- Decay disabled (`DECAY_CYCLES=0`).
- Severity was already info.
- New alert fired causing explicit reclassification instead of passive decay.

## Tuning Signals
| Symptom | Possible Tweak | Notes |
|---------|----------------|-------|
| Frequent oscillation critical→warn→critical | Increase `MIN_STREAK` or raise critical threshold | Avoid chasing transient spikes |
| High resolved churn (R every cycle) | Increase `DECAY_CYCLES` | Indicates idle window too short |
| Rarely decays (stuck warn) | Lower thresholds or decrease `DECAY_CYCLES` | Confirm underlying metric truly improved |

## Environment Variables
| Var | Purpose |
|-----|---------|
| `G6_ADAPTIVE_ALERT_SEVERITY` | Master enable for severity system |
| `G6_ADAPTIVE_ALERT_SEVERITY_RULES` | Override per-type thresholds (JSON/file) |
| `G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK` | Streak gating before escalation |
| `G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES` | Idle cycles before decay downgrade |
| `G6_ADAPTIVE_ALERT_SEVERITY_FORCE` | Force overwrite of existing severity field |

## Example Timeline (DECAY_CYCLES=2)
Cycle 20: risk_delta_drift warn → `... [W:1]`
Cycle 21–22: idle (no drift alert) → still warn
Cycle 23: decays warn→info → `... R:1 (stable)`
Cycle 24: new drift triggers warn again → `... [W:1]`

## Cross-References
- Design: `docs/design/adaptive_alerts_severity.md`
- Operator Manual Section 16
- Roadmap Change Log: Phase 2 entry (decay & resolved)

---
Use this cheat sheet during on-call to quickly differentiate noisy info-only periods from genuine degradation requiring action.
