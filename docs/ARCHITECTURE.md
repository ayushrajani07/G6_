# G6 Architecture (Scaffold)

> Status: Draft (Phase 1). This document captures the current high-level architecture to create a stable reference point before deeper refactors.

## 1. Runtime Overview

The system is an event + cycle oriented orchestration loop that ingests market/provider data, enriches + scores state, and emits:
- Console / Panel summaries (rich + plain modes)
- Prometheus metrics
- Persistent artifacts (snapshots, analytics, optional Influx)
- Alert streams / status files consumed by bridges

Primary entry scripts:
- `scripts/run_orchestrator_loop.py` – canonical loop runner (cycles, intervals, max cycles, early exit)
- `scripts/g6_run.py` – legacy / convenience launcher
- `scripts/status_simulator.py` – synthetic status generation (dev/testing)
- `scripts/summary_view.py` – live terminal dashboard & panels mode

## 2. Core Modules

### 2.1 Orchestrator
Responsibility: bootstrap components, maintain cycle cadence, orchestrate providers, adaptive controllers, analytics, and emission.
Key parts:
- `bootstrap_runtime()` (initialization: config, metrics server, env wiring)
- `run_loop()` & `run_cycle()` – deterministic iteration boundary with safety checks (max cycles, market close conditions)
- `RuntimeContext` – structured container for shared state (providers, config, timing, counters, feature flags)

Design Goals:
- Deterministic & inspectable loop
- Progressive shutdown (market close, keyboard interrupt, failure containment)
- Feature isolation via env flags (moving toward explicit config)

### 2.2 Providers & Data Sources
Providers abstract upstream data (e.g., market data, analytics). Modes selected by env (e.g., `G6_PROVIDERS_*`). Simulation layer reproduces provider shape for deterministic tests.

### 2.3 Adaptive Subsystem
Adaptive alert/severity + scaling & strike logic tuned by dense family of `G6_ADAPTIVE_*` env vars. Current issues:
- Parameter sprawl
- Implicit coupling to summary rendering & metrics
Planned: group parameters into typed config objects; add validation and layered defaults.

### 2.4 Metrics Layer
File: `src/metrics/metrics.py` (monolithic). Handles:
- Registration of Prometheus metrics
- Group gating / dynamic enabling
- Cardinality protection & adaptive disabling
Constraints / Risks:
- Single large module (difficult to test in isolation)
- Implicit global state (registry)
Refactor Plan (Phase 2+):
1. Extract metric group descriptors
2. Factory for registering groups
3. Pure functions for value derivation -> easier unit tests
4. Typed wrapper around Prometheus constructs

### 2.5 Summary / Panels Rendering
Modes:
- Plain terminal
- Rich adaptive panel view (with group toggles & severity diffusion)
- Panels bridge writing structured panel fragments to `data/panels`
Key env toggles: `G6_SUMMARY_*`, `G6_PANELS_*`
Pain Points:
- Mixed concerns (rendering, state transforms, dedupe, history persistence)
Roadmap: separate model layer (deriving canonical summary model) from UI formatting + transport.

### 2.6 Storage & Snapshots
Artifacts:
- Auto snapshots (benchmarks, parity snapshots)
- Optional Influx pipeline (gated by `G6_STORAGE_INFLUX_*`)
- CSV / analytics dumps
Observations: multiple partially overlapping dump formats; unify under a versioned exporter abstraction.

### 2.7 Configuration & Environment Governance
Current State:
- Heavy dependence on `os.environ` reads scattered across modules
- Authoritative doc: `docs/env_dict.md`
- Auto inventory: `docs/ENV_VARS_AUTO.md` (script: `scripts/gen_env_inventory.py`)
Planned Evolution:
- Central `Config` object built from: (defaults -> file `_config.json` -> env overrides -> CLI args)
- Validation + dead flag detection
- JSON snapshot of active config for introspection & support tooling

## 3. Cross-Cutting Concerns

### 3.1 Observability
- Prometheus metrics server (port via env)
- Optional structured logging / panel logging sinks (`G6_OUTPUT_SINKS`)
- Trend / anomaly debug toggles

### 3.2 Performance & Safety
- Cycle interval enforcement
- Adaptive disable of high-cardinality metrics
- Benchmarks & anomaly history gating

### 3.3 Feature Flag Taxonomy
Flags fall into categories:
- Behavior modifiers (adaptive severity tuning)
- Output/render gating (summary/panels/theme)
- Experimental / refactor probes (`G6_REFACTOR_DEBUG`, compatibility toggles)
- Provider / storage backends
Need: classification & lifecycle policy (introduce stages: experimental -> active -> deprecated -> removed).

## 4. External Interfaces
- Prometheus scrape endpoint (metrics)
- Generated status JSON files consumed by panels & tests
- Potential future: lightweight HTTP health API (flags exist: `G6_HEALTH_API_*`)

## 5. Known Hotspots (Pre-Refactor)
| Area | Issue | Refactor Direction |
|------|-------|--------------------|
| metrics monolith | Low cohesion | Modular group registry |
| env flag sprawl | Hard to audit | Central config + schema |
| summary renderer | Logic + presentation interwoven | Extract model layer |
| legacy bridge paths | Transitional complexity | Enforce single normalized pipeline |
| adaptive param sets | Implicit coupling | Typed config objects |

## 6. Incremental Refactor Strategy
1. Codify configuration assembly (read once) -> freeze -> inject
2. Introduce metric group descriptors & registration abstraction
3. Build summary model builder (pure) + presentation adapters
4. Deprecate / prune stale env vars identified by inventory
5. Introduce lifecycle tagging for flags (metadata table)

## 7. Extension Points (Future)
- Plugin registry for providers (entrypoints or dynamic import map)
- Derived analytics processors chain (Composable pipelines)
- Theming engine for panels (declarative layout spec)

## 8. Open Questions
- Should runtime store a structured diff of env overrides vs defaults for diagnostics?
- Where to persist config snapshot? (e.g., `data/active_config.json`)
- Formal versioning for emitted snapshot/parity files?

## 9. Next Steps (Phase 1 Scope)
- Finalize this scaffold into stable `ARCHITECTURE.md` (mark sections complete)
- Author `CONFIGURATION.md` with precedence + draft schema
- Extract redundancy catalog
- Add JSON output for env inventory & hook into tests

---
Generated scaffold: refine collaboratively; keep drift low.

## 10. Phase 2 Progress (Inception)

Initial scaffolds added (non-breaking):

| Area | Artifact | Purpose |
|------|----------|---------|
| Metrics modularization | `src/metrics/registry.py` | Future home for registry construction decoupled from monolith |
| Metrics group logic | `src/metrics/groups.py` | Pure helper for enable/disable filtering |
| Metrics package facade | `src/metrics/__init__.py` (expanded) | Stable public surface while refactoring internals |
| Runtime config (light) | `src/config/runtime_config.py` | Typed snapshot for loop + metrics env values |
| Summary model | `src/summary/model.py` | Rendering-agnostic data model for future unified renderer |
| Error handling | `src/utils/error_handling.py` | Central severity + decorator utilities |

Near-term (Phase 2 next steps):
1. Introduce metric group descriptor definitions (`metrics/descriptors.py`).
2. Migrate a small, isolated metric subset (e.g., cache metrics) into new registry path behind feature flag.
3. Add `summary/builder.py` producing `SummarySnapshot` from existing runtime state (pure function).
4. Replace scattered loop env reads with `runtime_config.get_runtime_config()` in orchestrator.
5. Emit `data/active_runtime_config.json` snapshot optionally (diagnostic flag) to validate stability.

Exit Criteria for Phase 2:
- No behavior change (tests green) with new scaffolds present.
- New modules imported in one or two low-risk call sites (confidence build).
- Documentation updated (this section) and cross-linked from `CONFIGURATION.md`.
