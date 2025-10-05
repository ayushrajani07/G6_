# High-Impact Cleanup Plan (Scaffolding Draft)

This document captures the actionable cleanup roadmap for the G6 project. It is a normalized copy of the previously discussed plan, now checked into version control for iterative refinement.

## Objectives

Reduce maintenance surface, eliminate dead / legacy code, consolidate scattered documentation, and institutionalize guardrails that prevent regression of clutter or drift.

## Pillars

1. Inventory & Classification
2. Dead Code Detection Automation
3. Logic De-duplication (SSE / Unified HTTP)
4. Legacy & Temp Artifact Purge
5. Environment Variable Governance
6. Documentation Consolidation & Indexing
7. CI Guardrails / Quality Gates
8. Execution Waves (A/B/C) & Rollback Safety
9. Metrics & KPIs
10. Communication & Migration Notes

## Wave Definition

| Wave | Focus | Risk | Outputs |
|------|-------|------|---------|
| A | Inventory, doc structure, detection scaffolds, no functional refactors | Low | Inventory JSON, env catalog, doc index, candidate list | 
| B | Logic refactors (shared SSE security), controlled deletions, env validator | Medium | Shared helpers, removed dead code, warnings | 
| C | Structural packaging, stricter CI gates, advanced metrics | Medium/High | Slimmer deployable, KPI dashboard |

## Inventory Classification Tags

| Tag | Meaning | Heuristic |
|-----|---------|-----------|
| core | Actively imported at runtime | Appears in import graph from entry roots |
| infra | Build / tooling / config | Known config filenames |
| docs-active | Canonical docs kept in /docs | Under docs/ (non-archive) |
| docs-legacy | Historical, to archive | Named PHASE*, WAVE*, SCOPE* |
| temp-debug | One-off scratch / debugging | Prefix temp_*, debug_* |
| candidate-remove | Unreferenced & unexecuted | No imports inbound + no coverage |
| drift-dup | Duplicated logic to unify | Manual tag (e.g., SSE security duplication) |
| orphan-test | Test references removed feature | Failing import / always skipped reason matches legacy |

## KPIs (Baseline To Capture)

| KPI | Baseline (TBD) | Target |
|-----|----------------|--------|
| total_python_files | (inventory) | -15% Wave B |
| temp_debug_files | (inventory) | -90% Wave A |
| unique_env_vars (G6_*) | (scan) | -10% deprecated removal |
| duplicate_logic_segments | (jscpd/radon) | -20% Wave B |
| avg_full_test_runtime_s | current | -5% Wave C |
| flaky_test_incidents (manual) | current | -50% Wave C |

## Initial Scripts

Scripts added under `scripts/cleanup/`:

* `gen_inventory.py` – Builds structured inventory JSON with heuristic tags.
* `env_scan.py` – Extracts environment variables (G6_*) and emits machine-readable JSON + Markdown table.
* `validate_cleanup.py` – Placeholder for CI gates (to be expanded in Wave B).

## Next Implementation Steps (Completed in Scaffold)

1. Inventory scaffolding created.
2. Environment variable extraction baseline created.
3. Documentation index and environment reference generated.
4. CHANGELOG entry added (scaffolding).

## Follow-Up (To Do)

* Populate KPI baseline file once scripts executed in CI.
* Integrate coverage + dead code (e.g., vulture) into `validate_cleanup.py`.
* Introduce shared SSE security helper (Wave B).
* Archive / remove candidate-remove after one green cycle.

---
Generated: scaffolding version. Refine iteratively.

---

## Dead Code Detection (Tooling Added)

Pipeline components:

1. Vulture scan via `scripts/cleanup/dead_code_scan.py` (excludes tests, archive, data).
2. Lightweight import graph heuristic (placeholder for deeper reachability scoring) builds early signal; integration hook reserved.
3. Allowlist stored in `tools/dead_code_allowlist.json` capturing baseline findings (key: filename:name:line).
4. Report outputs:
	- `tools/dead_code_report.json` (machine readable)
	- `docs/dead_code.md` (human summary)
5. Budget enforcement via `G6_DEAD_CODE_BUDGET` env (CI fail if new > budget).

Adoption Steps:
1. Generate initial baseline: `python -m scripts.cleanup.dead_code_scan --update-baseline`.
2. Commit allowlist + (optionally) first report for historical reference.
3. Add CI job invoking script; publish markdown artifact.
4. During Wave A deletes: remove obvious items, do NOT refresh baseline unless resetting intentionally.
5. After major prune: regenerate baseline to freeze new standard.

Limitations / False Positives:
 - Dynamic attribute / plugin discovery via getattr/env.
 - Test-only utilities not imported by runtime may appear (should move under tests/ or allowlist then refactor).
 - Metaprogrammed registrations (decorator side effects) can show as unused names.

Planned Enhancements:
 - Merge coverage: exclude any symbol executed at least once.
 - AST call graph expansion across functions/methods.
 - Trend line & KPI integration (weekly delta).

Success Metric: Reduce allowlist size 15% per week until < 50, then freeze and enforce zero growth.
