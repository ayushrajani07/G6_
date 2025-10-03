# Orchestrator vs Legacy Collection Loop Parity Matrix

_Last updated: 2025-09-27_

Purpose: Historical parity checklist between the orchestrator `run_loop` + `run_cycle` path and the (now removed) legacy `collection_loop`. Legacy loop & gating flag `G6_ENABLE_LEGACY_LOOP` were removed on 2025-09-28 after sustained green parity.

Legend:
- ✅ Parity confirmed (tests and/or manual verification)
- ⚠️ Partial (behavior differs intentionally or needs follow-up)
- ⏳ Pending validation / not yet implemented in orchestrator
- ❌ Missing (gap requiring implementation before removal) 

| Category | Feature / Behavior | Legacy Source (illustrative) | Orchestrator Component | Status | Notes / Follow-Up |
|----------|--------------------|-------------------------------|------------------------|--------|-------------------|
| Core Cycle | Interval control & sleep pacing | `collection_loop` interval calc | `run_loop` scheduler | ✅ | Interval env / config precedence matches (tests) |
| Core Cycle | Market hours gating (`market_hours_only`) | Inline market open checks | `market_hours.should_run_cycle` logic | ✅ | Force-open env honored identically |
| Core Cycle | Run-once bounded execution | `run_once` + status file check | `--run-once` flag handling | ✅ | Both exit after first successful cycle |
| Core Cycle | Max cycles via env (`G6_MAX_CYCLES`) | Legacy loop `G6_MAX_CYCLES` | `G6_LOOP_MAX_CYCLES` (orchestrator) | ✅ | Alias implemented: orchestrator honors both; prefer `G6_LOOP_MAX_CYCLES` going forward (legacy alias retained). |
| Providers | Composite provider failover | Pre-provider call block | Provider facade + failover wrapper | ✅ | Fail-fast flag parity confirmed |
| Providers | Parallel per-index collection | Not implemented (sequential) | `run_cycle` parallel workers | ✅ | Orchestrator superset; legacy intentionally lacks |
| Providers | Domain model emission (snapshots) | N/A | `snapshot_collectors` + snapshot cache | ✅ | Orchestrator-only feature (no parity needed) |
| Metrics | Cycle duration histogram | Absent | `g6_cycle_time_seconds` | ✅ | Superset; no legacy equivalent |
| Metrics | SLA breach & missing cycle detection | Inline timers | Central in `run_cycle` | ✅ | Counters align with design |
| Metrics | Per-index attempt/failure attribution | Inline collection code | Metrics adapter + guard | ✅ | Normalized via adapter |
| Metrics | Cardinality guard disablement | N/A | `cardinality_guard` module | ✅ | Orchestrator-only (documented) |
| Metrics | Deprecated usage counters | Legacy loop warning path | Central metrics + deprecation registry | ✅ | Legacy increments on gated use |
| Adaptive | Strike depth scaling | N/A | `adaptive_strike_scaling` | ✅ | Orchestrator-only; no parity required |
| Adaptive | Multi-signal controller (future) | N/A | Planned controller | ⏳ | Will land Phase 2 |
| Storage | CSV sink invocation semantics | Direct call per cycle | Same sink called in `run_cycle` | ✅ | Verified identical call contract |
| Storage | Junk row suppression | Implemented in sink (shared) | Shared | ✅ | Behavior identical (centralized) |
| Expiry | Misclassification remediation policy | Shared sink logic | Shared sink logic | ✅ | Centralized path ensures parity |
| Events | Event log emission (cycle_start/end) | Inline writes | Unified event bus | ✅ | Normalized formatting (parity harness OK) |
| Panels | Periodic status snapshot timing | After each cycle end | After cycle via hook | ✅ | Orchestrator may offer diff mode later (superset) |
| Panels | Basic panel status parity test | N/A (legacy baseline) | `tests/test_panel_status_parity.py` | ✅ | One-cycle structural parity (indices + meta clusters) validated |
| Panels | Event-driven diffs | N/A | Planned diff emitter | ⏳ | Superset; not a parity blocker |
| Health | Component health gauge emission | Limited / ad-hoc | Health monitor integration | ✅ | Orchestrator richer; legacy minimal |
| Config | Strict schema enforcement | Partial / permissive | Loader + schema v2 | ✅ | Orchestrator path validates earlier |
| Config | Deprecated key detection | Limited | Metrics + rejection | ✅ | Superset (acceptable divergence) |
| Security | HTTP basic auth for catalog/snapshots | N/A | Implemented | ✅ | Superset |
| Deprecation | One-time legacy warning | Implemented | N/A (orchestrator default) | ✅ | Gating now raises unless enabled |
| Removal Prep | Parity harness golden snapshots | `parity_harness` legacy path | `parity_harness` orchestrator path | ✅ | Golden regeneration env flows documented |

## Outstanding Items Before Legacy Removal
1. Multi-signal adaptive controller (not required for removal, but note orchestrator-only enhancement incoming).
2. Event-driven panel diffs (orchestrator superset; ensure docs frame as enhancement not blocker).

## Removal Criteria (R+1 Target)
- All rows above at status ✅ or acceptable superset (documented).
- No CI/tests rely implicitly on `collection_loop` (all explicit uses gated with flag in tests only where needed).
- Two consecutive full green test runs (pre-removal) completed (legacy loop now removed).
- `DEPRECATIONS.md` updated to "REMOVAL SCHEDULED (pending release tag)".
- Announcement note inserted into `CHANGELOG.md` / release notes.

## Verification Strategy
- Parity harness regression test executes orchestrator + (flag-enabled) legacy in isolation; compares normalized JSON snapshots (prices, option counts, expiry codes, metrics summary subset).
- On any drift: open issue with category [parity] referencing matrix row.

## Change Log
2025-09-26: Initial matrix created post gating of legacy loop.
2025-09-27: Updated max cycles parity row to ✅ (alias `G6_MAX_CYCLES` supported in orchestrator); removed alias decision from outstanding items.
2025-09-27: Added panel status structural parity test (`tests/test_panel_status_parity.py`) covering indices presence & core meta clusters.
