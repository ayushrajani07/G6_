# Terminal Dashboard Refactor Plan

Date: 2025-10-03
Status: Phase 0 (Scaffolding)
Owner: TBD

## 1. Current Components (Scope: Terminal Dashboard)

Entry Points:
- `scripts/summary/app.py` (unified terminal app, complex + mixed concerns)
- `scripts/summary_view.py` (deprecated shim; still supplies StatusCache, plain fallback, duplicate helpers)

Core Modules:
- Derivation & helpers: `scripts/summary/derive.py`, `scripts/summary/env.py`
- Data reading / misc: `scripts/summary/data_source.py`, `snapshot_builder.py`, `bridge_detection.py`
- Loop engine: `scripts/summary/unified_loop.py`
- Rendering/layout: `scripts/summary/layout.py`, `scripts/summary/panels/*`
- Plugins: `scripts/summary/plugins/*` (TerminalRenderer, PanelsWriter, SSE ingestion)
- Legacy shim duplication: time formatting & env parsing repeated between `summary_view.py` and `derive.py`

## 2. Simplified Current Flow
1. Read status JSON (raw dict) from `data/runtime_status.json`.
2. Build a lightweight snapshot (`SummarySnapshot`) with sparse derived dict.
3. Invoke plugins (terminal renderer, panels writer, optional SSE).
4. Terminal renderer rebuilds layout panels each cycle relying on raw dict + ad hoc derivation functions.
5. Panels writer synthesizes JSON outputs from raw status.
6. Derivation helpers are repeatedly re-run (no caching/diffing).

## 3. Pain Points / Risks
Category | Issue
---------|------
Coupling | Tight implicit coupling between layout, panel functions, derive utilities.
Duplication | Formatting/time helpers duplicated in multiple modules.
Mutation Semantics | `status` mapping mutable via side-channels; unclear contract.
Performance | Re-import & re-derive every refresh; no diff-driven updates.
Testability | UI + logic intertwined; limited pure-function boundaries.
Error Surfacing | Broad try/except; failures can be silently swallowed.
Extensibility | Adding panels requires manual wiring in two functions (build + refresh).
Plain Mode | Plain fallback inconsistent (debug log only) vs rich layout.
SSE / Panels Mode | Environment-triggered behavior scattered across modules.

## 4. Target Architecture (High-Level)
Layer | Responsibility | Example Module(s)
------|---------------|------------------
Domain Model | Typed snapshot + submodels | `summary/domain.py`
IO Layer | Status / panels file reading w/ error taxonomy | `summary/status_reader.py`
Derivation | Pure transforms from raw -> domain | `summary/derive/*.py`
Engine | Loop scheduling, plugin orchestration | `summary/engine/loop.py` (future)
Plugin API | Stable protocol, immutable snapshot view | `summary/plugins/base.py`
Renderer Adapters | Rich, Plain, PanelsWriter, SSE | `summary/plugins/*.py`
Layout Registry | Declarative panel registration + ordering | `summary/layout/registry.py`
Panels | Pure: Domain -> PanelRenderData | `summary/panels/*.py`
Serialization | Consistent JSON emission, versioned schema | `summary/serialize/*.py`
CLI | Thin parse & launch layer | `summary/cli.py`
Compatibility | Bridge for legacy entrypoint | `summary_view.py` (temporary)

## 5. Domain Snapshot Draft
```python
@dataclass(frozen=True)
class CycleInfo: number: int|None; last_start: float|None; last_duration: float|None; success_rate: float|None
@dataclass(frozen=True)
class AlertsInfo: total: int|None; severities: dict[str,int]
@dataclass(frozen=True)
class ResourceInfo: cpu_pct: float|None; memory_mb: float|None
@dataclass(frozen=True)
class SummaryDomainSnapshot: cycle: CycleInfo; alerts: AlertsInfo; resources: ResourceInfo; indices: list[str]; ts_read: float; raw: dict[str,Any]
```

## 6. Phase Roadmap
Phase | Goals
------|------
0 | Scaffold domain models + status reader + basic test (no behavior change)
1 | Panel registry + renderer decoupling (Rich & Plain share panel data) | adapter keeps old API
2 | Replace unified loop snapshot build with domain builder + immutable snapshot
3 | Diff-based panel refresh + per-panel timing metrics
4 | SSE push integration & reduce polling; finalize plain mode parity
5 | Remove legacy shim & duplicate helpers; consolidate derive & formatting

## 7. Immediate Wins (Phase 0/1)
- Extract CLI arg parsing.
- Add stable domain dataclasses with builder that wraps existing `derive.*` outputs.
- Centralize status read with sane error taxonomy.
- Panel registry abstraction (list of providers returning data + metadata) feeding both Rich and Plain.

## 8. Risk Mitigation
- Keep old path behind `G6_SUMMARY_REWRITE` flag until parity tests pass.
- Add snapshot parity tests comparing derived indices / alert totals old vs new.
- Maintain PanelsWriter contract while internally switching to domain snapshot.

## 9. Metrics & Observability (Future)
- Per-panel render duration + failure count.
- Cycle build vs render breakdown.
- Diff hit ratio (how many panels unchanged).

## 10. Acceptance Criteria for Phase 0
- `scripts/summary/domain.py` provides dataclasses + `build_domain_snapshot(raw: dict, ts_read: float)`.
- `scripts/summary/status_reader.py` exposes `read_status(path) -> StatusReadResult` (with structured errors).
- Unit test validates builder handles empty, minimal, and full-ish mock status dicts.
- No impact to existing loop or renderer yet.

## 11. Next Implementation Steps
1. Add `domain.py`
2. Add `status_reader.py`
3. Add tests
4. Commit & push

## Phase 1 Progress (2025-10-03)
Implemented:
- Panel intermediate types (`panel_types.py`).
- Panel registry with cycle, indices, alerts, resources providers (`panel_registry.py`).
- Plain renderer plugin (`plain_renderer.py`) producing stable text output from domain snapshot + registry.
- Rewrite flag integration (`G6_SUMMARY_REWRITE`) in `scripts/summary/app.py` for:
	- Unified loop: uses `PlainRenderer` when `--no-rich` and flag active.
	- One-shot fallback path: domain snapshot + panel registry instead of legacy `plain_fallback`.
- Tests:
	- `test_panel_registry.py` (structure & error handling).
	- `test_plain_renderer.py` (ordering, missing field resilience).

Next (Phase 2 Targets):
- Replace loop snapshot builder with domain snapshot + derived metrics consolidation.
- Add diff hashing to skip unchanged panels.
- Parity tests between legacy plain fallback and new plain renderer.

Flag Usage:
```
G6_SUMMARY_REWRITE=1 python scripts/summary/app.py --no-rich --cycles 1
```

## Phase 2 Progress (2025-10-03)
Implemented:
- Added `domain` field to `SummarySnapshot` dataclass.
- Unified loop now builds domain snapshot first, then legacy derived map (transitional).
- PanelsWriter prefers domain fields for `indices_count` and `alerts_total`.
- Plain renderer gains diff suppression (hash-based) with env override `G6_SUMMARY_PLAIN_DIFF=0`.
- New tests:
	- `test_unified_loop_domain.py` (domain population & indices count parity).
	- `test_plain_renderer_diff.py` (suppression and disabling).

Notes:
- Frame builder still used for memory/panels_mode; will migrate once those fields move into domain model.
- No changes to existing rich renderer path yet (Phase 3 target).

Next (Phase 3 Targets):
- Integrate diff hashing into rich panels (panel-level invalidation).
- Expose domain snapshot to TerminalRenderer for hybrid rendering.
- Add parity fixture tests: legacy `plain_fallback` vs new plain renderer output lines.
- Begin removing duplicated derive helpers from deprecated `summary_view.py`.

---
(End of Phase 0 planning document)
