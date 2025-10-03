# On-Call Adaptive Alerts: 10-Line Escalation Guide

1. Badge shows `[C:x W:y]`: If `C>0`, open critical source first (interpolation_high >70%? risk_delta_drift >10%?).
2. Multiple critical types: Capture panel JSON & metrics snapshot before mitigation (for post-mortem).
3. Critical persisting > N cycles (N≈decay window *2) without R increments: treat as real degradation – investigate upstream data / provider.
4. Rapid oscillation (frequent R then immediate re-escalation): raise `G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK` or widen decay window after confirming noise.
5. Large single-step decay (critical→info) means long inactivity gap; verify process pauses (look for missing cycles / gaps metrics).
6. High warn count with stable `(stable)` absent critical: monitor only; defer action unless business impact reported.
7. No decay (R never increases) + stable high warn: consider lowering thresholds or verifying metric correctness.
8. Increase verbosity: temporarily log enriched alerts raw by setting `G6_ADAPTIVE_ALERT_SEVERITY_FORCE=1` (only if external producers could conflict) and enabling debug logging (implementation-specific).
9. Always record current `severity_meta` (rules, decay_cycles) when escalating – attach to incident ticket.
10. Post-resolution: if thresholds modified, update `G6_ADAPTIVE_ALERT_SEVERITY_RULES` JSON & commit doc changes (design + env_dict) to keep single source of truth.

Cross-Refs: `adaptive_alerts` panel (severity_meta), `docs/cheatsheets/adaptive_alerts_badge.md`, design doc section 13–16.
