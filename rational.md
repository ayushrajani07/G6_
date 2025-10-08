# Provider + Collector Rationalization & Prioritized Action Plan

_Last updated: 2025-10-07_

## 1. Executive Summary
The provider (`kite_provider.py`) and collector pipeline (`unified_collectors.py` + `modules/expiry_processor.py`) have evolved through layered tactical fixes (resilience, diagnostics, feature flags). This produced: (a) high cyclomatic complexity, (b) diffuse logging semantics, (c) implicit contracts (dict payload morphing), and (d) duplicated environment parsing. This plan formalizes a staged refactor emphasizing safety (shadow mode), observability, and incremental adoption.

Primary goals:
1. Untangle monoliths into explicit phase/state abstractions.
2. Reduce hidden side‑effects and implicit global/env lookups.
3. Normalize logging + metrics emission for predictable operational signals.
4. Provide clear extension points (recovery strategies, persistence, DQ, salvage).
5. Preserve behavior under a controlled feature flag until parity confidence is established.

---
## 2. Current Architecture Snapshot
| Layer | Responsibility (Intended) | Reality | Issue Class |
|-------|---------------------------|---------|-------------|
| Provider (kite_provider) | Auth, instruments, expiries, quotes, diagnostics | Also deprecation shims, fallback fabrication, strike logic | Mixed concerns, >600 LOC |
| Expiry Processing | Per-expiry orchestration | Legacy path still authoritative; shadow pipeline mirrors full phase set | Converging |
| Unified Collectors | Index cycle orchestration | Delegates majority to modules; some legacy helpers remain | Partial extraction debt |
| Recovery (Historical Synthetic) | Provide optional fallback (removed Oct 2025) | Previously extracted & observable in shadow phases (validation, salvage, synthetic) | Simplified |
| Metrics | Registry + dynamic creations | Central adapter introduced; dynamic creation largely removed from hot path | Consolidating |
| Logging | Structured observability | Decision + phase timing logs added; full normalization pending | In progress |

---
## 3. Key Pain Points
1. Monolithic `process_expiry` makes localized changes risky.
2. Recovery (synthetic + salvage) logic intertwined with core path, preventing clean toggling.
3. Environment flags repeatedly parsed (performance + clarity cost).
4. Dynamic metrics creation scatters try/except blocks.
5. Logging duplication and inconsistent severity reduce signal-to-noise.
6. Silent broad `except Exception` blocks mask actionable faults.
7. Provider file conflates resource lifecycle, caching, expiry logic, heuristics, and diagnostics.

---
## 4. Untangling Opportunities
### 4.1 Provider Decomposition
Create internal modules:
- `kite_provider/auth.py`: credential management, `_ensure_client`, lazy init
- `kite_provider/instruments.py`: caching, backoff, retry, TTL adjustment
- `kite_provider/expiries.py`: expiry extraction + fabrication heuristics
- `kite_provider/diagnostics.py`: diagnostics + deprecation shims
- `kite_provider/options.py`: (already exists) remains focused

Introduce `ProviderCore` object aggregated by thin facade class for backward-compatible public API.

### 4.2 Declarative Expiry Pipeline
Replace imperative chain with registered phases.
```
PHASES = [resolve, fetch, prefilter, enrich, validate, salvage,
          coverage, iv, greeks, persist, classify, snapshot, summarize]
```
Each phase: `(ctx, settings, state) -> state`.
State: immutable dataclass (new instance per phase) or controlled mutation with a finalizer.

### 4.3 Config Object (`CollectorSettings`)
Single env hydration pass. Example fields:
```
min_volume, min_oi, volume_percentile,
salvage_enabled, domain_models, trace_enabled,
retry_on_empty, log_level_overrides
```
Populated once at cycle start; passed into per-expiry phases.

### 4.4 Recovery Strategy Abstraction
```
class RecoveryStrategy:
    def on_empty_enriched(self, state) -> bool: ...   # returns early_return
    def attempt_salvage(self, state) -> None: ...
```
Inject a `DefaultRecoveryStrategy` to preserve current behavior; enable easy removal or test substitution.

### 4.5 Metrics Adapter
Predeclare metrics in a spec; stop runtime creation.
```
metrics_api.record_empty_quote_fields(index, rule)
metrics_api.observe_strike_coverage(index, rule, value)
```
Adapter internals gracefully no-op if registry absent.

### 4.6 Logging Normalization
Event naming schema: `domain.phase.outcome`.
Examples:
- `expiry.resolve.ok`
- `expiry.fetch.empty`
- `expiry.prefilter.applied`
- `expiry.validate.fail`
- `expiry.salvage.applied`
- `expiry.persist.fail`

All logs: one line, structured key=value pairs. Dedup logic moved to an `ExpiryLogEmitter` with internal sets.

### 4.7 Error Taxonomy
Define explicit exception subclasses for controlled abort vs fatal. Replace broad catches with:
- `PhaseRecoverableError`
- `PhaseAbortError`
- `PhaseFatalError`
Map to logging: WARNING, INFO (abort expected), ERROR respectively.

---
## 5. Prioritized Action Plan (Comprehensive)
### Phase 0 (Safety Net) – Status: COMPLETE
1. `G6_COLLECTOR_PIPELINE_V2` flag implemented (shadow invoke only).
2. `CollectorSettings` created; expiry filters (volume / OI / percentile stub) centralized and tests added.
3. Metrics adapter layer present; dynamic creation minimized (legacy provider still pending cleanup).

### Phase 1 (Instrumentation & Shadow) – Status: COMPLETE
Implemented `ExpiryState` concept within shadow pipeline, first four phases operational + structural parity checks.
Parity hash v2 stabilizes diff noise; diff logging integrated under DEBUG when mismatches.

### Phase 2 (Functional Migration) – Status: COMPLETE (Shadow)
Preventive validation and salvage behavior represented as discrete observational phases. (Synthetic fallback phase removed Oct 2025; empty enrich results now propagate directly to coverage + alert logic.)
`RecoveryStrategy` protocol and default stub introduced (legacy still uses inline logic).

#### Phase 2 Progress (2025-10-06)
Shadow pipeline now includes preventive validation (`phase_preventive_validate`) and salvage simulation (`phase_salvage`).
`recovery.py` introduces a `RecoveryStrategy` protocol and `DefaultRecoveryStrategy` stub (not yet invoked by legacy path). Salvage currently mirrors legacy foreign expiry salvage criteria for observation only.
Next steps before any functional switch consideration:
- (Historical – removed) Integrate synthetic fallback as a discrete shadow phase.
- Attach timing/metrics adapter instrumentation per phase.
- Add parity hash computation to suppress noisy diffs for large strike universes.

### Phase 3 (Post-Processing & Metrics) – Status: COMPLETE (Shadow)
Coverage, IV, Greeks, persist(sim) parity instrumentation and timing integrated. Metrics adapter recording parity & structural stats.

### Phase 4 (Provider Modularization) – Status: ADVANCED / NEAR COMPLETE
Provider modules (auth, instruments, expiries, diagnostics, options, startup, rate limiter, structured events) now extracted. Facade delegates to:
- `provider_core` (rate limiter + startup summary)
- `auth` (ensure/update credentials wrappers)
- `instruments`, `expiry_discovery`, `options`, `diagnostics`, `provider_events`
Residual future split candidates (post-removal focus): further provider surface slimming & phase event instrumentation. Synthetic quote counters & fallback heuristics no longer applicable.

### Phase 5 (Logging Overhaul) – Status: PARTIAL (Provider Complete)
Provider side now emits gated structured JSON events (`provider.kite.<domain>.<action>.<outcome>`) behind `G6_PROVIDER_EVENTS`/`G6_STRUCT_LOG`. Pipeline expiry phases still on legacy mixed formatting; next logging focus shifts to expiry pipeline normalization and phase outcome schema adoption.

### Phase 6 (Clean Removal / Hardening) – Status: PARTIAL (Taxonomy Applied, Env Cleanup Done)
Provider error taxonomy applied via `_raise_classified`; broad duplicate raise cascades removed. Residual env lookups confined to `settings.py` snapshot hydration and intentional option path gating; dynamic metric creation eliminated in provider modules. Remaining hardening: pipeline phase structured log convergence + potential deprecation shim removal after observation window.

### Phase 7 (Optimization & Polish) – Status: IN PROGRESS
Shadow gating operational with promotion, churn, rollback, protected diff safeguards. Authoritative promotion flag and manual demote implemented. Benchmarks & design doc outstanding.

### Phase 8 (Cutover & Decommission) – Status: PLANNED
Criteria-based switch of authoritative path; legacy path retained behind `G6_COLLECTOR_PIPELINE_LEGACY_FORCE`. Remove deprecated dynamic patterns post-stabilization.

---
## 6. Detailed Action Items with Acceptance Criteria (Refreshed)
| ID | Action | Status | Criteria | Notes |
|----|--------|--------|----------|-------|
| A1 | Implement `CollectorSettings` | DONE | Env refs replaced in expiry filters | Tests added (`test_collector_basic_filters.py`) |
| A2 | Feature flag gating (shadow) | DONE | Flag triggers shadow parity & logs | `G6_COLLECTOR_PIPELINE_V2` operational |
| A3 | `ExpiryState` + first 4 phases | DONE | Structural parity stable; low diff rate | Parity hash v2 reduces noise |
| A4 | RecoveryStrategy extraction | DONE (stub) | Protocol + default present | Not yet wired into legacy path |
| A5 | Logging rename pass (initial) | PARTIAL | Some structured logs present | Needs schema rollout |
| A6 | Metrics adapter insertion | DONE (expiry path) | No new dynamic metrics in expiry path | Provider pending cleanup |
| A7 | Provider modular split | ADVANCED | Core + auth + instruments + expiries + options + diagnostics + structured events extracted; facade slimmed | Further splits optional |
| A8 | Pipeline switchover | PENDING | Flag on parity (<1% option count delta) | Requires A7 + perf baseline |
| A9 | Remove legacy dynamic metrics | DONE | No dynamic metric registration in provider modules after sweep | Future additions go through spec |
| A10 | Benchmark + doc | PENDING | Timing report & `PIPELINE_DESIGN.md` committed | After modularization |
| A11 | Gating robustness (rollback/churn) | DONE | Rollback metrics & decisions logged | Protected + churn windows active |
| A12 | Authoritative promotion flag | DONE | Promotion sets `authoritative` under env | Force demote overrides tested |
| A13 | Provider skeleton (core/auth/instruments/expiries/diagnostics placeholders) | DONE | Modules + facade merged, tests passing | Patch 1 scaffolding added 2025-10-07 |
| A14 | Auth lifecycle migration (lazy init + env discovery in AuthManager) | DONE | AuthManager handles ensure_client & env creds | Incremental migration 2025-10-07 |

---
## 7. Phase Execution Driver Sketch
```python
@dataclass
class ExpiryState:
    index: str
    rule: str
    expiry_date: date|None = None
    strikes: list[int|float] = field(default_factory=list)
    instruments: list[dict] = field(default_factory=list)
    enriched: dict[str, dict] = field(default_factory=dict)
    expiry_rec: dict[str, Any] = field(default_factory=lambda: {})
    errors: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)

class Phase(Protocol):
    name: str
    def run(self, ctx, settings: CollectorSettings, state: ExpiryState) -> ExpiryState: ...

def execute_pipeline(ctx, settings, state, phases: list[Phase]):
    for phase in phases:
        start = time.perf_counter()
        try:
            state = phase.run(ctx, settings, state)
        except PhaseRecoverableError as e:
            state.errors.append(f"recoverable:{phase.name}:{e}")
            break
        except PhaseAbortError as e:
            state.errors.append(f"abort:{phase.name}:{e}")
            return state
        except Exception as e:
            state.errors.append(f"fatal:{phase.name}:{e}")
            break
        finally:
            dt = (time.perf_counter()-start)*1000
            logger.debug("expiry.phase.timing phase=%s ms=%.2f index=%s rule=%s", phase.name, dt, state.index, state.rule)
    return state
```

---
## 8. A23 Consolidated Settings Migration (2025-10-07)

Phase 3 of A23 replaced hot-path environment lookups with hydrated fields on `CollectorSettings`.

Added fields:
- quiet_mode / quiet_allow_trace
- trace_collector (alias trace_enabled retained)
- loop_heartbeat_interval
- provider_outage_threshold / provider_outage_log_every
- (Removed) disable_synthetic_fallback
- foreign_expiry_salvage (plus legacy salvage_enabled)
- recovery_strategy_legacy

Refactored modules:
- unified_collectors: heartbeat, outage classification, trace gating
- modules/expiry_processor: salvage precedence, recovery strategy toggle (synthetic disable path removed)
- providers_interface: concise mode now delegates to provider helper `is_concise_logging()`

Regression coverage: `tests/test_collector_settings_flags.py` validates parsing & precedence.

Next (A24): strip remaining legacy env fallbacks after deployment verification window.

## 9. A24 Deprecations (Initiated 2025-10-07)

Executed:
- Provider shim `src.providers.kite_provider` hard-removed (now raises ImportError).
- Synthetic fallback removal eliminated prior disable checks; pipeline phases no longer branch on fabricated data.
- Outage classification and heartbeat gating rely solely on settings (env reads retained only as transitional fallback comments where removal planned 2025-10-20).

Planned final removals (post stability window):
- Eliminate any residual transitional fallback branches referencing deprecated env flags.
- Remove duplicate salvage flag alias logic (retain `foreign_expiry_salvage`).
- Collapse `trace_enabled` alias leaving `trace_collector` canonical.

Risk Mitigation:
- Immutability regression tests added (`test_collector_settings_immutability.py`).
- Fallback branches instrumented only via code comments; no runtime divergence expected.
- One-shot structured log `collector.settings.summary ...` now emitted on first settings hydration for operational visibility (flags, thresholds, gating state). Guarded by in-process sentinel to avoid spam.
    - Optional multi-line human block enabled with `G6_SETTINGS_SUMMARY_HUMAN=1` for readability (aligned key/value list). Falls back silently if formatting helper not available.
        - Extended pattern: `provider.kite.summary` (enable multi-line with `G6_PROVIDER_SUMMARY_HUMAN=1`) and `metrics.registry.summary` (enable multi-line with `G6_METRICS_SUMMARY_HUMAN=1`). One-shot emission guarded by sentinels; safe under repeated imports/tests.
## 8. Logging Strategy
| Event | Level | Emit Conditions |
|-------|-------|-----------------|
| `expiry.resolve.ok` | DEBUG/INFO (concise flag) | Successful rule resolution |
| `expiry.fetch.empty` | WARNING (dedup) | No instruments first time per cycle |
| `expiry.fetch.count` | DEBUG | Post-fetch instrumentation |
| `expiry.prefilter.applied` | DEBUG | Prefilter reduced set |
| `expiry.validate.fail` | WARNING | Preventive validation flagged issues |
| `expiry.salvage.applied` | WARNING | Foreign expiry salvage executed |
| `expiry.persist.fail` | ERROR | Persistence fail (non-recoverable) |
| `expiry.coverage.metrics` | DEBUG | Coverage ratios computed |
| `expiry.complete` | INFO | Success summary (options, coverage) |

`_trace` downgraded to DEBUG; escalate with `G6_TRACE_COLLECTOR_FORCE_WARN` if needed.

---
## 9. Metrics Migration
Steps:
1. Inventory dynamic creations (grep for `Counter(`, `Gauge(` inside collectors modules).
2. Add formal spec entries (names + help text) or ensure existing ones cover them.
3. Introduce `metrics/api.py` with stable surface.
4. Update expiry phases to invoke adapter only.
5. Delete dynamic creation blocks + tests asserting existence still pass.

Rollback Plan: Keep adapter shim returning dynamic creation for one interim release behind `G6_METRICS_ADAPTER_FALLBACK=1`.

---
## 10. Risk Matrix
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Hidden dependency on legacy log strings | M | M | Dual emit under compatibility flag during transition |
| Performance regression from object churn | M | M | Benchmark & optimize after functional parity confirmed |
| State divergence in shadow mode causing noise | L | L | Hash stable subset for quick equality instead of full deep diff |
| Metrics cardinality drift | L | H | Pre-merge snapshot compare using cardinality guard existing tooling |
| Test flakiness due to timing changes | M | M | Keep legacy path default until deterministic tests pass on CI 2 cycles |

---
## 11. Timeline (Indicative)
| Week | Milestones |
|------|------------|
| 1 | Phase 0 + 50% of Phase 1 (shadow resolve/fetch) |
| 2 | Complete Phase 1; begin Phase 2 (recovery & salvage) |
| 3 | Phase 3 (metrics/coverage/iv/greeks/persist) shadow fully working |
| 4 | Cutover flag default ON in staging; provider split start |
| 5 | Provider modularization complete; logging overhaul |
| 6 | Cleanup, remove legacy branches, performance tuning |

---
## 12. Initial Implementation Target (Suggested First Patch)
1. Add `CollectorSettings`.
2. Replace env parsing in `expiry_processor` (volume/oi/percentile/salvage/domain_models flags) with settings.
3. Introduce helper `apply_basic_filters(enriched, settings)`.
4. Add unit test verifying filters are applied deterministically with mock data.

---
## 13. Success Metrics
| Dimension | Metric | Baseline | Target |
|-----------|--------|----------|--------|
| Complexity | `expiry_processor.py` LOC | ~600 | <250 (core) |
| Test Time | Avg full test suite | X (capture) | +0–5% max |
| Logging | WARN lines per cycle (normal market) | N (capture) | -50% |
| Observability | Structured event coverage | Ad-hoc | 100% phases |
| Incidents | Hotfix frequency in expiry logic (monthly) | >1 | <0.25 |

---
## 14. Appendix: Snapshot of Current Issues (Grep Topics)
- Dynamic metrics: `empty_quote_fields_total` creation inline.
- Foreign expiry salvage heuristic embedded (difficult to tune independently).
- Repeated env lookups: `G6_FILTER_MIN_VOLUME`, `G6_FOREIGN_EXPIRY_SALVAGE`, etc.
- Logging duplication (pre-dedup improvements now partially addressed).

---
## 15. Next Steps (Actionable)
1. Complete structured logging schema for remaining provider & pipeline phases (iv, greeks, persist, classify, snapshot) – (A19 extension).
2. Apply error taxonomy (`PhaseRecoverableError`, etc.) and replace broad `except` usage.
3. Remove residual dynamic metrics & stray env lookups in provider (A23).
4. Implement authoritative cutover flag evaluation & dashboard panels wiring (pre-A24).
5. Execute parity observation window & populate PIPELINE_DESIGN.md tracking table.
6. Perform rollback drill and document results in `PIPELINE_DESIGN.md`.

---
Progress logged through 2025-10-07; next reporting checkpoint after provider modular skeleton merged.

---
Feel free to request the first patch implementation; it is scoped for rapid, low-risk introduction.
