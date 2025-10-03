# G6 Development Guidelines & Future Enhancements

> Audience: Contributors & maintainers. This document catalogs architectural weak links, development precautions, and prioritized enhancement recommendations.

---
## 1. Architectural Weak Links (Current)
| Area | Weakness | Risk | Notes |
|------|----------|------|-------|
| Live Panel State | Incomplete per-index wiring (NA fields) | Operator confusion / reduced at-a-glance insight | Implement structured state export post-cycle |
| Memory Pressure Tier 3 | Unimplemented dynamic strike/expiry contraction | Potential OOM if upstream symbol set expands | Design scaling heuristics tied to pressure progression |
| Data Retention | No built-in pruning | Disk exhaustion over long horizon | Add retention policy engine or external cron recipe |
| Provider Abstraction | Single provider assumption | Vendor lock-in / failover gap | Introduce provider registry & fallback sequencing |
| Web Dashboard Code | Deprecated remnants | Codebase noise & user confusion | Plan removal or isolation into legacy branch |
| IV Solver Bounds | Static bounds & iterations | Divergence for exotic market regimes | Adaptive bounds based on underlying realized vol |
| Error Taxonomy | Ad-hoc error_type labels | Inconsistent metrics correlation | Central enum & mapping layer |
| Config Validation Depth | Basic type/shape checks | Runtime surprises on new nested sections | Strengthen schema (jsonschema or pydantic) |
| Logging Sanitization | Partial ASCII fallback | Possible leakage of structured sensitive tokens | Add pattern-based redaction layer |
| Parallelism Strategy | Potential underutilization / overfetch | Reduced throughput in high-latency scenarios | Evaluate async or batched parallel fetch |
| Retry Logic | Generic backoff | Suboptimal under burst provider rate limits | Implement jitter + rate-limit aware delays |

---
## 2. Development Precautions
1. Backwards Compatibility: Never repurpose existing CSV column names; append new ones.
2. Metrics Stability: Avoid renaming existing Prometheus metrics; add new labels only if cardinality impact reviewed.
3. Cardinality Control: Gate any new per-option metric behind memory pressure awareness; test with large strike universes.
4. Config Evolution: Update `validator.py` and the canonical `README.md` (Configuration section) together; document defaults explicitly.
5. Error Handling: Wrap provider calls with resilience utilities; never allow an exception in one index to abort the whole cycle unless integrity-critical.
6. Timezone Consistency: Use UTC internally where possible; if local exchange time is needed, centralize conversion.
7. Performance Profiling: Add lightweight timing gauges before introducing heavier analytics (e.g., surfaces, spread builders).
8. Dependency Hygiene: Pin versions for critical numeric libs to avoid drift-induced calculation divergence.
9. Testing Scope: For numerical routines (IV, Greeks), add regression fixtures; verify solver iteration counts remain within historical norms.
10. Logging Discipline: Prefer structured context summarization rather than dumping large JSON blocks per cycle.
11. Security: Keep token paths / secrets out of repo; ensure new scripts respect `.gitignore` patterns.
12. Windows Compatibility: Preserve ASCII fallback logic; test ANSI color toggles; avoid hardcoding POSIX-only paths.
13. Resource Cleanup: Any new thread or async loop must have graceful shutdown integration.
14. Time Utilities: Prefer `utc_now()` / `get_ist_now()` from `src.utils.timeutils` over direct `datetime.now()`; never use `datetime.utcnow()`.

### 2.1 Pre-commit Hooks
The repo ships with a `.pre-commit-config.yaml` enforcing:
- No `datetime.utcnow()` (use `datetime.now(timezone.utc)` or `utc_now()`).
- No naive `datetime.now()` without timezone.
- Basic hygiene (trailing whitespace, EOF newline, YAML validity, flake8).

Enable locally:
```
pip install pre-commit
pre-commit install
```
Run against entire codebase (one-time full sweep):
```
pre-commit run --all-files
```
If a hook fails, fix the code and re-stage. Hooks are lightweight to catch issues early.

---
## 3. Coding Standards (Lightweight)
- Language: Python 3.11+; prefer type hints (PEP 484) in new/modified modules.
- Style: Black-compatible formatting; meaningful docstrings for public functions.
- Imports: Group standard lib / third-party / local; avoid wildcard imports.
- Error Messages: Action-oriented ("Retrying fetch..."), include index & expiry context.
- Logging Levels: DEBUG (verbose internals), INFO (cycle summaries), WARNING (recoverable anomalies), ERROR (data loss risk), CRITICAL (process viability).

---
## 4. Tests & Quality Gates
Minimum additions for new feature:
| Category | Requirement |
|----------|------------|
| Unit Tests | Core logic & edge cases covered |
| Regression | Numerical outputs stable (IV/Greeks) |
| Performance (optional) | Measurement for latency-sensitive additions |
| Lint | Run ruff/flake8 (add CI) |

Suggested future: GitHub Actions workflow executing: install deps → run pytest (with `--maxfail=1`) → export coverage badge.

---
## 5. Future Enhancements (Detailed)
| Category | Enhancement | Description | Benefit |
|----------|------------|-------------|---------|
| Observability | Per-index live panel state export | Structured state bridging to panel | Faster operator feedback |
| Storage | Retention & Compaction Service | Age-based rollups & archival | Disk sustainability |
| Analytics | Vol Surface Builder | Interpolate arbitrage-free surface | Advanced modeling |
| Analytics | Spread & Strategy Simulator | Evaluate multi-leg strategy Greeks & P/L | User value add |
| Reliability | Multi-Provider Fallback | Retry alt provider on failures | Higher availability |
| Resilience | Adaptive IV Solver Bounds | Dynamic bounds from realized vol stats | Fewer solver failures |
| Config | Rich Schema Validation | jsonschema or pydantic based enforcement | Earlier failure detection |
| Security | Log Redaction Filters | Mask token-like patterns | Lower leakage risk |
| Performance | Async Collection Layer | Non-blocking I/O for API calls | Lower cycle duration |
| Alerts | Packaged Alert Rules | Deployable default alert set | Faster production readiness |
| Compression | Automatic Old CSV Compression | ZIP or parquet conversion | Reduce footprint |
| CLI | Subcommand Interface | `g6 collect`, `g6 analyze`, etc. | More discoverable UX |
| Docs | Architecture Diagrams (mermaid) | Auto-generated diagrams in docs | Clarity for new devs |
| Metrics | Derived Volatility Drift | Track shift from previous cycle | Surface instability |
| Memory | Tier 3 Strike Depth Scaling | Drop far OTM dynamically | Prevent OOM |
| Testing | Synthetic Market Generator | Deterministic chains for tests | Stable reproducibility |

---
## 6. Contribution Workflow (Proposed)
1. Branch naming: `feat/`, `fix/`, `doc/`, `ops/` prefixes.
2. Open PR with concise summary & risk assessment.
3. Ensure tests green; add/update docs.
4. Tag reviewers with domain expertise (analytics / storage / infra).
5. Squash merge preserving meaningful commit message.

---
## 7. Release & Versioning
Adopt semantic versioning (semver):
- MAJOR: Backwards-incompatible CSV/metric changes
- MINOR: Additive features, new metrics, new columns
- PATCH: Bug fixes, performance improvements

Tag example: `v0.2.0` after adding live panel per-index wiring.

---
## 8. Risk Mitigation Strategies
| Risk | Mitigation |
|------|-----------|
| Provider API outage | Implement multi-provider fallback & exponential backoff |
| Disk saturation | Automate retention + monitoring of disk usage metrics |
| Memory leak in solver | Periodic memory sampling + pressure-based restart triggers |
| Incorrect Greeks due to model drift | Add sanity bounds; cross-validate vs external library tests |
| High cardinality explosion | Guard new labels; dynamic disabling under pressure |

---
## 9. Decommission / Cleanup Plan
If future architecture replaces current collectors:
1. Freeze current branch (tag `legacy-collector`)
2. Migrate metrics to compatibility layer
3. Provide migration script for CSV -> new format (if needed)
4. Remove deprecated code after one minor version cycle

---
## 10. Open Questions (To Decide)
| Topic | Question |
|-------|----------|
| Persistence | Move to Parquet for columnar efficiency? |
| Analytics | Introduce SABR / local vol modeling? |
| Scaling | Horizontal sharding by index vs vertical scaling? |
| Security | Vault integration for tokens? |
| CLI | Should we create a `g6` console entry point? |

---
## 11. Tracking & Documentation Discipline
- Every new metric: update `docs/METRICS.md`.
- Every new toggle: update `docs/CONFIG_FEATURE_TOGGLES.md` + `README.md` (Feature Toggles subsection).
- Every schema change: increment MIGRATION.md log.

### 11.1 Metrics Group Pruning (Dry-Run Support)
### 11.2 Build Info Metric Extraction
`g6_build_info` registration logic has been modularized into `src/metrics/build_info.py` (`register_build_info`). The facade import (`from src.metrics import register_build_info`) is unchanged; internal relocation reduces monolith size and isolates side-effectful idempotent gauge relabeling.

The dynamic metrics group pruning API now supports a safe preview mode.

Usage:
```
from src.metrics import prune_metrics_groups
preview = prune_metrics_groups(reload_filters=True, dry_run=True)
# -> returns summary WITHOUT deleting any grouped metrics
applied = prune_metrics_groups(reload_filters=False)  # perform actual pruning
# Convenience wrapper (equivalent to dry_run=True):
from src.metrics import preview_prune_metrics_groups
preview2 = preview_prune_metrics_groups(reload_filters=True)
```
Returned summary keys:
- `before_count` / `after_count` / `removed`
- `removed_attrs` (capped at 50)
- `enabled_spec` (whether an allow-list is active)
- `disabled_count`
- `dry_run` (True when simulation only)

Operational Guidance:
1. Use `dry_run=True` in diagnostics (CI, support scripts) to understand the impact of current `G6_ENABLE_METRIC_GROUPS` / `G6_DISABLE_METRIC_GROUPS` filters before applying.
2. Follow with `dry_run=False` (default) once the preview looks correct.
3. Prefer `reload_filters=True` for the first call after modifying environment variables; subsequent chained operations can set `reload_filters=False` to avoid redundant parsing.
4. Dry-run does not mutate internal group mapping state; any attribute presence checks after preview will still see original metrics.
5. Structured logs:
	- Preview: `metrics.prune_groups.preview` (fields: dry_run, before_count, prospective_removed, removed_attrs_sample, enabled_spec, disabled_count)
	- Applied: `metrics.prune_groups.applied` (fields: dry_run, before_count, after_count, removed, removed_attrs_sample, enabled_spec, disabled_count)

No new environment variables were introduced; dry-run is purely a call-site flag and backward compatible.

### 11.3 Introspection & Init Trace Dump Extraction
Environment-driven JSON dump logic for metrics introspection (`G6_METRICS_INTROSPECTION_DUMP`) and initialization trace (`G6_METRICS_INIT_TRACE_DUMP`) moved from the monolithic `metrics.py` into `src/metrics/introspection_dump.py`.

Benefits:
- Removes duplicated inline blocks (historically present twice due to prior merges).
- Centralizes flag normalization ("1", "true" -> stdout) and best-effort error handling.
- Keeps `metrics.py` focused on registry orchestration.

Public surface change: none (dumps still triggered automatically during init if flags set). Optional helper `run_post_init_dumps(registry)` exposed for advanced/manual invocation.

Structured Logs:
Two machine-parseable log events were added:
* `metrics.introspection.dump` (fields: `event`, `metric_count`, `groups_present`, `output`)
* `metrics.init_trace.dump` (fields: `event`, `total_steps`, `total_time`, `output`)
These complement the human-readable pretty JSON logs and enable automation to consume summary metadata without parsing full payloads or file output.

### 11.4 Legacy Registration Shim Extraction
The compatibility `_register` helper (supports legacy builders calling `metrics._register`) was extracted into `src/metrics/registration_compat.py` as `legacy_register`. The method on `MetricsRegistry` now delegates.

Rationale:
- Isolates legacy-only code, easing future deprecation.
- Enables instrumentation (e.g., counters) without touching core registry logic.

### 11.5 Pruning Facade Modularization
`prune_metrics_groups` and `preview_prune_metrics_groups` moved to `src/metrics/pruning.py` with backward-compatible delegators left in `metrics.py`. Tests continue to import through the original namespace.

Advantages:
- Clear separation between operational helpers and the registry implementation.
- Paves path for lighter-weight automation scripts importing only pruning helpers.

### 11.6 Follow-Up Opportunities
1. Structured logging for introspection / init trace dumps (parallel to prune preview/applied) for automated capture.
2. Instrument `legacy_register` usage (counter) to measure remaining dependency before deprecation.
3. Consider lazy construction of introspection inventory (on first access) if startup time becomes critical.
4. Evaluate consolidating duplicate "Initialized X metrics" logs introduced historically—now simplified after extractions.
5. Potential environment toggle to suppress automatic dumps entirely while still allowing explicit programmatic invocation.

### 11.7 Auto Dump Suppression Flag
Added environment variable `G6_METRICS_SUPPRESS_AUTO_DUMPS` (values: 1/true/yes/on) to prevent automatic execution of introspection and init trace dumps during metrics initialization even if `G6_METRICS_INTROSPECTION_DUMP` or `G6_METRICS_INIT_TRACE_DUMP` are set.

Behavior:
* When suppression flag is truthy, no dump I/O occurs and a structured log `metrics.dumps.suppressed` is emitted with field `reason=G6_METRICS_SUPPRESS_AUTO_DUMPS`.
* Manual invocation via `run_post_init_dumps(registry)` still performs dumps (call sites can decide to bypass suppression if desired).
* Use case: noisy test environments or CI pipelines where dump flags are globally enabled but a subset of jobs wants leaner logs.

Testing: `tests/test_metrics_dump_suppression.py` asserts suppression prevents the pretty JSON markers and emits the structured suppression event.

### 11.8 Lazy Introspection Inventory
The introspection inventory (`_metrics_introspection`) is now built lazily by default to reduce initialization overhead.

New Environment Flag: `G6_METRICS_EAGER_INTROSPECTION` (1/true/yes/on) forces eager construction during registry initialization (previous always-eager behavior). The existing dump flag `G6_METRICS_INTROSPECTION_DUMP` implicitly forces eager build so dump output remains immediate and complete.

Behavior Summary:
- Default: `_metrics_introspection` is set to `None` sentinel until first access via `get_metrics_introspection()` or an introspection dump routine.
- On first access, inventory is built, cached, and structured log `metrics.introspection.lazy_built` emitted with `metric_count`.
- Dump helper `maybe_dump_introspection` triggers build if sentinel is present, preserving previous expectation that a dump always contains full inventory.

Tests: `tests/test_metrics_lazy_introspection.py` validates lazy default, eager flag, and dump flag forcing eager path.

### 11.9 Deprecation Policy & Legacy Surfaces
The metrics subsystem now emits explicit `DeprecationWarning`s for legacy usage patterns to guide migration.

Current Deprecations:
- Direct import `src.metrics.metrics` (use facade `from src.metrics import ...`).
- Legacy registration shim (`MetricsRegistry._register` / `legacy_register`). Replace with declarative spec registration or existing public helpers.

Warnings:
- Emitted once per process (unless Python warning filters altered).
- Suppressed when environment variable `G6_SUPPRESS_LEGACY_WARNINGS` is truthy (`1,true,yes,on`).

Structured Events (still emitted even if warnings suppressed):
- `metrics.legacy_register.used` (shim invocation count by metric name).

Removal Timeline (tentative):
- Warning phase: current development cycle.
- Hard removal: earliest two minor versions after initial warning (update CHANGELOG with exact version once scheduled).

Tests: `tests/test_metrics_deprecations.py` verifies warning presence and suppression behavior.

---
## 12. Documentation Debt Register
| Area | Gap | Planned Fix |
|------|-----|-------------|
| Live panel | Lacks per-index data mapping | After state export implementation |
| Memory pressure | No diagram of tier transitions | Add mermaid state diagram |
| Solver | Missing iterative convergence explanation | Add section in analytics doc |

---
## 13. Exit Criteria for v1.0.0
- Full live panel data parity with metrics
- Automated retention & compression
- Multi-provider fallback live
- CI with coverage & lint
- Alert rule pack shipped
- Comprehensive operator & developer docs (this set) stable

---
## 14. Appendix: Decision Log Template
Maintain a `DECISIONS.md` with entries:
```
Date | Area | Decision | Alternatives | Rationale | Impact
```

---
End of guidelines.

---
## 15. Dashboard & Panels Typing Conventions (Wave 3)

Goal: Eliminate ad-hoc `Dict[str, Any]` in the web dashboard, panels pipeline, and metrics augmentation logic. Provide stable, discoverable shapes for UI / panel JSON and future refactors.

### 15.1 Core TypedDicts (see `src/types/dashboard_types.py`)
| Name | Purpose | Key Fields |
|------|---------|-----------|
| `StreamRow` | One rolling per-index line in indices stream | `index`, `legs`, `succ`, `status`, `status_reason`, `err` |
| `FooterSummary` | Aggregated footer across stream rows | `total_legs`, `overall_success`, `indices` |
| `CsvStorage` / `InfluxStorage` / `BackupStorage` | Per-sink metrics snapshot (partial / optional keys) | sink-specific counters |
| `StorageSnapshot` | Composite of the three sink dicts | `csv`, `influx`, `backup` |
| `ErrorEvent` | Recent error increment for panel display | `index`, `error_type`, `delta`, `ago`, `ts` |
| `HistoryErrors` / `HistoryStorage` | Internal history entry shards | `errors` or `storage` |
| `HistoryEntry` | Union of history shards | discriminated by key presence |
| `RollState` | Rolling per-index accumulation | counters + last error metadata |

### 15.2 Protocols
| Protocol | Methods | Usage |
|----------|---------|-------|
| `UnifiedSourceProtocol` | `get_runtime_status()`, `get_indices_data()`, `get_source_status()` | FastAPI endpoints (`app.py`) guard optional unified source import |
| `OutputRouterProtocol` | `begin_panels_txn()`, `panel_update()`, `panel_append()` | Transactional panel publishing via PanelsWriter (legacy panel_updater removed) |
| `PanelsTransaction` | Context manager interface | Returned by `begin_panels_txn()` | 

Rationale: Protocols maintain runtime flexibility (optional imports, duck-typed adapters) while giving static guarantees for call sites.

### 15.3 Implementation Guidelines
1. Import shapes from `src.types.dashboard_types` instead of redefining inline.
2. When evolving panel JSON, extend the relevant TypedDict (add optional keys) rather than returning raw dicts.
3. Prefer narrow local variables (e.g., `rows: list[StreamRow]`) to surface type errors early.
4. History union (`HistoryEntry`) is currently a simple key-presence union; if shape proliferation occurs, convert to a discriminated union (`kind: Literal['errors','storage']`).
5. Avoid `# type: ignore` for assignment—cast or refine the variable shape instead.
6. Guard optional imports (unified source, output router) and return `None` instead of raising; endpoints should test for `None` and respond `503`.
7. Panel transaction publishing: always wrap in `begin_panels_txn()` when available to minimize inconsistent multi-file states.
8. Sorting / numeric operations on TypedDict values should defensively handle `None` and unexpected types; keep fallbacks explicit.
9. New panels should define a dedicated TypedDict for their payload root to avoid reintroducing `Any`.
10. If a TypedDict starts accumulating many optional unrelated clusters, consider splitting into multiple smaller domain-focused TypedDicts.

---
## 16. Minimal Metrics Post-Init Recovery (2025-10)

The metrics initialization refactor removed broad late "recovery" blocks in favor of deterministic early registration. A very small number of metrics still require a safety net due to optional subsystems or group gating:

| Metric | Condition | Reason for Late Fallback |
|--------|-----------|--------------------------|
| `g6_panel_diff_truncated_total` | `panel_diff` group enabled but spec/group path skipped | Ensures truncation events observable even if grouped spec skipped by predicate edge case |
| `g6_vol_surface_quality_score` | `analytics_vol_surface` group allowed | Provides analytics quality signal; avoid registration when analytics disabled |
| `g6_events_last_full_unixtime` | Event bus not yet lazily registered | Some tests read gauge before any event publish triggers bus metric init |

Implementation lives in `src/metrics/recovery.py` (`post_init_recovery`). Principles:
1. Idempotent and narrow scope.
2. Honors `G6_METRICS_STRICT_EXCEPTIONS` (re-raises unexpected errors in strict mode).
3. Prefer fixing ordering/root causes before adding anything new here.

If you believe another metric needs late recovery, first ask: "Can I move its primary registration earlier instead?" Only add to the helper when the answer is no and a test/operator invariant depends on its presence.

### 15.4 Migration Pattern (Applied in Wave 3)
Step | Action | Example
-----|--------|--------
1 | Centralize shapes | Added `dashboard_types.py`
2 | Refactor data producer | `metrics_cache.py` now emits `List[StreamRow]`, `StorageSnapshot`, `List[ErrorEvent]`
3 | Introduce protocols | `_unified` and panel router now typed
4 | Remove legacy ignores | Eliminated `# type: ignore[assignment]` after shaping
5 | Document & enforce | This section + future lint rule candidate

### 15.5 Future Typing Enhancements (Wave 4 Candidates)
- Discriminated union for history entries (`{'kind':'errors', ...}`) to remove structural ambiguity.
- Typed panel payload root objects: e.g., `IndicesStreamPanel`, `StoragePanel` to formalize file shapes on disk.
- Protocol for error handler (`ErrorHandlerProtocol`) to decouple direct import in UI layer.
- Convert ad-hoc dict returns in endpoints to Pydantic models (still lightweight but self-validating).
- Add mypy plugin configuration for stricter TypedDict totality checks in panel modules only.

### 15.6 Anti-Patterns to Avoid
| Anti-Pattern | Replacement |
|--------------|------------|
| Reintroducing `Dict[str, Any]` for panel rows | Use / extend `StreamRow` |
| Blind `isinstance(dict)` before key access | Depend on known TypedDict + optional `get()` for backward compat |
| Swallowing all exceptions without handler | Route via `get_error_handler()` with category/severity |
| Extending union via unchecked `dict` insertion into history | Define new TypedDict & update union |

### 15.7 Quick Reference Snippet
```
from src.types.dashboard_types import StreamRow

row: StreamRow = {
	'time': ts_str,
	'index': idx,
	'legs': cycle_legs,
	'legs_avg': avg or None,
	'legs_cum': cumulative or None,
	'succ': success_pct,
	'succ_avg': success_avg,
	'succ_life': lifetime_pct,
	'cycle_attempts': attempts,
	'err': recent_err or '',
	'status': status,
	'status_reason': reason,
}
```

---

## 17. Metrics Initialization Trace (2025-10)

The metrics module supports an optional lightweight instrumentation mode to help diagnose
ordering issues, slow module imports, or unexpected gating outcomes during startup.

Enable by setting the environment variable:

```
G6_METRICS_INIT_TRACE=1
```

When enabled, `MetricsRegistry.__init__` records a per-step entry in the in‑memory list
`_init_trace` (attribute on the registry instance). No I/O or logging is performed unless
you explicitly introspect and emit it. This keeps overhead negligible for normal runs.

### 17.1 Data Shape
Each element of `_init_trace` is a dict with at least:

| Key | Type | Meaning |
|-----|------|---------|
| `step` | `str` | Logical initialization phase label (e.g. `group_gating`, `spec_registration`, `api_metrics`) |
| `ok` | `bool` | True if the step completed without raising an exception (internal exceptions are caught) |
| `dt` | `float` | Elapsed wall time in seconds (microsecond precision ~1e-6) |
| `count` | `int` (optional) | Step-specific count (e.g. number of spec metrics registered) |
| `groups` | `int` (optional) | Number of controlled groups detected during gating |
| `error` | `str` (optional) | Stringified exception when `ok` is False |

Future keys may be appended; consumers should ignore unknown keys.

### 17.2 Typical Step Labels
Order is deterministic when successful:
1. `group_gating` – applies enable/disable filters and installs predicates.
2. `spec_registration` – registers declarative spec + grouped spec metrics.
3. `index_aggregate` – early creation of `metric_group_state` (and related index aggregates).
4. `perf_metrics` – performance category initialization.
5. `api_metrics` – API call metric registration (with early fallback if needed).
6. (Additional category steps...) – storage, cache, memory, ATM, Greeks, group_registry.
7. Pruning + spec minimum + group state population (not all have separate labels yet).

Not every micro-step is traced; only coarse phases with meaningful latency or failure surface area.

### 17.3 Access & Usage
```
from src.metrics import get_metrics
reg = get_metrics()
trace = getattr(reg, '_init_trace', [])
for row in trace:
	print(row)
```

Recommended tooling: if you need structured export, derive a JSON blob in tests or a
diagnostic CLI rather than expanding core init to log by default.

### 17.4 Overhead & Safety
- Disabled by default (zero list allocations except empty list creation).
- Step timing uses a single `time.time()` call at start/end – low overhead.
- Exceptions inside a step are caught; `error` field is populated, preserving previous resilient behavior.
- Trace is intentionally NOT automatically cleared; repeated reinitializations in the same process (discouraged) will append.

### 17.5 Future Enhancements (If Needed)
- Optional env (`G6_METRICS_INIT_TRACE_DUMP=stdout|<path>`) to dump at completion (deferred until a concrete need arises).
- Add explicit labels for pruning and recovery phases if they become bottleneck suspects.
- Expose a public accessor `get_init_trace()` once stabilized; for now treated as experimental internal.

---
