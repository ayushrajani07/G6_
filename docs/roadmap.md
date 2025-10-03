# Phase 5 Operational Hardening & Data Governance Roadmap

_Last generated: 2025-10-01_

## Purpose
Shift from consolidation + deprecation cleanup to long-horizon operational resilience, data lifecycle safety, observability maturity, and governance automation.

## High-Level Goals
1. Data retention (optional, guarded) – prevent unbounded growth.
2. Metrics & cardinality maturity – spec-driven, enforce naming & group constraints.
3. Deprecation window execution – automated hygiene detection (R+1 enforcement).
4. Panel & snapshot trust – schema versioning, optional signing, severity metrics.
5. Failure isolation – fault budget metrics, memory pressure tier 3 scaling.
6. Release/onboarding polish – unified CLI, minimal bundle, token JSON output.
7. Coverage uplift (critical modules only) – ring-fenced reliability.

## Issue Catalogue (Condensed)
| Domain | Representative Issues | Impact |
|--------|-----------------------|--------|
| Env / Docs | Duplicate entries, lingering aliases | Drift & confusion |
| Metrics | No authoritative spec, gating drift risk | Silent regressions |
| Panels | No schema version negotiation test | Harder evolution |
| Tests | Timing guard only; no slow-test trend | Performance creep |
| Resilience | No fault budget counters, tier 3 incomplete | Slower incident insight |
| Retention | Infinite retention only | Storage risk |
| CLI Surface | Fragmented entry scripts | Cognitive load |

## Solution Patterns
- Spec → Code → Test loop.
- Guard (warn) → Enforce (fail) after one release.
- Baselines as contracts (metrics groups, slow tests, critical coverage set).

## Phase Breakdown
### Phase A – Governance Backbone (Week 1–2)
- Env doc duplicate linter test.
- Metrics spec (YAML) + registry conformance test.
- Panel `schema_version` injection + version test.

### Phase B – Unified CLI (Week 2–3)
- Introduce `scripts/g6.py` (collect, summary, simulate, integrity, bench, retention).
- Deprecate legacy wrappers (emit one-time warnings).

### Phase C – Test & Perf Discipline (Week 3–4)
- Slow test reporter plugin + baseline.
- Critical module coverage guard (≥70%).
- TRACE logging level modernization.

### Phase D – Resilience (Week 4–5)
- Fault budget counters & downgrade logic.
- Memory pressure tier 3 strike depth scaling.

### Phase E – Retention (Week 5–6)
- Dry-run retention scanner + metrics.
- Optional active pruning with safety checks.

### Phase F – Panel Trust (Week 6–7)
- Manifest signing (HMAC) optional.
- Integrity severity metrics.

### Phase G – Observability & DQ (Week 7–8)
- DQ aggregate metrics & panel.
- Error taxonomy normalization.

### Phase H – Cleanup & Removal (R+1)
- Remove archived README stubs & obsolete flags.
- Final CHANGELOG & deprecation hygiene confirmation.

## Success Metrics
| Goal | Metric | Target |
|------|--------|--------|
| Governance health | Env/metrics/panel tests | 100% green |
| Slow test control | New >2s unmarked | 0 |
| Critical coverage | Each critical module | ≥70% |
| Panel integrity | Hash mismatches normal run | 0 |
| Retention safety | Accidental pruning today | 0 |
| Cardinality drift | Series spike without note | <10% |
| Resilience reaction | Recovery cycles (post fault) | <2 |

## Risk Mitigation
| Risk | Mitigation |
|------|-----------|
| Over-enforcement friction | Stage in warn mode first |
| Retention misconfiguration | Dry-run default + protect_today |
| Spec drift | PR template section: “Update metrics_spec?” |
| Panel version churn | Provide N-1 compatibility shim |

## Immediate Start Checklist
1. Add `docs/metrics_spec.yaml` + seed core stable metrics.
2. Implement `tests/test_metrics_spec.py` verifying presence & structure.
3. Add env duplicate detection test.
4. Insert `schema_version` key in panel writer & test.
5. Commit baseline before adding higher-risk features.

## Proposed Metrics Spec Structure (Excerpt)
```yaml
- name: g6_iv_estimation_success_total
  type: counter
  labels: [index, expiry]
  group: iv_estimation
  stability: stable
  description: Successful IV solves
- name: g6_panels_integrity_ok
  type: gauge
  labels: []
  group: panels_integrity
  stability: stable
  description: 1 when all panel hashes match manifest
```

## Panel Schema Versioning
- Add `schema_version` (int) at panel root.
- Maintain constant in `src/panels/version.py`.
- Test: All emitted panels share expected version; bump requires updating golden.

## Retention Safeguards (Draft Config)
```json
"retention": {
  "enabled": false,
  "dry_run": true,
  "max_age_days": 45,
  "protect_today": true,
  "prune_csv": true,
  "prune_influx": false
}
```

## Critical Module Candidates
- `src/utils/symbol_root.py`
- `src/panels/validate.py`
- `src/metrics/metrics.py`
- `src/storage/csv_sink.py`
- `src/collectors/unified_collectors.py`

## Naming Conventions (Enforce Gradually)
- Counters: `_total` suffix.
- Histograms: `<base>_seconds` + `_bucket/_sum/_count`.
- Gauges: no `_total` suffix.

## Deprecation Hygiene Test Outline
1. Parse `DEPRECATIONS.md`.
2. For rows with status REMOVED: grep repo for symbol (expect none).
3. For rows with earliest removal date < today and still active: warn/fail.

---
_This roadmap is a living document; adjust sequencing as emergent risks surface._

---
## Completed Milestone: Metrics Modularization & Facade Adoption (2025-10-02)
Status: COMPLETE

Deliverables Achieved:
- Facade exports stabilized (`src/metrics/__init__.py`); all internal/test code migrated.
- Legacy deep import path retained with optional deprecation warning flag (`G6_WARN_LEGACY_METRICS_IMPORT`).
- Group gating + metadata extraction validated; synthetic supplementation logic in place.
- Environment variable documentation debt eliminated (coverage & duplicates tests green, zero baseline).
- Migration guide updated with completion criteria & future removal conditions.

Impact:
- Reduced coupling to monolithic `metrics.py`.
- Faster cold test imports (target future measurement ticket).
- Clear boundary for future per-domain metric module extraction.

Risks Remaining:
- Deep import still available (accidental reintroduction risk) until default warning enabled.
- Some domain families (risk aggregation, vol surface) still defined in core registry class.

Follow-On Targets (Queued for Next Governance Phase):
1. Metrics Spec Authoring
  - Create `docs/metrics_spec.yaml` enumerating core stable metrics (name, type, labels, group, stability, deprecation fields).
  - Add conformance test ensuring registry subset ≥ spec set (warn on unknown metrics to detect drift).
2. Domain Module Extraction
  - Extract volatility surface metrics initialization into `src/metrics/vol_surface.py` (imported lazily by facade).
  - Extract risk aggregation metrics into `src/metrics/risk_agg.py`.
  - Provide guarded import to avoid import-time side effects when feature gated.
3. Default Warning Enablement
  - Flip default: emit deep import deprecation warning unless `G6_SUPPRESS_LEGACY_METRICS_WARN=1`.
  - Timeline: after one full release (R+1) with no regressions.
4. Cardinality Guard Enhancements
  - Track per-group metric count & detect >X% growth vs baseline snapshot.
  - Optional CI fail if cardinality spike unaccompanied by CHANGELOG note.
5. Build Info Extensions
  - Add optional `config_hash` provenance diff panel & metric pairing to surface config drift live.
6. Performance Measurement
  - Benchmark import latency pre/post modularization (script: `scripts/metrics_import_bench.py`).
7. Registry Health Diagnostics
  - Add `g6_metric_duplicates_total` counter incremented when duplicate registration attempts are caught & suppressed.
8. Removal Criteria Execution
  - Once spec + warning default active for ≥2 releases and zero deep imports detected, remove compatibility shim code paths.

Decision Log References:
- CHANGELOG [Unreleased]/Completed Metrics Modularization entry.
- `docs/METRICS_MIGRATION.md` section 10 (completion status & safe removal criteria).

Ownership & Next Step:
- Assign metrics spec authoring to Governance WG.
- Open tracking issue: “Metrics Spec & Conformance Test” linking to this section.
