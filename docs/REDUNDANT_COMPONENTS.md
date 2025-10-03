# Redundant / Legacy / Candidate for Removal Components

> Source: Extracted from `docs/cleanup.md` Phase 1 analysis. Status labels: ACTIVE (in use), LEGACY (superseded but still present), REDUNDANT (duplicate functionality), DEPRECATED (announce removal), REMOVE_CANDIDATE (safe to excise after validation).

## Legend
- Impact: LOW (isolated), MED (some scripts/tests), HIGH (core loop)
- Action Codes: AUDIT, MERGE, RETIRE, REWRITE, KEEP (document), SPLIT (modularize)

## 1. Scripts
| Path | Status | Issue | Impact | Proposed Action |
|------|--------|-------|--------|-----------------|
| `scripts/g6_run.py` | LEGACY | Overlaps with `run_orchestrator_loop.py` | LOW | RETIRE after confirming CI/dev not depending |
| `scripts/status_to_panels.py` | TRANSITIONAL | Bridge for panels (legacy path) | MED | MERGE into unified summary emission pipeline |
| `scripts/init_menu.py` | REDUNDANT | Setup/utility not part of core workflow | LOW | AUDIT usage; REMOVE_CANDIDATE if unused in tooling |
| `scripts/dev_tools.py` | MIXED | Misc dev functions (simulate-status, summary) duplicates specialized scripts | LOW | SPLIT into focused utilities or deprecate duplicates |
| `scripts/summary_view.py` (legacy code paths) | PARTIAL LEGACY | Contains V1 + V2 rendering toggles | MED | STRIP legacy branches after model layer extraction |
| `scripts/status_simulator.py` | KEEP (Document) | Essential for deterministic tests/dev | LOW | Document scenario usage |

## 2. Metrics & Observability
| Component | Status | Issue | Impact | Proposed Action |
|-----------|--------|-------|--------|-----------------|
| `src/metrics/metrics.py` monolith | OVERGROWN | All metric groups intertwined | HIGH | SPLIT into registry + group modules |
| Cardinality adaptive toggles proliferation | SPRAWL | Many fine-grained flags | MED | CONSOLIDATE under structured config |

## 3. Environment Flags
| Pattern | Status | Issue | Impact | Proposed Action |
|---------|--------|-------|--------|-----------------|
| Wildcard suffix `_` groups (e.g., `G6_BENCHMARK_`) | INDETERMINATE | Hard to statically audit | MED | INVENTORY -> Replace with explicit grouped config |
| Duplicate enable flags (`G6_METRICS_ENABLE` vs `G6_METRICS_ENABLED`) | DUPLICATE | Confusion / drift | LOW | DEPRECATE one & map to canonical |
| Legacy summary flags (`G6_SUMMARY_LEGACY`, `G6_ALLOW_LEGACY_*`) | DEPRECATION PENDING | Transitional only | MED | Schedule removal after parity tests |

## 4. Output / Panels Pipeline
| Component | Status | Issue | Impact | Proposed Action |
|-----------|--------|-------|--------|-----------------|
| Legacy panels bridge | TRANSITIONAL | Two-step (status file -> panels) | MED | MERGE: direct model -> panel artifacts |
| Mixed sinks (`stdout,logging,panels`) | DUPLICATE CONFIG | Hard-coded parsing | LOW | Centralize sink parsing & validation |

## 5. Storage / Snapshots
| Component | Status | Issue | Impact | Proposed Action |
|-----------|--------|-------|--------|-----------------|
| Multiple snapshot formats (parity vs auto) | REDUNDANT | Divergent naming & retention | LOW | UNIFY under versioned snapshot manager |
| CSV analytics dumps vs Influx | PARTIAL OVERLAP | Two persistence paths | MED | Evaluate usage; possibly gate with strategy pattern |

## 6. Adaptive / Alerting
| Component | Status | Issue | Impact | Proposed Action |
|-----------|--------|-------|--------|-----------------|
| Severity trend experimental vars (`G6_ADAPTIVE_SEVERITY_TREND_*`) | SPRAWL | Hard to tune cohesively | MED | GROUP + derive composite config |
| Strike logic flags (`G6_ADAPTIVE_STRIKE_*`) | VERBOSE | Many small knobs | MED | Provide aggregated profile presets |

## 7. Testing / Governance
| Component | Status | Issue | Impact | Proposed Action |
|-----------|--------|-------|--------|-----------------|
| Environment coverage test | INCOMPLETE | Lacks auto inventory integration | LOW | EXTEND to consume JSON inventory |
| Redundant smoke scripts | REDUNDANT | Overlapping manual flows | LOW | CONSOLIDATE into parametrized pytest-based smoke |

## 8. Removal Candidates Queue
| Item | Preconditions | Validation Steps | Target Phase |
|------|--------------|------------------|--------------|
| `scripts/g6_run.py` | Confirm no CI references | Search repo & run grep; update docs | Phase 2 |
| Duplicate metrics enable var | Introduce canonical flag | Map old->new & add warning | Phase 2 |
| Legacy summary toggles | Achieve parity snapshot | Run side-by-side diff harness | Phase 3 |
| Panels bridge script | Unified emission implemented | Provide migration doc | Phase 3 |

## 9. Tracking & Next Actions
- Add JSON inventory extension (feeds env duplicate detection)
- Build config loader scaffold to centralize reads (collect impact stats)
- Start metrics module slicing proof-of-concept (non-invasive wrapper)
- Draft deprecation policy doc snippet (could embed into `env_dict.md`)

---
Document will be updated as audits validate real-world usage and as phased removals happen.
