# Documentation Index

Canonical, curated docs after consolidation. Automated guardrails check for
presence of required entries (see `scripts/cleanup/doc_index_check.py`).

## Core
- `README.md` – High-level platform overview
- `docs/clean.md` – Strategic cleanup roadmap & execution waves
- `docs/ENVIRONMENT.md` – Environment variable governance & lifecycle
- `docs/METRICS.md` – Metrics taxonomy & migration notes
- `docs/DEPRECATIONS.md` – Active / completed deprecations

## Architecture
- `docs/SSE.md` – Unified SSE & HTTP architecture, security & refactor phases
- `docs/UNIFIED_MODEL.md` – Unified data model & plugin architecture
- `docs/PANELS_FACTORY.md` – Panels assembly pipeline & rendering
- `docs/CONFIGURATION.md` – Configuration surfaces & precedence

## Operations & Governance
- `docs/GOVERNANCE_METRICS.md` – KPIs, measurement definitions
- `docs/EXEC_SUMMARY.md` – Executive snapshot (periodic)
- `docs/REDUNDANT_COMPONENTS.md` – Candidates for removal / already removed
- `docs/GOVERNANCE.md` – Policies, gates, lifecycles
- `docs/CLEANUP_FINAL_REPORT.md` – Consolidated cleanup & governance outcomes (scaffold)

## Observability
- `docs/OBSERVABILITY_DASHBOARDS.md`
- `docs/METRICS_CATALOG.md`
- `docs/RULES_CATALOG.md`

## Historical / Legacy (candidates for archive)
- `WAVE*_TRACKING.md`
- `PHASE*_SCOPE.md`
- `DEFERRED_ENHANCEMENTS.md`

This file is intentionally concise—deep drill-down content remains in the
individual documents referenced above.

Regenerate or expand via future `scripts/cleanup/doc_index.py` (planned).
