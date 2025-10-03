# Metrics Modularization Migration Guide

This guide helps transition from direct imports of the monolithic `src.metrics.metrics` module to the new facade-based API while retaining full backward compatibility.

## 1. Rationale
The historical metrics module accumulated heterogeneous responsibilities (registry lifecycle, group gating, server bootstrap, metadata export). Modularization improves:
* Import weight (faster startup in tests / tooling)
* Targeted unit testing of group & metadata logic
* Backward compatibility during phased extraction
* Clarity of public vs internal surfaces

## 2. Facade Imports (Preferred)
```python
from src.metrics import (
    MetricsRegistry,
    setup_metrics_server,
    get_metrics_singleton,
    get_metrics,
    register_build_info,
    get_metrics_metadata,
    isolated_metrics_registry,
)
```
All names above are re-exported; legacy deep imports continue to function for at least one full release window after completion of the modularization phases.

## 3. Mapping Old → New
| Old Import | Preferred Replacement | Notes |
|------------|-----------------------|-------|
| `from src.metrics.metrics import setup_metrics_server` | `from src.metrics import setup_metrics_server` | Idempotent; returns existing server if already started |
| `from src.metrics.metrics import get_metrics` | `from src.metrics import get_metrics` | Alias retained (returns singleton registry) |
| `from src.metrics.metrics import get_metrics_singleton` | `from src.metrics import get_metrics_singleton` | Same behavior |
| `from src.metrics.metrics import register_build_info` | `from src.metrics import register_build_info` | Now accepts `git_commit` & `config_hash` |
| `from src.metrics.metrics import MetricsRegistry` | `from src.metrics import MetricsRegistry` | Class definition unchanged |
| `import src.metrics.metrics as m` | `from src import metrics as m` OR targeted facade import | Avoid broad module import when only a few symbols used |

## 4. Build Info Metric
`register_build_info(version=..., git_commit=..., config_hash=...)` registers or updates a single `g6_build_info` gauge line. Environment fallbacks:
* `G6_BUILD_VERSION`
* `G6_BUILD_COMMIT`
* `G6_BUILD_TIME`

Re-invocation updates labels without duplicate samples.

## 5. Group Gating & Metadata
Group enable/disable variables:
* `G6_ENABLE_METRIC_GROUPS` (comma whitelist)
* `G6_DISABLE_METRIC_GROUPS` (blacklist applied after whitelist)

`get_metrics_metadata()` (facade alias) triggers `reload_group_filters` before summarizing metrics & group membership and performs synthetic supplementation for representative groups when no explicit whitelist is set.

## 6. Testing Patterns
Use `isolated_metrics_registry()` context manager for unit tests that need a clean registry without mutating global singleton state:
```python
from src.metrics import isolated_metrics_registry

with isolated_metrics_registry() as reg:
    reg.options_processed_total.inc()
```

To assert facade ↔ legacy identity (example provided in new test):
```python
from src.metrics import get_metrics as facade_get
from src.metrics.metrics import get_metrics as legacy_get
assert facade_get() is legacy_get()
```

## 7. Incremental Adoption Strategy
1. Update library / orchestrator code to facade imports (non-breaking).
2. Update test modules en masse using search-and-replace.
3. Leave tooling or ad-hoc scripts for last if they rely on dynamic import patterns.
4. After one release with both paths: optionally introduce a warning on direct `src.metrics.metrics` import (not yet enabled).

## 8. FAQ
**Q:** Do I need to change anything if I only read metrics via HTTP?  
**A:** No. The exporter endpoint and metric names are unchanged.

**Q:** Will `get_metrics()` ever be removed?  
**A:** Not in the immediate term. A deprecation notice will precede any removal with at least one release window.

**Q:** Why keep `get_metrics_singleton` if `get_metrics` exists?  
**A:** Provides explicit semantic clarity in call sites that expect the singleton rather than a new registry (historical consistency).

## 9. Future Roadmap (Indicative)
* Further extraction of domain-specific metric families (risk aggregation, panels diff) into separate modules.
* Optional facade-only enforcement mode (import warning) once adoption threshold reached.
* Lean test harness that imports only metadata/group modules when full registry not required.

---
For questions or edge cases, annotate the CHANGELOG entry or open a tracking issue.

## 10. Completion Status (Post-Migration)
Bulk call‑site migration to facade imports is COMPLETE.

Summary:
* All application and test modules now use `from src.metrics import ...` (facade) with the exception of intentionally retained legacy parity tests.
* Dynamic imports updated (`importlib.import_module('src.metrics')`) replacing `src.metrics.metrics` occurrences.
* Audit tooling (`scripts/audit_metrics_usage.py`) flags any reintroduced deep imports.
* Legacy module `src.metrics.metrics` remains as a compatibility shim for a minimum of one full release window (R+1). After that window a runtime warning may be enabled before any hard deprecation.
* Environment variable inventory expanded; newly surfaced adaptive alert & volatility surface toggle variables are being integrated into `env_dict.md` (see temporary appendix `docs/env_vars_adaptive_append.md`).

Action Items Before Enforcing Warnings:
1. Finalize documentation of newly detected `G6_` environment variables (adaptive alert severity & color controls, vol surface per‑expiry toggle, etc.).
2. Consolidate duplicate env var doc entries (`G6_REFACTOR_DEBUG`, `G6_SUMMARY_DOSSIER_PATH`).
3. (Optional) Add import warning guard inside `src/metrics/metrics.py` wrapped by an env toggle (e.g., `G6_WARN_LEGACY_METRICS_IMPORT=1`).

Safe Removal Criteria (Future):
* Zero occurrences of `src.metrics.metrics` in non-test code for 2 consecutive releases.
* CI audit script passes with no warnings for at least 30 days.
* All env var docs updated & CHANGELOG contains formal deprecation notice.

If you encounter a missing facade export, add it to `src/metrics/__init__.py` and update this guide.
