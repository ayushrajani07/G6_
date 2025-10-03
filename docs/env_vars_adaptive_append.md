# Adaptive Alert & Metrics Facade Environment Variables (Pending Consolidation)

This temporary appendix lists newly introduced or previously undocumented G6_ environment variables surfaced by the test_env_doc_coverage guard after the metrics facade migration.

They must be merged into docs/env_dict.md (single authoritative inventory) and duplicates removed.

## Newly Detected (to be added)

Core adaptive alerting / severity system:
- G6_ADAPTIVE_ALERT_SEVERITY
- G6_ADAPTIVE_ALERT_SEVERITY_RULES
- G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES
- G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK
- G6_ADAPTIVE_ALERT_SEVERITY_FORCE
- G6_ADAPTIVE_ALERT_SEVERITY
- G6_ADAPTIVE_ALERT_SEVERITY_RULES
- G6_ADAPTIVE_DEMOTE_COOLDOWN
- G6_ADAPTIVE_MAX_DETAIL_MODE
- G6_ADAPTIVE_ALERT_COLOR_INFO
- G6_ADAPTIVE_ALERT_COLOR_WARN
- G6_ADAPTIVE_ALERT_COLOR_CRITICAL

(Full list length 129 – capture snapshot separately via scripts/env_doc tooling.)

## Duplicates To Consolidate
- G6_REFACTOR_DEBUG
- G6_SUMMARY_DOSSIER_PATH

## Next Step
Integrate the above into env_dict.md with concise one‑line descriptions and remove this appendix.
