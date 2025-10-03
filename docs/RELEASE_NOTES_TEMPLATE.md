# Release Notes Template (G6 Platform)

Use this template when drafting a new release. Replace placeholders and remove unused sections. Refer to `docs/DEPRECATIONS.md` for active deprecations.

## 1. Overview
Brief summary of major themes (performance, integrity, remediation, observability).

## 2. Highlights
- Feature 1: <one line>
- Feature 2: <one line>

## 3. Breaking Changes
- <List any incompatible config / API / behavior changes>

## 4. Deprecations
Reference `docs/DEPRECATIONS.md`. For each item scheduled for removal in this or next release:
- Component: <name> (Deprecated since: <date>) – Replacement: <replacement>. Removal target: <R+N>. Action required: <steps>.

Checklist:
- [ ] Verified `DEPRECATIONS.md` updated with any new items.
- [ ] All slated-for-removal components either removed or timeline extended with justification noted.
- [ ] `g6_deprecated_usage_total` monitored (attach short usage summary if non-zero for soon-to-remove items).

## 5. New Features
| Area | Description | Flags (if any) |
|------|-------------|----------------|
| Orchestrator |  |  |
| Remediation |  |  |
| Observability |  |  |
| Performance |  |  |
| Security |  |  |

## 6. Metrics Additions
| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| g6_deprecated_usage_total | Counter | component | Track runtime use of deprecated components |
| ... | ... | ... | ... |

## 7. Configuration / Env Additions
| Name | Type | Default | Description |
|------|------|---------|-------------|
| <ENV_FLAG> | bool | 0 | <desc> |

## 8. Fixed Issues
- <Issue / bug description + impact>

## 9. Performance / Scalability
- <Cycle time, memory, cardinality improvements>

## 10. Integrity & Data Quality
- <Misclassification reduction, gaps detection enhancements>

## 11. Security / Supply Chain
- <SBOM, audit gating updates>

## 12. Upgrade Notes
- Steps to migrate from prior release.
- Any manual data cleanup or flag migrations.

## 13. Removal Summary (If Applicable)
Components removed this release:
| Component | Replacement | Deprecated Since | Notes |
|-----------|-------------|------------------|-------|

## 14. Acknowledgements
(Optional credits / external libs / contributors.)

---
_Last updated: 2025-09-26_
