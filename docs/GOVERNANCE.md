# Platform Governance & Quality Gates

_Last updated: 2025-10-05_

This document codifies the operational governance model for the G6 platform: KPIs,
quality gates (CI enforcement), deprecation & consolidation policies, and
lifecycle states for major components.

## 1. Objectives

1. Sustain reliability & determinism (flake rate reduction, bounded latency).
2. Prevent silent regression (coverage & orphan test gates).
3. Minimize maintenance drag (dead code budget, doc consolidation).
4. Provide auditable change process (waves, KPIs, CI outputs).
5. Enable safe, incremental refactors with explicit rollback criteria.

## 2. Key Performance Indicators (KPIs)

| KPI | Definition | Target | Source | Notes |
|-----|------------|--------|--------|-------|
| Flake Rate | (# intermittent test reruns required)/(total test jobs) | < 1% | CI logs / retry stats | Tracked per week |
| Coverage (Lines) | Cobertura line-rate percent | >= Baseline & no drop > allowed | `coverage.xml` + baseline JSON | Gate enforced |
| Dead Code Budget | Count of new high-confidence unused symbols above baseline | 0 (strict) | `dead_code_scan.py` | Exploratory low-confidence ignored |
| File Reduction | Removed or archived redundant scripts/docs count | +X per wave (trend) | Inventory diff | Qualitative improvement |
| Env Var Drift | Referenced-but-uncataloged env vars | 0 | `env_catalog_check.py` | Strict fail on missing |
| Docs Index Freshness | Missing canonical docs from index | 0 | `doc_index_check.py` | | 
| Orphan Tests | Heuristic orphans detected | 0 | `orphan_tests.py` | Exceptions require allowlist |
| SSE Latency p95 | Emit->flush latency histogram (sse_flush) | SLA defined (TBD) | Prometheus | Observed not gated yet |
| Panel Diff Truncations | panel_diff_truncated_total rate | Non-increasing | Prometheus | Monitor fragmentation |

## 3. CI Quality Gates (validate_cleanup.py)

Current enforced sequence (fail-fast):
1. Inventory & env var counts logged (informational)
2. Coverage non-regression: absolute floor `G6_COVERAGE_MIN_PCT` (default 70.0) and max drop `G6_COVERAGE_MAX_DROP` (default 2.0pp) vs `tools/coverage_baseline.json`
3. Dead code scan: budget via `G6_DEAD_CODE_BUDGET` (default 0). Implemented by `scripts/dead_code_scan.py`; optional pytest gate with `G6_RUN_DEAD_CODE_SCAN=1`.
4. Orphan test scan: fails if any triaged orphan qualifies (>=3 reasons including `no_local_imports`)
5. Env catalog freshness (`env_catalog_check.py`): missing vars fail; stale only fails if `G6_ENV_CATALOG_STRICT=1`
6. Docs index freshness (required canonical docs present)

All gates must log explicit PASS lines; the final line: `[validate-cleanup] all gates passed`.

## 4. Dead Code Policy

- Detection Tooling: `scripts.cleanup.dead_code_scan` (vulture + custom import graph)
- Confidence: Only high-confidence items (vulture default) enforced; exploratory (low-confidence) surfaced for inspection.
- Budget: `G6_DEAD_CODE_BUDGET` allows temporary tolerated count (used sparingly during large refactors). Enforced using `scripts/dead_code_scan.py` (CI step) and `tests/test_dead_code_scan_optional.py` when opt-in env set.
- Removal Process: Mark candidate -> ensure 0 test references -> archive/delete in next wave with CHANGELOG note.

## 5. Documentation Consolidation Policy

Principles:
- One canonical narrative per domain (SSE, Metrics, Env, Config).
- Auto-generated exhaustive lists (env, metrics catalog) separated from curated narrative.
- Stubs retained for one deprecation window (>= 1 release) before removal.

Current Stubs (to remove after window):
- `SSE_ARCHITECTURE.md`, `SSE_SECURITY.md`
- `metrics_dict.md`, `metrics_generated.md`
- `env_dict.md`

Removal Criteria: no inbound code/test links + index updated + CHANGELOG deprecation entry.

## 6. Deprecation Lifecycle

| Stage | Label / Doc Note | Allowed Usage | Actions |
|-------|------------------|---------------|---------|
| Proposed | tracked in DEPRECATIONS.md | Existing only | Collect references / impact |
| Warning | CHANGELOG + optional runtime warn | Discouraged | Provide migration instructions |
| Deprecated | Marked final removal date | Avoid new usage | Block in new code review |
| Removed | Code deleted / stub left | None | Stub removed next release |

## 7. Refactor & Removal Waves

- Wave A: Safe deletes (dead scripts, demo HTML, temp debug) – complete.
- Wave B: Structural refactors (SSE shared extraction Phase 1 & 2) – complete.
- Wave C: In-progress governance & doc consolidation (current phase).

Rollback Safety:
- Each refactor guarded by existing tests (SSE security, metrics, panels integrity)
- Logs & metrics parity snapshot scripts (e.g., `gen_parity_snapshot.py`) available to verify no behavior drift.

## 8. Environment Variable Governance

Sources of truth:
- Auto scan output (`ENVIRONMENT.md`) – exhaustive table
- Catalog JSON (`tools/env_vars.json`) – used by freshness gate
- Feature toggles narrative (`CONFIG_FEATURE_TOGGLES.md`)

Mutation Rules:
- New variable MUST appear in scan + narrative (if toggle) in same PR
- Renames: add alias handling + deprecation entry until removal
- Hard removal: require 2 releases with warning unless security-critical

## 9. Metrics Governance

Canonical references:
- Narrative (`METRICS.md`)
- Auto catalog (`METRICS_CATALOG.md`)

Rules:
- New metric: must include description, labels, cardinality notes.
- High-cardinality families require gating or documented justification.
- Removals: add NOTE line in `METRICS.md` with last release version.

## 10. SSE & Streaming Governance

- Shared module `sse_shared.py` centralizes security & framing.
- Token bucket + auth/UA/IP logic covered by tests; any new headers or filters require test addition.
- Future planned gate: latency p95 regression detection (TBD instrumentation diff script).

## 11. Ownership & Review

| Area | Owner (Role) | Review Cadence |
|------|--------------|----------------|
| Env Catalog | Platform Infra | Weekly drift scan report |
| Metrics Taxonomy | Observability | Bi-weekly / on additions |
| SSE Security | Streaming | Every change to `sse_shared.py` |
| Dead Code Budget | Core Eng | Each refactor PR |
| Docs Index | Tech Writing | Weekly quick scan (script) |

(Owners are role placeholders; adjust to specific individuals in internal tracker.)

## 12. CHANGELOG & Release Hygiene

Each release PR must include:
- Coverage diff vs baseline (non-regression statement)
- Dead code delta (count increase must justify budget usage)
- Deprecations progressed stage table
- Removed stubs list (if any)

## 13. Exceptions Process

If a gate blocks urgent production fix:
1. Justify exception (impact, scope, rollback plan)
2. Apply temporary env override (e.g. raise drop threshold) in CI only
3. Open follow-up issue to restore baseline within 24h

## 14. Future Enhancements (Planned)

| Idea | Benefit | Status |
|------|---------|--------|
| Latency regression gate (SSE flush p95) | Early perf detection | Spec drafting |
| Panel diff size anomaly detection | Prevent UI degradation | Prototype in metrics |
| Auto doc index generator | Eliminate manual index drift | Planned script |
| SBOM & provenance (g6-sbom, g6-provenance) | Supply chain audit | CLI placeholders exist |
| Flake rate tracker script | Quantify stability improvements | Not started |

## 15. Removal Watchlist

| Artifact | Rationale | Target Release |
|----------|-----------|----------------|
| `metrics_dict.md` | Stub – consolidated | R+1 |
| `metrics_generated.md` | Stub – consolidated | R+1 |
| `env_dict.md` | Stub – consolidated | R+1 |
| `SSE_ARCHITECTURE.md` | Stub – merged | R+1 |
| `SSE_SECURITY.md` | Stub – merged | R+1 |

## 16. Glossary

- Baseline Coverage: Stored in `tools/coverage_baseline.json`.
- Orphan Test: Test file with no local imports, no asserts, no marks, and no coverage hits.
- Dead Code Budget: Temporary permitted count of new unused items.
- Deprecation Window: Minimum one full release cycle before permanent removal.

---
Feedback / adjustments: update this document in the same PR as gate or policy changes.
