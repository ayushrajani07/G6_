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
15. Structured Provider Events: When adding new provider operations, emit a gated structured event using `provider_event(domain, action)` inside `src.broker.kite.provider_events` for consistency; never raise from instrumentation path.

### 2.2 Structured Provider Events (Observability Contract)
The provider facade now supports opt-in structured JSON events for key operations (instruments fetch, quotes/ltp, expiries, options, health):

Enable:
```
export G6_PROVIDER_EVENTS=1        # or set in environment (Windows: $env:G6_PROVIDER_EVENTS='1')
# optional global gate (supersets provider)
export G6_STRUCT_LOG=1
```

Format (example):
```
{"ts": 173... , "event":"provider.kite.quotes.ltp.success", "domain":"quotes", "action":"ltp", "outcome":"success", "dur_ms":12, "provider":"kite", "instruments_requested":1, "returned":1}
```

Failure adds: `error_type`, `error_msg`, `error_class` (taxonomy) and optional `trace` when `G6_PROVIDER_TRACE=1`.

Guidelines:
- Avoid adding large payload arrays; prefer counts (e.g. `returned`, `count`).
- Add only stable scalar fields (int/float/bool/str) via `evt.add_field`; non-serializable objects converted to `repr`.
- Keep domain names lower-case (`instruments`, `quotes`, `expiries`, `options`, `health`).
- Do not rely on event presence in core logic (observability only).

Testing:
- See `tests/test_provider_structured_events.py` for examples capturing logs and asserting event shape.
- For new domains, add a dedicated test with the gate enabled to prevent silent regression.

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

#### 11.9.1 Test Warning Hygiene (2025-10 Cleanup)

### 11.10 Logging & Print Output Policy (2025-10)

Hard Output Whitelisting:
The test/runtime bootstrap (`sitecustomize.py`) now installs a root logging filter and a wrapped `print` to aggressively silence noise. Only the following logger name prefixes are permitted to emit via standard logging handlers:

- `src.collectors.unified_collectors`
- `src.collectors.cycle_context` (added 2025-10 to restore consolidated `PHASE_TIMING` emission after modular silence pass)
- `src.orchestrator.startup_sequence`
- `src.broker.kite_provider`
- `src.collectors.modules.market_gate`
- `src.tools.token_manager`

All other logger traffic is dropped at filter-level (handlers never see the record). This is intentionally non-configurable at runtime to guarantee stable, low-noise test output and operator-facing logs.

Print Gating:
- `print()` calls are suppressed unless originating from:
	* `__main__` (direct script execution)
	* Modules whose `__name__` starts with `scripts.` or `tests.`
	* Modules covered by the logging whitelist prefixes above
	* Heuristic JSON payloads (first arg looks like a JSON object) to avoid breaking machine-readable CLI results
	* Benchmark reporting scripts (`bench_trend.py`, `bench_report.py`) explicitly (path-based allowance)

Bypass Mechanism for Mandatory Output:
- For scripts that must always emit (CI parsers, benchmark utilities), write to `sys.__stdout__` directly instead of `print()` to avoid any future wrapper changes:
	```python
	import sys
	sys.__stdout__.write(json_payload + "\n")
	sys.__stdout__.flush()
	```
- `bench_trend.py` and `bench_report.py` have been updated to follow this pattern.

Design Rationale:
1. Eliminates incidental noise from deep modules (coverage warnings, duplicate metric notices) in standard test and local runs.
2. Encourages structured events / metrics over ad-hoc `print` debugging.
3. Reduces flakiness in output-driven tests relying on precise stdout content.

Migration Guidance:
- If you add a new critical early-phase component whose logs must surface, extend the whitelist in `sitecustomize.py` (avoid wildcard broadening; use the narrowest stable prefix).
- Prefer structured events (see `struct_events.py`) for per-cycle diagnostics; these can be selectively suppressed via `G6_STRUCT_EVENTS_SUPPRESS`.
- Avoid adding general-purpose logging in tight inner loops; rely on aggregated summaries instead.

Anti-Patterns (Rejected):
- Adding ad-hoc environment toggles to re-enable broad logging: increases complexity, undermines deterministic test output.
- Switching to `print()` for noisy modules: print is also gated; use structured events if information is still valuable.

Testing Considerations:
- Tests asserting CLI output should continue to pass because whitelisted or direct `sys.__stdout__` writes are preserved.
- When adding a new CLI: ensure its module path resides under `scripts.` (conventional) so default print allowance applies.

Future Enhancements:
- Potential `G6_LOG_POLICY_DIAGNOSTIC=1` mode to emit a one-time summary of suppressed module logger names for developer introspection.
- Telemetry counter of suppressed log records (sampled) to quantify noise reduction benefits.


As of the October 2025 W4-12 completion:

- All production & test modules import metrics solely via the facade (`from src.metrics import ...`).
- No remaining runtime usages of `src.metrics.metrics` outside the compatibility shim and migration documentation examples.
- Deprecation test coverage retained only where explicitly validating warning suppression behavior (if re-enabled in future). Those tests will be removed once the shim enters hard removal phase.
- New code MUST NOT reintroduce `src.metrics.metrics`; add a review check in code reviews for this pattern.
- Removal timeline updated: deep import shim slated for removal after two additional minor releases unless blockers logged in `METRICS_MIGRATION.md`.

Result: baseline test runs have eliminated prior deep-import deprecation warnings, focusing warning channel on any newly introduced issues.

### 11.10 Environment Flag Parsing Helper

Repeated inline patterns of `os.getenv(NAME,'').lower() in {'1','true','yes','on'}` have been consolidated via `src.utils.env_flags.is_truthy_env`.

Guidelines:
- Prefer `from src.utils.env_flags import is_truthy_env` and call `is_truthy_env('G6_SOME_FLAG')`.
- For flags with default-on semantics, check presence first if behavior differs when unset (see metrics facade handling of summary flags).
- Use the shared `TRUTHY_SET` only if implementing vectorized parsing or advanced logic; avoid redefining local truthy sets.
- When adding new flags, document them in `env_dict.md` and use the helper immediately to avoid style drift.

2025-10 Adoption Wave:
- Test infrastructure (`tests/conftest.py`) migrated – timing guard, sandbox, metrics/output resets, progress & watchdog flags now unified.
- Core collectors (`src/collectors/unified_collectors.py`) refactored: import trace, greek overrides, daily header, data quality enable, alerts compatibility, refactor debug flag.
- Output subsystem (`src/utils/output.py`) migrated: color force, health components, panels txn debug/auto-debug flags standardized.
- Fallback shim: Where early-import ordering could break (very early in process start or inside sandboxed subprocess) a minimal local shim is used; remove these shims only after confirming helper import is always resolvable in those contexts.

Legacy Pattern vs New:
```python
# Legacy
if os.getenv('G6_TRACE_COLLECTOR','').lower() in {'1','true','yes','on'}:
	enable_tracing()

# New
from src.utils.env_flags import is_truthy_env
if is_truthy_env('G6_TRACE_COLLECTOR'):
	enable_tracing()
```

Do / Don’t:
- Do centralize any repeated composite checks (e.g. multiple related flags) in a small helper that itself calls `is_truthy_env` (keeps normalization single-source).
- Don’t introduce bespoke truthy parsing (like checking for `'Y'` or capital variants) unless formally added to `TRUTHY_SET` for consistency.
- Don’t mutate environment variables mid-execution to influence logic; prefer passing explicit parameters where feasible (tests may still set env for scenario control).

Follow-Up Opportunities:
- Introduce `is_falsy_env` (already provided) in places currently doing negative membership checks to improve readability.
- Add a lint rule (custom ruff plugin or simple grep in CI) to reject new occurrences of the raw pattern.
- Provide a small performance micro-benchmark if flag parsing becomes hot (current overhead negligible relative to I/O-bound operations).

### 11.10.1 Startup Summaries & One‑Shot Emissions

The platform emits a set of one-shot structured startup summaries to make runtime posture auditable and machine-consumable.

Core Elements:
1. Structured Line (always): A single-line `summary=<name>` style JSON-ish or structured log with stable key ordering.
2. Optional JSON Dump: Enabled via `G6_<SUMMARY>_SUMMARY_JSON`; includes masked sensitive fields and deterministic `hash` + `emit_ms` keys.
3. Optional Human Block: Enabled via `G6_<SUMMARY>_SUMMARY_HUMAN`; multi-line pretty text for operator consoles.
4. Dispatcher & Composite Hash: Each summary registers its per-summary truncated SHA256; dispatcher later emits `startup.summaries.hash` aggregating them for quick diff detection.
5. Sentinels: `_G6_<SUMMARY>_SUMMARY_EMITTED` global prevents duplicates; tests reset these explicitly when validating single-emission guarantees.
6. Masking: Central masking list ensures secrets never appear in logs yet hash stability is preserved (mask before hashing).

Adding a New Summary (Pattern):
```python
from src.startup.summary_helpers import emit_and_register_summary

def emit_feature_xyz_summary():
	if globals().get('_G6_FEATURE_XYZ_SUMMARY_EMITTED'):
		return
	data = {
		'enabled': feature_enabled(),
		'mode': current_mode(),
		'version': __version__,
	}
	emit_and_register_summary(
		name='feature.xyz.summary',
		data=data,
		json_flag='G6_FEATURE_XYZ_SUMMARY_JSON',
		human_flag='G6_FEATURE_XYZ_SUMMARY_HUMAN',
		human_block_fn=lambda d: (
			'Feature XYZ:\n'
			f"  enabled={d['enabled']}\n"
			f"  mode={d['mode']}\n"
			f"  version={d['version']}"
		),
	)
	globals()['_G6_FEATURE_XYZ_SUMMARY_EMITTED'] = True
	```

	### 11.11 Provider Modularization (A7) – Step 4 Client Bootstrap Extraction (2025-10)

	Scope: Relocated all credential & client bootstrap responsibilities from the monolithic `kite_provider.py` into a dedicated module `src/broker/kite/client_bootstrap.py`.

	Extracted Responsibilities:
	1. `.env` Hydration: Lightweight KEY=VALUE ingestion now via `hydrate_env()`.
	2. Immediate Client Build: `build_client_if_possible(provider)` mirrors constructor inline logic (unchanged logging tokens).
	3. Lazy Ensure: `ensure_client(provider)` replaces inline `_ensure_client`, preserving environment re-discovery & throttled logging.
	4. Credential Updates: `update_credentials(provider, api_key, access_token, rebuild)` centralizes mutation + optional rebuild semantics.

	Why:
	- Shrinks facade class to orchestration only; isolates side-effectful auth logic for future multi-provider reuse or swap (mock / alt vendor).
	- Simplifies targeted testing (bootstrap functions can be monkeypatched independently without touching unrelated option or expiry logic).
	- Enables eventual provider registry injecting a generic bootstrap strategy.

	Backward Compatibility:
	- `KiteProvider._ensure_client` and `update_credentials` remain public; they delegate to extracted functions. Fallback inline code path retained if import fails (defensive in early boot scenarios).
	- Logging messages (`Kite client initialized (constructor)` / `(lazy ensure_client)` / credential discovery notices) unchanged for test parity.
	- Environment variable precedence & late discovery semantics identical to previous implementation.

	Testing:
	- Existing provider initialization, diagnostics, and lazy-init tests continue to pass without modification.
	- No new environment flags introduced; extraction is purely organizational.

	Follow-Up Opportunities:
	1. Introduce interface `ProviderBootstrapStrategy` for alternate brokers (Zerodha, Fyers, mock) sharing the same facade shape.
	2. Add structured event on auth failure distinguishing network vs token errors before marking `_auth_failed`.
	3. Provide a dry-run mode for bootstrap to validate env presence without constructing a client (useful in deployment preflight checks).
	4. Token refresh scheduling hook (currently stub) could live beside bootstrap utilities for cohesion.

	Risk Mitigation:
	- Delegation wrapped in try/except to avoid import-time cascades if path refactors occur mid-series; fallback preserves legacy behavior.
	- Functions are idempotent with respect to already-initialized `provider.kite` instances.

	Removal Plan (Deferred): Inline fallback branches can be removed after two minor versions once stability confirmed; document in CHANGELOG when scheduled.

	Summary Line for Changelog:
	> A7 Step 4: Extracted Kite client bootstrap & credential management into `src.broker.kite.client_bootstrap` (no functional change).

	### 11.12 Provider Modularization (A7) – Step 5 Startup Summary Extraction (2025-10)

	Scope: Moved the one‑shot provider startup summary block (structured log, dispatcher registration, optional JSON & human formats) from the `KiteProvider` constructor into `src/broker/kite/startup_summary.py`.

	Motivation:
	- Further slims the constructor, isolating pure side-effect emission logic.
	- Eases targeted testing of summary output without invoking full provider heavy imports.
	- Prepares for future multi-provider registry where summaries can be orchestrated uniformly.

	Behavior Parity:
	- Log line token `provider.kite.summary` and key ordering unchanged.
	- Global sentinel `_KITE_PROVIDER_SUMMARY_EMITTED` reused to guarantee single emission.
	- JSON (`G6_PROVIDER_SUMMARY_JSON`) and human (`G6_PROVIDER_SUMMARY_HUMAN`) flags preserved verbatim.
	- Dispatcher `register_or_note_summary` call retained (best-effort guarded).

	Risk Mitigation:
	- Delegation wrapped in try/except; any import failure silently falls back to no-op (tests verify presence so failure would surface quickly).
	- Internal attribute access (`provider._settings`) confined to module with explicit comment; still treated as snapshot read only.

	Follow-Ups:
	1. Consider emitting a structured hash of summary fields for drift detection (if not already covered by dispatcher composite hash).
	2. Provide a generic `emit_provider_startup_summary(name, provider, fields)` helper to reduce code duplication across future providers.
	3. Add debug flag to force re-emit for manual diagnostics (`G6_FORCE_PROVIDER_SUMMARY=1`) without changing default idempotence.

	Changelog Line:
	> A7 Step 5: Extracted Kite provider startup summary emission into `src.broker.kite.startup_summary` (no functional change).

	### 11.13 Provider Modularization (A7) – Step 6 Rate Limiter & Throttled Logging Extraction (2025-10)

	Scope: Moved API rate limiter construction and throttled logging timestamp guards (`_rl_fallback`, `_rl_quote_fallback`) logic into `src/broker/kite/rate_limiter_helpers.py`.

	Rationale:
	- Reduces facade noise; keeps state orchestration readable.
	- Enables reuse of identical throttling semantics by future providers without copy/paste.
	- Facilitates isolated unit tests around throttling intervals if needed.

	Behavior Parity:
	- Interval default (5s) unchanged.
	- Attribute names `_rl_last_log_ts` / `_rl_last_quote_log_ts` retained so diagnostics relying on them (if any future exposure) remain stable.
	- Fallback inline logic preserved under try/except to avoid import-order regressions.

	Future Opportunities:
	1. Centralize additional throttled paths (e.g., auth failure warnings) through helpers.
	2. Add per-event counters (suppressed log attempts) for observability.
	3. Consider adaptive backoff if repeated failures occur inside throttled regions.

	Changelog Line:
	> A7 Step 6: Extracted rate limiter & throttled logging helpers to `src.broker.kite.rate_limiter_helpers` (no functional change).

	### 11.14 Provider Modularization (A7) – Step 7 Quotes Module Refinement (2025-10)

	Scope: Internal refactor of `src/broker/kite/quotes.py` consolidating duplicated normalization and LTP quality guard logic. Public functions `get_ltp` and `get_quote` retain identical signatures and behaviour.

	Changes:
	1. Added `_normalize_instruments`, `_quality_guard_ltps` helpers. (Removed legacy `_synthetic_ltp` helper Oct 2025.)
	2. Simplified `get_ltp` flow: early return on successful real fetch after quality guard (synthetic fallback path removed).
	3. No change to caching, batching semantics.

	Parity Guarantees:
	- Log messages (debug quality failure, auth warning) unchanged.
	- Error handling still routes through `handle_provider_error` with same component labels.

	Motivation:
	- Reduce cognitive load in primary functions.
	- Prepare ground for future batching/caching enhancements without growing function complexity.

	Follow-Ups (Deferred):
	1. Extract quote cache & TTL logic into dedicated `quote_cache.py` (will facilitate alternative cache backends).
	2. (Removed) synthetic quote & LTP normalization unification (obsolete post removal).
	3. Add lightweight metrics around cache hit ratio (synthetic fallback frequency metric removed).

	Changelog Line:
	> A7 Step 7: Refactored quotes module (normalization & quality guard helpers) with no functional changes.

	### 11.15 Provider Modularization (A7) – Step 8 Quote Cache & Fetch Extraction (2025-10)

	Scope: Extracted real quote retrieval concerns from `quotes.get_quote` into:
	1. `quote_cache.py` – thread-safe in-memory cache (symbol -> (timestamp, payload)).
	2. `quote_fetch.py` – orchestration of normalization, cache fast-path, optional batching, rate limiting, retry, and cache population.

	Behavior Parity:
	- Environment variable `G6_KITE_QUOTE_CACHE_SECONDS` honored exactly as before.
	- Batching + limiter integration semantics unchanged; limiter instance still cached on provider (`_g6_quote_rate_limiter`).
	- Auth failure handling remains in `quotes.get_quote`; synthetic fallback removed.

	Rationale:
	- Reduces size/complexity of `quotes.py` and isolates side-effectful network logic.
	- Enables future replacement/injection of alternate cache strategies (e.g., shared process cache) without modifying public API.

	Follow-Ups:
	1. Add metrics counters: `quote_cache_hits`, `quote_cache_misses` surfaced via provider diagnostics.
	2. Consider moving synthetic quote build into `synthetic_quotes.py` for symmetry with LTP synthetic builder.
	3. Introduce configurable max cache size with LRU eviction if symbol universe grows.
	4. Add structured event on rate limit detection for observability.

	Changelog Line:
	> A7 Step 8: Extracted quote cache & real fetch logic to `quote_cache.py` and `quote_fetch.py` (no functional change).

	### 11.16 Provider Modularization (A7) – Step 9 Quote Cache Diagnostics (2025-10)

	Scope: Augmented provider diagnostics with quote cache statistics after cache extraction.

	New Diagnostics Keys:
	- `quote_cache_size`: current number of cached symbols.
	- `quote_cache_hits`: cumulative in-process hit count since start (resets only on process restart or explicit test helper usage).
	- `quote_cache_misses`: cumulative miss count (includes TTL expiry misses and disabled-cache code paths where ttl <= 0).

	Implementation:
	- Added counters and `snapshot_meta()` in `quote_cache.py`.
	- `diagnostics.provider_diagnostics` imports `quote_cache` best-effort; absence yields `None` values.

	Rationale:
	- Enables visibility into cache effectiveness and guides future decisions (e.g., increasing TTL, adding eviction, or disabling cache).

	Follow-Ups:
	1. Expose hit/miss ratio metric (Prometheus gauge) gated behind an environment flag to avoid noise.
	2. Provide optional reset endpoint / method for long-lived processes (facilitate rolling window analysis).
	3. Add time-bucketed sampling (e.g., hits_last_5m) if high churn observed.

	Changelog Line:
	> A7 Step 9: Added quote cache diagnostics fields (size, hits, misses) to provider diagnostics.

	### 11.17 Provider Modularization (A7) – Step 10 Quote Cache Prometheus Metrics (2025-10)

	Scope: Expose quote cache performance via Prometheus under existing metric group `cache` (aligned with root & serialization cache patterns).

	New Metrics (all gated by cache group filters; appear when metrics registry initialized):
	- `g6_quote_cache_hits_total` (Counter) – Incremented on cache hit.
	- `g6_quote_cache_misses_total` (Counter) – Incremented on cache miss (includes TTL expiry & disabled cache TTL<=0 paths).
	- `g6_quote_cache_size` (Gauge) – Current number of cached symbols.
	- `g6_quote_cache_hit_ratio` (Gauge) – Hits / (Hits + Misses), updated on each access or put.

	Implementation Details:
	1. Added `MetricDef` entries to `src/metrics/spec.py` (mirrors serialization cache naming: `_hits_total` / `_misses_total`).
	2. Augmented `quote_cache.py` with `_export_metrics(hit)` helper executed on get (hit/miss) and put (size/ratio refresh without changing counters).
	3. Lazy integration: if metrics subsystem unavailable (`get_metrics()` returns None) instrumentation silently no-ops.
	4. No additional environment flags introduced; gating handled by existing metric group controls (`G6_ENABLE_METRIC_GROUPS` / `G6_DISABLE_METRIC_GROUPS`).

	Parity & Safety:
	- Existing diagnostics (Step 9 additions) unchanged.
	- No changes to cache semantics, eviction (still unbounded), or TTL honoring.
	- Failure to register metrics (e.g., missing `prometheus_client`) is swallowed without raising.

	Operational Notes:
	- For large symbol churn, size gauge may grow unbounded; future enhancement may add optional max size + eviction metric similar to serialization cache.
	- Hit ratio gauge updates after each get or put; during early warm-up it may oscillate (acceptable for observability).

	Follow-Ups (Deferred):
	1. Add optional `G6_KITE_QUOTE_CACHE_MAX` + eviction counter/gauge.
	2. Add per-symbol freshness histogram (age distribution) if staleness debugging needed.
	3. Consider unified cache instrumentation utility to DRY patterns shared with root & serialization caches.

	Changelog Line:
	> A7 Step 10: Added quote cache Prometheus metrics (hits, misses, size, hit ratio) under cache group.

	### 11.18 Provider Modularization (A7) – Step 11 Provider Registry (2025-10)

	Scope: Introduced a lightweight provider registry abstraction to decouple provider selection (currently only `KiteProvider`) from call sites. Enables future multi-provider strategy (fallback / fan-out) without refactoring existing modules again.

	Module: `src/broker/provider_registry.py`

	Core API:
	- `register_provider(name, factory, default=False, eager=False)` – Registers a provider factory by canonical lowercase name. First registration becomes default unless default=False and an existing default remains.
	- `get_provider(name: str | None = None, fresh: bool = False)` – Returns singleton instance (lazy created) or new instance when `fresh=True`. Name resolution precedence: explicit arg > `G6_PROVIDER` env > default.
	- `set_default(name)` – Reassign default provider.
	- `list_providers()` – Sorted list of registered names.
	- `reset_registry()` – Test helper clearing factories & singletons.
	- `get_active_name()` – Last successfully resolved provider key.

	Behaviors / Guarantees:
	1. Auto-registers `kite` via `KiteProvider.from_env` on import (best-effort; silent if import fails).
	2. Duplicate registrations log a warning and overwrite the previous factory (simplifies hot reload scenarios in tests).
	3. Environment override uses `G6_PROVIDER` (case-insensitive); unknown values fall back to default with a warning.
	4. No exceptions propagate on factory construction failure unless caller requests a fresh instance repeatedly; errors are logged and `None` returned.

	Testing: Added `tests/test_provider_registry.py` covering default resolution, env override, fresh instantiation, and unknown provider.

	Deferred Enhancements:
	- Capability metadata (e.g., `supports_quotes`, `supports_options`).
	- Aggregated diagnostics snapshot across all instantiated providers.
	- Entry-point / plugin auto-discovery (`G6_PROVIDER_PLUGINS=1`).
	- (Removed) fallback chaining via synthetic-only provider.

	Migration Notes:
	- Existing code constructing `KiteProvider()` directly remains valid. Future orchestration code (e.g., collectors) can migrate to `get_provider()` for provider-agnostic behavior.
	- Once a second provider is introduced, update documentation with a selection matrix (features vs provider) and add capability flags.

	Changelog Line:
	> A7 Step 11: Added provider registry (`provider_registry.py`) enabling pluggable provider selection via G6_PROVIDER.

	### 11.19 Provider Modularization (A7) – Step 12 Capability Metadata (2025-10)

	Scope: Introduced capability metadata to the provider registry, enabling feature-aware orchestration decisions without hard-coding provider type checks.

	Additions:
	- `register_provider(..., capabilities={...})` optional mapping storing boolean feature flags per provider.
	- Internal `_CAPS` dict keyed by provider name; populated on registration (empty dict if omitted).
	- Accessors:
	  * `get_capabilities(name: str | None = None) -> dict[str,bool]` – Returns copy of capability map (name omitted -> active or default provider).
	  * `provider_supports(capability: str, name: str | None = None) -> bool` – Convenience predicate.

	Default Kite Capabilities (post synthetic removal):
	```
	quotes: true
	ltp: true
	options: true
	instruments: true
	expiries: true
	```

	Use Cases (Future):
	1. Conditional feature exposure in UI / APIs (e.g., only show greeks panel if provider_supports('options')).
	2. Multi-provider orchestration: choose a provider that supports a required capability set.
	3. (Removed) graceful degradation via synthetic_fallback.

	Design Notes:
	- Capabilities intentionally flat boolean flags; avoid premature hierarchical or versioned schemas.
	- Registry remains agnostic to semantics—`expiries` documented; synthetic-related naming removed.
	- Accessors return copies to prevent accidental mutation of internal state.

	Testing: Added `tests/test_provider_registry_capabilities.py` validating baseline kite capabilities and custom provider override.

	Deferred Enhancements:
	- Capability intersection resolver helper: `find_providers(requires={'quotes','options'})`.
	- Soft capability levels (e.g., `options_detail: full|summary`).
	- Dynamic capability mutation if provider reconfigures at runtime (would require invalidating caches / notifying observers).

	Changelog Line:
	> A7 Step 12: Added capability metadata to provider registry (capability accessors & baseline kite flags).

	### 11.20 Collector Pipeline – Error Taxonomy & Executor (2025-10)

	Scope: Introduced a phase-level error taxonomy and centralized executor to replace broad generic exception handling inside the shadow collector pipeline. Goals: (1) deterministic control-flow on expected data gaps vs transient recoverable conditions vs fatal defects, (2) cleaner logging/metrics classification surface, (3) foundation for future retries / backoff without embedding logic in each phase.

	Components:
	- `src/collectors/errors.py`
	  * `PhaseAbortError` – Clean early exit (precondition unmet); treated as expected no-data outcome (e.g., cannot resolve expiry, no strikes supplied). Does not imply infrastructure or logic defect.
	  * `PhaseRecoverableError` – Transient or external issue (e.g., provider returned zero instruments / quotes). Pipeline stops further phases for that expiry but outer cycle continues; candidate for future retry/backoff.
	  * `PhaseFatalError` – Unexpected internal failure (invariant breach / logic bug). Logged at higher severity; pipeline halts for that expiry; caller may escalate.
	  * `classify_exception(exc)` helper returns one of `abort|recoverable|fatal|unknown` (unknown for non-taxonomy exceptions).
	- `src/collectors/pipeline/executor.py` – `execute_phases(ctx, state, phases)` wrapper iterating ordered callables and applying taxonomy-based termination rules. Appends structured error tokens to `state.errors` using format `<classification>:<phase_name>:<detail>`.

	Phase Mappings (initial wave):
	- `phase_resolve`: Maps provider `ResolveExpiryError` -> `PhaseAbortError('resolve_expiry:...')` (expected no-data condition). Missing resolution still raises abort (`expiry_unresolved`).
	- `phase_fetch`: Empty instrument domain via `NoInstrumentsError` -> `PhaseRecoverableError('no_instruments_domain')`. Post-fetch empty instruments (any path) -> `PhaseRecoverableError('no_instruments')`.
	- `phase_enrich`: Domain `NoQuotesError` -> `PhaseRecoverableError('enrich_no_quotes_domain')`. Post-enrich empty -> `PhaseRecoverableError('enrich_empty')`.
	- Remaining observational phases retain swallow & annotate model (they do not influence subsequent phase viability yet).

	Design Rationale:
	1. Early Abort vs Recoverable: Distinguish structural absence (abort) from transient provider outage (recoverable) to avoid conflating uptime issues with expected gaps (e.g., off-cycle rules, thin expiries).
	2. Minimal Surface: Three explicit classes keep classification simple for logging/metrics dashboards (avoids overfitting early to numerous granular states).
	3. Executor Centrality: Central loop prevents each phase from re‑implementing break/continue logic and enables future features (retry wrapper, timing histograms, phase-specific latency metrics).

	Logging Pattern:
	- Executor emits `expiry.phase.exec` debug lines with fields: `phase`, `outcome` (`ok|abort|recoverable|fatal|unknown`), `ms`, `index`, `rule`, `errors`, `enriched`.
	- Downstream analytics can derive per-phase error ratios without parsing heterogeneous error strings across phases.

	Testing:
	- `tests/test_pipeline_executor_taxonomy.py` – Core executor outcome suite (ok, abort, recoverable, fatal, unknown).
	- `tests/test_phase_resolve_taxonomy_mapping.py` – Domain ResolveExpiryError -> abort mapping.
	- `tests/test_phase_fetch_enrich_domain_mapping.py` – Domain NoInstrumentsError / NoQuotesError -> recoverable mapping.

	Migration / Integration Notes:
	- Legacy orchestration still directly calling phase functions should migrate to `execute_phases` (ensures classification). Mixing both styles risks uncaught taxonomy exceptions if future phases raise directly.
	- New phases should raise taxonomy exceptions rather than appending to `state.errors` directly when the outcome influences downstream viability.
	- When adding a new domain exception, first decide: structural absence (Abort), transient external (Recoverable), or invariant violation (Fatal). Raise the corresponding taxonomy class close to the source to preserve context.

	Deferred Enhancements:
	1. Metrics: Counter per outcome per phase (`g6_pipeline_phase_total{phase, outcome}`).
	2. Retry Logic: Optional retry policy for recoverable phases (configurable max attempts / backoff).
	3. Structured Error Objects: Replace string tokens in `state.errors` with dataclass records for richer post-analysis (kept simple for now to avoid churn).
	4. Phase Timing Histogram: Export latency histograms once cardinality policy settled.

	Changelog Line:
	> Collector: Introduced phase error taxonomy (abort/recoverable/fatal) and centralized executor with domain mapping for expiry resolution, instrument fetch, and quote enrichment.

	### 11.21 Collector Pipeline – Phase Outcome Metrics & Retry (2025-10)

	Scope: Adds optional bounded retry logic for recoverable phase failures and emits low‑cardinality metrics for per‑phase attempts, retries, outcomes, and cumulative duration. This extends Section 11.20 by operationalizing the Recoverable classification without forcing behavioral change (retries are opt‑in).

	Configuration (Environment Flags):
	```
	G6_PIPELINE_RETRY_ENABLED=0|1          (default 0 – preserves single attempt behavior)
	G6_PIPELINE_RETRY_MAX_ATTEMPTS=3       (inclusive of initial attempt; min=1)
	G6_PIPELINE_RETRY_BASE_MS=50           (base backoff in milliseconds, exponential 2^(attempt-1))
	G6_PIPELINE_RETRY_JITTER_MS=0          (optional random 0..jitter added per attempt)
	```

	Retry Semantics:
	- Only taxonomy Recoverable (or classify_exception() -> 'recoverable') outcomes are eligible.
	- Abort / Fatal / Unknown immediately stop further phase execution.
	- Backoff growth: delay_ms = base_ms * 2^(attempt-1) (+ optional jitter), capped at 5000 ms.
	- Final outcome labels:
	  * ok – success (may have followed retries)
	  * recoverable – single recoverable failure (retries disabled)
	  * recoverable_exhausted – retries enabled but max attempts reached without success
	  * abort / fatal / unknown – unchanged from taxonomy stage

	Metrics (Spec Added in `src/metrics/spec.py`):
	- `g6_pipeline_phase_attempts_total{phase}` – increments every attempt (including first).
	- `g6_pipeline_phase_retries_total{phase}` – increments only for attempts index > 1.
	- `g6_pipeline_phase_outcomes_total{phase,final_outcome}` – exactly one increment per phase execution sequence.
	- `g6_pipeline_phase_duration_ms_total{phase,final_outcome}` – cumulative wall‑clock ms across all attempts for that sequence.
	- `g6_pipeline_phase_runs_total{phase,final_outcome}` – mirror counter to allow ratio derivations separate from pure duration accounting.

	Cardinality Rationale:
	- Labels limited to {phase} and {final_outcome}; no attempt index label (avoids unbounded growth and aligns with on‑call dashboards expecting stable series).
	- Duration exported as cumulative counter to enable deriving average = duration_ms_total / runs_total; avoids premature histogram explosion.

	Executor Changes (`execute_phases`):
	- Introduces retry loop around each phase with configuration gating.
	- Aggregates total elapsed time per phase (across attempts) recorded on finalization.
	- Emits debug `expiry.phase.exec` per attempt (unchanged style) preserving granular logs even when metrics aggregate.
	- Stops overall phase list on any final outcome that is not `ok` (maintaining original control flow semantics).

	Usage Guidance:
	1. Keep recoverable phase exceptions narrowly scoped; broad wrapping can mask real defects and induce unnecessary delay.
	2. Avoid long blocking inside phases when retries enabled—prefer small fast checks to leverage exponential backoff.
	3. If a phase performs internal retries already, consider normalizing around the executor policy to prevent duplicated delay.
	4. For future histograms, ensure bucket policy reviewed against actual latency distribution (exported debug timings can seed this).

	Testing:
	- `tests/test_executor_retries.py` covers: recoverable->success, recoverable exhausted, retry disabled single attempt.

	Deferred Enhancements:
	- Optional jitter enablement by feature flag if burst synchronization observed.
	- Phase-specific override (e.g., high criticality phases with different max attempts).
	- Histogram adoption after validating distribution variance.
	- Structured per-attempt metrics if on-call investigations require granular attempt latency.

	Changelog Line:
	> Collector: Added optional recoverable retry policy (env-gated) and phase execution metrics (attempts, retries, outcomes, cumulative duration).


```

Checklist Before Merging:
### 11.22 Collector Pipeline – Structured Error Records (2025-10)

Scope: Introduces parallel structured error recording for phase-level failures without breaking existing consumers of the legacy `state.errors` token list. Each legacy string token now has a corresponding `PhaseErrorRecord` dataclass entry in `state.error_records`.

Motivation:
- Facilitate richer post-cycle analytics (classification counts by phase, retry attempt attribution) without repeatedly parsing string prefixes.
- Preserve 100% backward compatibility (tests depending on exact token content/order remain valid).
- Provide an evolution path toward downstream persistence or streaming of structured pipeline diagnostics.

Data Model (`src/collectors/pipeline/error_records.py`):
```
@dataclass(slots=True)
class PhaseErrorRecord:
	phase: str                   # logical phase name (executor fn __name__ or normalized alias)
	classification: str          # abort | recoverable | recoverable_exhausted | fatal | unknown | <phase_specific>
	message: str                 # short message component (suffix of legacy token after phase)
	detail: Optional[str]        # reserved for future richer context (currently same as message or exception code)
	attempt: int                 # attempt number (1-based) within retry loop
	timestamp: float             # capture time (epoch seconds)
	outcome_token: str           # exact legacy token inserted into state.errors
	extra: dict | None           # optional extension field (kept None by default)
```

Helper (`add_phase_error` in `error_helpers.py`):
- Signature: `add_phase_error(state, phase, classification, message, *, detail=None, attempt=1, token=None, extra=None)`
- Behavior: Derives (or uses provided) legacy token, appends to `state.errors`, then appends `PhaseErrorRecord` with `outcome_token` referencing that token.
- Safety: Wrapped in try/except to avoid raising during error instrumentation paths.

Executor Changes:
- All exception branches (`PhaseAbortError`, `PhaseRecoverableError`, `PhaseFatalError`, generic) now call `add_phase_error` instead of directly appending to `state.errors`.
- Attempt number passed so first recoverable failure retains `attempt=1`; subsequent attempts (if any) only log additional tokens when an exception was thrown (success path adds no error record).

Phase Function Changes:
- Direct `state.errors.append()` calls replaced with `add_phase_error` (e.g. `phase_fetch`, `phase_enrich`, etc.) while keeping the original token strings intact (e.g. `fetch_recoverable:<msg>`).
- Phase-specific prefixes (historical tokens like `resolve_abort:`) are mapped with `classification` mirroring the token prefix for continuity.

Backward Compatibility:
- No existing token strings altered.
- Order of `state.errors` unaffected (helper preserves append timing).
- Consumers ignoring `error_records` see identical behavior.

Testing (`tests/test_structured_error_records.py`):
1. Abort path: Ensures abort token and exactly one structured record with classification `abort`.
2. Recoverable + retry success: Validates only first failed attempt produces a record with attempt=1; success attempt emits no error token.
3. Fatal path: Single fatal record parity.
4. Phase-level mapping sample (fetch) still produces paired structured record for internal token.

Usage Guidance:
- New phases should prefer raising taxonomy exceptions (Abort/Recoverable/Fatal) where control flow depends on outcome; `add_phase_error` primarily for internal catch-and-record situations or legacy-style inline token additions.
- Avoid overloading `classification` with high-cardinality dynamic substrings; keep it to taxonomy labels or stable phase prefixes. Use `message` (or future `detail`) for variable content.
- For future persistence, treat `outcome_token` as a join key back to logs / legacy analytics.

Deferred Enhancements:
1. Add aggregate structured error metrics (counter by classification, phase) once cardinality review complete (can reuse existing phase label set).
2. Optional JSON emission of structured errors at cycle end behind an env flag (`G6_PIPELINE_EMIT_STRUCT_ERRORS`).
3. Rich `detail` population (trace snippet, provider identifier) behind privacy/redaction guidelines.
4. Migration script to backfill historic token logs into `PhaseErrorRecord`-like rows for longitudinal analysis.

Changelog Line:
> Collector: Added structured phase error records (`state.error_records`) in parallel with legacy `state.errors` tokens; helper `add_phase_error` centralizes recording.

Migration Notes:
- No action required for existing consumers.
- Downstream code wanting structured access can start reading `state.error_records` opportunistically; always guard for empty list on older serialized snapshots.

Instrumentation Rationale:
- Minimal memory overhead (dataclass slots + small field set) vs repeated string parsing.
- Maintains single source of truth for token text (stored once in `errors`, referenced in record).

Security / Privacy:
- Current messages are concise codes; if future `detail` includes external error text, ensure provider tokens / secrets are sanitized upstream before calling helper.

```

#### 11.22.1 Enhancements – Metrics, Export & Enrichment Flags (2025-10)

Additive capabilities building on 11.22 structured records.

Environment Flags:
```
G6_PIPELINE_STRUCT_ERROR_METRIC=0|1          # When truthy, increments g6_pipeline_phase_error_records_total
G6_PIPELINE_STRUCT_ERROR_EXPORT=0|1          # When truthy, executor attaches JSON snapshot in state.meta['structured_errors']
G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT=0|1   # If export enabled, also prints single-line JSON (prefix: pipeline.structured_errors)
G6_PIPELINE_STRUCT_ERROR_ENRICH=0|1          # When truthy, helper attempts provider name list & short traceback (fatal/unknown only)
```

Metric:
`g6_pipeline_phase_error_records_total{phase,classification}`
- Increments once per legacy token (i.e., per structured record) only when metric flag enabled.
- Cardinality bounded by existing phase set × small classification set.

JSON Snapshot Shape (state.meta['structured_errors']):
```
{
	'count': <int>,
	'records': [ {'phase':..,'classification':..,'message':..,'attempt':..,'ts':..}, ... ],
	'exported_at': <epoch>,
	'hash': <sha256 first 16 hex of records array>
}
```

Stdout Emission:
Single line: `pipeline.structured_errors{"count":1,...}` for easy grep and log ingestion; stable key ordering provided by json.dumps(sort_keys=True) for hash.

Enrichment (`G6_PIPELINE_STRUCT_ERROR_ENRICH`):
- `extra.providers`: Up to 10 provider names (truncated 40 chars) if discoverable via state.settings.*.
- `extra.trace`: Short traceback (last ~800 chars) only for `fatal` or `unknown` classifications.

Privacy / Redaction:
- Provider names treated as non-sensitive identifiers; if future tokens embed secrets they must be masked BEFORE reaching helper.
- Traceback size capped and only for severe classifications to limit inadvertent data exposure.

Testing:
- `tests/test_structured_error_metrics_and_export.py` covers metric increment, JSON export, and basic parity assertions.

Failure Tolerance:
- All instrumentation paths wrapped in try/except (no user-visible failures if metrics registry absent or stdout write fails).

Future Ideas:
1. Optional redaction pattern list environment flag (`G6_PIPELINE_STRUCT_ERROR_REDACT_PATTERNS`).
2. Compression of snapshot when record counts large (currently small).
3. Cycle-level aggregation metrics (unique classifications per cycle) for anomaly detection.

Changelog Addition:
> Collector: Added optional structured error record counter and JSON/export + enrichment flags (11.22.1).

#### 11.22.2 Cycle Summary (2025-10)

Purpose: Emit a lightweight per-execution aggregate summary (`state.meta['pipeline_summary']`) to aid operators and downstream analytics without parsing per-phase logs.

Environment Flags:
```
G6_PIPELINE_CYCLE_SUMMARY=1            # (default on) attach summary dict to state.meta
G6_PIPELINE_CYCLE_SUMMARY_STDOUT=0|1   # optional single-line emission `pipeline.summary{"phases_total":...}`
```

Summary Shape (example):
```
{
	'phases_total': 5,
	'phases_ok': 4,
	'phases_error': 1,
	'phases_with_retries': 1,
	'retry_enabled': true,
	'error_outcomes': {'recoverable':1},
	'aborted_early': false,
	'fatal': false,
	'recoverable_exhausted': false
}
```

Field Notes:
- phases_total: Count of phase entries actually executed (includes the failing one if early stop).
- phases_error: Number of non-ok final outcomes (excludes transient retry attempts once resolved).
- phases_with_retries: Number of phases where attempts >1 (successful or exhausted).
- error_outcomes: Map of outcome->count excluding 'ok'.
- aborted_early / fatal / recoverable_exhausted: Convenience booleans for quick branching.

Behavior:
- Summary built after structured error export block; independent of whether errors occurred.
- Defaults on to encourage observability (set flag to 0 to suppress if footprint concerns arise).
- All logic wrapped in try/except; failure to build summary never breaks caller.

Testing: `tests/test_pipeline_cycle_summary.py` covers OK, early abort, and retry-success scenarios.

Future Enhancements:
1. Add histogram or moving window success ratios.
2. Persist summaries to a rotating file for longer-term diffing.
3. Optional inclusion of per-phase concise list (phase_runs) behind verbose flag.

Changelog Addition:
> Collector: Added per-cycle pipeline summary (phases, error counts, retry indicators) with optional stdout emission (11.22.2).

#### 11.22.3 Panel Export (Structured Errors + Summary) (2025-10)

Purpose: Provide dashboard / panels subsystem with a single JSON artifact combining the pipeline cycle summary and structured error list for rapid UI consumption and operator drill-down.

Environment Flag:
```
G6_PIPELINE_PANEL_EXPORT=0|1    # When truthy, write pipeline_errors_summary.json into $G6_PANELS_DIR (or data/panels)
```

Output File: `pipeline_errors_summary.json`
```
{
	"version": 1,
	"summary": { ...same fields as 11.22.2... },
	"errors": [ {"phase":"fetch","classification":"recoverable","message":"no_instruments","attempt":1}, ... ],
	"error_count": <int>,
	"exported_at": <epoch_seconds>
}
```

Behavior:
- File written at end of `execute_phases` after summary creation.
- Missing / empty errors list yields `error_count:0`.
- Directories auto-created; failures silently ignored (non-fatal path).
- Version field reserved for future schema evolution (add fields without rupture).

Security / Privacy:
- Mirrors structured error enrichment rules (no stack trace unless enrichment flag adds truncated trace inside structured records; panel export excludes trace for now to keep payload lean and safe).

Testing: `tests/test_pipeline_panel_export.py` verifies file presence and key fields for both ok and error scenarios.

Future Enhancements:
1. Add optional inclusion of per-phase timings (phase_runs) behind verbose flag.
2. Provide rolling N cycle history file for trend panels.
3. Integrate hash field for diff detection similar to structured error export.

Changelog Addition:
> Collector: Added panel export of pipeline summary + structured errors JSON (11.22.3).
- [ ] Structured line appears exactly once in integration test capture.
- [ ] Composite hash line includes new summary hash fragment.
- [ ] JSON & human blocks gated by flags and absent by default.
- [ ] Sensitive keys masked (add to mask list if new secret field introduced).
- [ ] Sentinel set only after successful emit (avoid premature set inside try/except pre-hash).

Anti-Patterns:
- Emitting only a human block (breaks machine parsing).
- Logging raw secrets then masking (hash churn + leakage risk).
- Multiple ad-hoc summaries for closely related concerns (prefer one consolidated object with clearly named keys).

Deprecation: When renaming a summary, keep the old name emitting a stub with `deprecated: true` and a `replacement` key for one minor version.

Future Hardening Opportunities:
- Dispatcher integrity metric (count expected vs registered vs emitted).
- Optional signature line with HMAC if tamper resistance becomes a requirement.

#### 11.22.4 Panel Export Rolling History (2025-10)

Purpose: Enable operators and dashboards to perform short-horizon trend and diff analysis without scraping logs by retaining a rolling window of the most recent panel export artifacts, plus an index for efficient listing.

Environment Flags:
```
G6_PIPELINE_PANEL_EXPORT_HISTORY=0|1          # When truthy, write a timestamped copy of each pipeline_errors_summary export
G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT=<int>  # Max historical files to retain (default 20; minimum 1)
```

Artifacts (in `$G6_PANELS_DIR`):
- `pipeline_errors_summary.json` (unchanged base latest snapshot)
- `pipeline_errors_summary_<epoch>.json` (one per cycle while history enabled)
- `pipeline_errors_history_index.json` index file:
```
{
	"version": 1,
	"count": <current_retained>,
	"limit": <configured_limit>,
	"files": ["pipeline_errors_summary_1696670001.json", ...]  // newest first
}
```

Behavior:
- After writing the base file, if history is enabled a timestamped clone is created using the `exported_at` seconds value.
- Files with prefix `pipeline_errors_summary_` are enumerated, sorted descending by embedded timestamp, and pruned beyond limit.
- Index file rewritten each cycle; failures are silent and do not impact core pipeline.
- Limit coercion: non-integer or <1 values fallback to 1.

Design Notes:
- Chose per-file JSON (vs single growing log) to simplify atomic writes and pruning without rewriting large blobs.
- Epoch-second granularity: Acceptable risk of collision; extremely fast multiple cycles within same second would overwrite; considered negligible given cycle cadence. Future enhancement could append monotonic counter on collision.
- Index kept lean; does not duplicate summary/error payloads to avoid redundancy.

Testing: `tests/test_pipeline_panel_export_history.py` covers multi-cycle creation, pruning, ordering newest-first, and limit correctness for both ok and error outcomes.

Future Enhancements:
1. Add change hash (digest) to index entries for delta detection.
2. Provide optional compressed variant (`.json.gz`) for large error payload scenarios.
3. Add retention by age (seconds) in addition to count-based pruning.
4. Merge with prospective trends file (aggregation) to reduce file count pressure if cadence grows.

Changelog Addition:
> Collector: Added rolling history option for panel export with pruning and index (11.22.4).

Operational Guidance:
- Keep limit modest (<=50) to avoid directory listing overhead on slower disks.
- For dashboards polling directory, read index once and only open newest N as needed.
- If disk IO becomes a concern, disable history or raise cycle interval.

Anti-Patterns:
- Storing history on network share without considering latency (may delay pipeline tail latency).
- Large limits without rotation strategy, turning panel dir into quasi-log store.

Security / Privacy:
- Same payload as base file; ensure upstream redaction before enabling history in sensitive environments.

Deprecation Path:
- If schema evolves, increment index version; maintain backward compatibility for at least one minor version before removing older processing paths.

#### 11.22.5 Panel Export Hashing (2025-10)

Purpose: Provide deterministic change detection and downstream caching for panel export artifacts and rolling history.

Environment Flag:
```
G6_PIPELINE_PANEL_EXPORT_HASH=0|1  # default 1 (on). When truthy compute SHA-256 based 16 char content hash.
```

Behavior:
- Hash computed over stable projection (summary, errors, error_count, version) excluding volatile `exported_at`.
- Truncated to 16 hex chars for brevity (collision probability acceptable for dashboard refresh gating; extendable later).
- Added as `content_hash` field in `pipeline_errors_summary.json` and each history artifact.
- History index: when hashing enabled, `files` becomes an array of objects: `{ "file": <name>, "hash": <content_hash>, "ts": <exported_at> }` otherwise remains list of filenames.
- Failures to hash are silent (export still written minus hash) to avoid disrupting pipeline.

Testing: `tests/test_pipeline_panel_export_hash.py` validates stability across identical runs and hash presence in index entries.

Future Enhancements:
1. Add optional full-length hash flag for cryptographic audit scenarios.
2. Append hash to filename for immutable cache semantics (opt-in) e.g. `pipeline_errors_summary_<ts>_<hash>.json`.
3. Provide differential export (only new errors) keyed by hash lineage.

#### 11.22.6 Pipeline Config Snapshot (2025-10)

Purpose: Capture the active pipeline execution configuration (env-driven flags + retry parameters) each cycle (or first cycle) for reproducibility, auditing and quick operator visibility.

Environment Flags:
```
G6_PIPELINE_CONFIG_SNAPSHOT=0|1          # When truthy, write pipeline_config_snapshot.json
G6_PIPELINE_CONFIG_SNAPSHOT_STDOUT=0|1   # Optional stdout emission (single line) mirroring JSON
```

Snapshot File: `pipeline_config_snapshot.json`
```
{
	"version": 1,
	"exported_at": <epoch>,
	"flags": {
		"G6_PIPELINE_RETRY_ENABLED": true,
		"G6_PIPELINE_RETRY_MAX_ATTEMPTS": 3,
		...
		"G6_PIPELINE_PANEL_EXPORT_HASH": true
	},
	"content_hash": "<16hex>"
}
```

Behavior:
- Written at the start of `execute_phases` (pre-phase execution) so consumers know the configuration governing that cycle.
- Hash computed solely over the `flags` mapping (sorted keys) to stay stable across cycles when flags unchanged.
- File overwritten each cycle (no history) to avoid noise; history could be added later via dedicated flag if needed.
- Silent failure model (never aborts pipeline on filesystem errors).

Testing: `tests/test_pipeline_config_snapshot.py` ensures creation, field presence, and hash stability across multiple runs without flag changes.

Future Enhancements:
1. Add optional history (`pipeline_config_snapshot_<ts>.json`) behind a separate flag for change audits.
2. Emit diff summary if hash changes between consecutive cycles.
3. Include derived values (e.g. effective backoff schedule preview) for richer diagnostics.

Operational Guidance:
- Use stdout variant in containerized environments where sidecar tailing is preferred over volume mounts.
- Pair with panel export hash to correlate behavioral changes with configuration drift.

Security Considerations:
- Only boolean/primitive tuning values included; no secrets expected. If future flags may hold secrets, introduce redaction list before enabling snapshot history.

#### 11.22.7 Structured Error Redaction Layer (2025-10)

Purpose: Prevent inadvertent leakage of sensitive substrings (e.g. API tokens, account IDs) in structured error exports and panel artifacts while preserving original legacy token stream for regression parity.

Environment Flags:
```
G6_PIPELINE_REDACT_PATTERNS="foo,bar[0-9]+"   # Comma-separated regex patterns
G6_PIPELINE_REDACT_REPLACEMENT="***"          # Replacement string (default *** )
```

Behavior:
- Applied at `add_phase_error` time to the structured `message` field only; legacy token (`state.errors`) remains unmodified for deterministic matching / tests.
- Panel export applies a defensive re-redaction pass to cover scenarios where flag changes mid-cycle or earlier records were created before enabling patterns.
- Invalid regex patterns are skipped silently; remaining patterns still applied.
- Redaction is a simple global regex substitution; order is left-to-right as provided.

Testing: `tests/test_pipeline_redaction.py` validates single and multiple pattern operation, invalid pattern resilience, and token non-redaction guarantee.

Future Enhancements:
1. Add capture-group preserving replacement (e.g. show last 4 characters).
2. Provide structured `redacted_fields` diagnostics list for operator audit.
3. Support JSON path based redaction if future records add nested structures.

Security Notes:
- Prefer precise patterns (anchor where possible) to avoid over-redaction leading to loss of forensic utility.
- If secrets are large random strings, consider hashing instead of blanket replacement for correlation without exposure.

#### 11.22.8 Trend Aggregation (Rolling Metrics) (2025-10)

Purpose: Offer lightweight, append-only operational trend view (success rate, error counts) without parsing full history artifacts.

Environment Flags:
```
G6_PIPELINE_TRENDS_ENABLED=0|1    # When on, maintain pipeline_errors_trends.json
G6_PIPELINE_TRENDS_LIMIT=<int>    # Max records retained (default 200, min 1)
```

Artifact: `pipeline_errors_trends.json`
```
{
	"version": 1,
	"records": [
		{"ts": 1696671001, "phases_total": 5, "phases_error": 0, "error_count": 0, "hash": "abc123..."},
		...
	],
	"aggregate": {
		"cycles": 42,
		"success_cycles": 38,
		"success_rate": 0.9047,
		"errors_total": 7,
		"phase_errors_total": 9,
		"phases_total": 210
	}
}
```

Behavior:
- Appended after panel export; uses summary + export error_count + optional `content_hash`.
- Prunes oldest entries beyond limit (simple list slice) keeping memory bounded.
- Aggregate recalculated each cycle (O(n) over retained window; small by design). If limit grows large, future optimization could maintain incremental counters.

Testing: `tests/test_pipeline_trends.py` ensures accumulation, pruning to limit, and aggregate correctness (bounds checked for success_rate).

Future Enhancements:
...existing code...
#### 11.22.9 Legacy cycle_tables Integration (2025-10)

Purpose: Provide a backward-compatible bridge for any residual consumers of the deprecated `cycle_tables` interface to access the modern `pipeline_summary` data without parsing new panel or trend artifacts.

Environment Flag:
```
G6_CYCLE_TABLES_PIPELINE_INTEGRATION=0|1   # When enabled executor records summary for cycle_tables emit hook
```

Behavior:
- After computing the per-cycle `pipeline_summary`, the executor (if flag truthy) calls `record_pipeline_summary(summary)` in `cycle_tables`.
- On later invocation, `emit_cycle_tables(payload)` (still a no-op for tables) injects `payload['pipeline_summary'] = <summary>` when a summary exists.
- If flag disabled or no summary recorded yet, emit leaves payload unchanged.
- Legacy timing and record_* functions remain inert; only summary injection is added.

Public Additions:
- `record_pipeline_summary(summary: dict)` – store shallow copy of latest summary.
- `get_pipeline_summary() -> Optional[dict]` – accessor for tests / diagnostics.

Testing: `tests/test_cycle_tables_integration.py` validates enabled path injection and disabled path non-mutation.

Failure Model:
- All integration guarded by try/except; failures never impact core pipeline.

Future Enhancements:
1. Add optional derived `success_rate` field (currently derivable externally: `(phases_ok == phases_total)` logic per cycle).
2. Emit a structured log line when injection occurs for audit (currently omitted to reduce noise).
3. Soft deprecation path: add warning emission if still enabled after cutoff date.

Deprecation Strategy:
- Flag will default to 0 and may be removed after downstream confirms elimination of old cycle table consumers.
1. Add moving window (e.g. last 10 cycles) sub-aggregate.
2. Include retry statistics (count of phases_with_retries).
3. Provide optional histogram buckets for phases_error distribution.

#### 11.23.0 Pipeline Metrics Expansion (2025-10)

Purpose: Elevate observability from per-phase counters to cycle-level health KPIs, latency distributions, short‑term rolling rates, and long‑horizon trend ingestion without increasing cardinality.

New Metrics:
| Attr | Prom Name | Type | Labels | Description |
|------|-----------|------|--------|-------------|
| pipeline_cycle_success | g6_pipeline_cycle_success | Gauge | (none) | 1 if cycle had zero phase errors else 0 |
| pipeline_cycles_total | g6_pipeline_cycles_total | Counter | (none) | Total cycles that produced a summary |
| pipeline_cycles_success_total | g6_pipeline_cycles_success_total | Counter | (none) | Successful cycles (no phase errors) |
| pipeline_phase_duration_seconds | g6_pipeline_phase_duration_seconds | Histogram | phase,final_outcome | Per-phase execution duration distribution (seconds, attempts aggregated) |
| pipeline_cycle_error_ratio | g6_pipeline_cycle_error_ratio | Gauge | (none) | phases_error / phases_total (0 when denominator zero) |
| pipeline_cycle_success_rate_window | g6_pipeline_cycle_success_rate_window | Gauge | (none) | Rolling success rate over last N cycles |
| pipeline_cycle_error_rate_window | g6_pipeline_cycle_error_rate_window | Gauge | (none) | Rolling error rate over last N cycles |
| pipeline_trends_success_rate | g6_pipeline_trends_success_rate | Gauge | (none) | Long-horizon success_rate from trend aggregation file |
| pipeline_trends_cycles | g6_pipeline_trends_cycles | Gauge | (none) | Total cycles represented in trend aggregation file |

Environment Flags:
```
G6_PIPELINE_ROLLING_WINDOW=N            # Integer >0 enables rolling window gauges with deque(maxlen=N)
G6_PIPELINE_PHASE_DURATION_BUCKETS= "0.01,0.05,0.1,0.25,0.5,1,2.5,5,10"  # (Planned) histogram bucket override (current runtime mutation limited; spec default used)
G6_PIPELINE_TRENDS_METRICS=0|1         # When enabled, read trends file each cycle and set pipeline_trends_* gauges
```

Design Notes:
- Histogram uses seconds to align with existing *_seconds families; we retain ms counter for cumulative arithmetic.
- Runtime bucket override is a documented no-op for now because prometheus_client histograms are immutable post-registration (will require pre-registration parsing in a future refactor).
- Rolling window implemented with attribute on `execute_phases` function to avoid additional module globals; memory bounded by N.
- Trend ingestion is optional, cheap (single JSON read) and tolerant of missing file.
- All metric writes are wrapped in defensive try/except to preserve pipeline resilience.

Edge Cases:
1. phases_total = 0 => error ratio set to 0.0 to avoid divide-by-zero noise.
2. Rolling window size env removed mid-run: existing deque persists; size shrinks only on process restart (acceptable trade-off).
3. Trends file corruption => silently ignored; gauges unchanged.
4. High N rolling window could increase per-cycle cost O(1) still (deque) – safe.
5. Histogram observation failure (rare) suppressed; counter still accurate.

Testing Additions (planned):
- Validate success/error counters after synthetic success + failure cycles.
- Assert rolling window gauges follow expected values for N=3 across 4 cycles (moving rate).
- Observe histogram bucket existence via registry family names (not distribution correctness in unit tests).

Future Enhancements:
1. Pre-registration dynamic bucket parsing (move env parse into spec build path).
2. Add gauge for cumulative retry rate (phases_with_retries / phases_total).
3. Expose moving window for retry rate (triangular window experiment).
4. Add quantile summary alternative if histogram overhead becomes a concern.
5. Consider separate gauge for consecutive success streak length.

Migration / Backward Compatibility:
- No existing metric renamed or removed; additions only.
- Dashboards depending on phase counters unaffected.
- Trend ingestion gauges appear only when flag enabled; default off preventing unexpected catalog shifts for consumers that diff metrics.

4. Potential diff artifact referencing previous hash for quick change classification.

Operational Guidance:
- Keep limit modest to avoid unnecessary JSON size; for long-term analytics rely on external TSDB ingestion if needed.

Performance Considerations:
- JSON write once per cycle; with limit 200 typical file size remains small (<50KB unless extreme error payload sizes occur).

### 11.10.2 CI Enforcement (Planned)
Introduce `scripts/enforce_env_flags.py` to fail builds if new raw boolean parsing patterns are introduced. Allow explicit suppression via `# noqa: G6-LEGACY-FLAG` for the rare intentional case.

#### 11.10.3 Test Reset Helpers for Startup Summaries (2025-10)

To keep the runtime implementation clean while still validating "exactly once" semantics across multiple one‑shot startup summaries in a single process, two private helpers were introduced in `src/observability/startup_summaries.py`:

* `_reset_startup_summaries_state(clear_registry: bool = False)` – Clears internal dispatcher emission bookkeeping (`_EMITTED`, JSON field hash list, composite flag). When `clear_registry` is False (default) existing registered emitters (e.g. `env.deprecations`) remain so tests can force emission without rebuilding import side effects.
* `_force_emit_env_deprecations_summary()` – Invokes the registered `env.deprecations` emitter directly (if present) to guarantee a deterministic structured line even when no deprecated variables are set (count=0 line).

Integration Test Pattern (`tests/test_startup_summaries_integration.py`):
1. Attach a `StreamHandler` to all relevant loggers before importing modules that may emit.
2. Call `_reset_startup_summaries_state()` (preserving registry) and reload key modules to clear their module‑level sentinels.
3. Explicitly delete per‑summary sentinels (`_G6_*_SUMMARY_EMITTED`, `_KITE_PROVIDER_SUMMARY_EMITTED`) and reset singletons (e.g. collector settings) needed to re-trigger emission paths.
4. Instantiate components that emit on construction (e.g. `KiteProvider`) before orchestrator bootstrap if bootstrap might short‑circuit or choose an alternate provider.
5. Run `bootstrap_runtime(...)`, then create a fresh `MetricsRegistry()` (after clearing its sentinel) to capture `metrics.registry.summary`.
6. Force env deprecations summary via `_force_emit_env_deprecations_summary()` and finally call `emit_all_summaries()` for composite hash emission.
7. Assert each structured summary token appears exactly once and that JSON variants (when flags enabled) are present; assert composite hash line.

Why Helpers (instead of ad-hoc hacks in test):
* Keeps test logic declarative and avoids synthesizing fake log lines (which previously risked masking real regressions).
* Avoids tightening production pathways just for testability (no public reset API leaked).
* Maintains ability to extend summaries without editing the integration test beyond adding a new token to the assertion list.

Usage Constraints:
* Never call these helpers in production code paths (they are underscored and excluded from public surface) – they intentionally mutate internal state.
* If a future summary requires expensive construction to re-emit, prefer factoring the emitter into an idempotent callable rather than extending the helpers.
* If a summary’s sentinel logic changes, update the integration test sentinel clearing block accordingly.

Potential Future Hardening:
* Add a dispatcher integrity assertion helper that returns (registered, emitted, missing) counts for quick test diagnostics.
* Provide a fixture in `tests/conftest.py` wrapping the reset + reload sequence to reduce boilerplate if additional integration tests are added.

### 11.11 Provider Modularization Wave (Phase A7 Step 1 – 2025-10)

The first step of the provider modular split extracted the instruments fetch + cache logic from `src/broker/kite_provider.py` into a dedicated module:

`src/broker/kite/instruments.py` – exposes `fetch_instruments(provider, exchange, force_refresh=False)`.

Rationale:
1. Shrink monolithic facade (reduces future diff noise; improves navigability).
2. Isolate retry / TTL heuristics to enable later experimentation (e.g. adaptive TTL, structured error codes) without touching unrelated quote / expiry code.
3. Provide a clearer seam for multi‑provider abstraction (future: generic interface so alternative providers can plug in their own instruments module).

Behavior Parity Guarantees (Step 1):
* Public method signature `KiteProvider.get_instruments(exchange=None, force_refresh=False)` unchanged.
* Caching semantics preserved (short TTL override on empty list, one‑shot immediate retry on first empty fetch).
* Auth / generic failure path still returns empty list and sets `_used_fallback` flag; no synthetic instrument fabrication introduced.
* Logging tokens preserved (e.g. `instrument_fetch_returned_empty_list`, `empty_retry_success`, `empty_instruments_cache_short_ttl`).

Follow‑Up Opportunities (Later Steps):
* Introduce structured event emission (instead of ad-hoc warnings) for empty / auth failure paths.
* Add metrics: `provider_instruments_fetch_seconds`, `provider_instruments_retry_count` gated by concise logging flag.
* Generalize module to `provider_core/instruments.py` once second provider implementation exists.
* Inject dependency on an abstract rate limiter protocol (decouple from concrete attribute `_api_rl`).

Migration Notes:
* Downstream code importing or monkeypatching `KiteProvider.get_instruments` sees no change; internal call now delegates.
* Tests referencing cache internals unaffected (state objects remain on provider instance).
* Future removal of direct attribute access will be documented separately under deprecations once diagnostics coverage widens.

### 11.12 Provider Modularization Wave (Phase A7 Step 2 – 2025-10)

Extracted expiry discovery + ATM strike logic from `kite_provider` into `src/broker/kite/expiry_discovery.py`:
* `get_atm_strike(provider, index_symbol)`
* `get_expiry_dates(provider, index_symbol)`
* `get_weekly_expiries(provider, index_symbol)`
* `get_monthly_expiries(provider, index_symbol)`

Goals:
1. Further shrink facade surface (expiry + instruments were the two largest logic blocks).
2. Enable future multi-provider shared expiry strategy (fabrication fallback + extraction heuristics) with minimal duplication.
3. Prepare for potential structured event emission and metrics around expiry fabrication without touching facade.

Parity Guarantees (Step 2):
* Exact fabrication fallback preserved (two Thursdays) when instrument universe present but no expiries extracted.
* Auth failure path still sets `_auth_failed` and returns 14-day synthetic expiry.
* Empty instrument universe warning token unchanged (`empty_instrument_universe_no_expiries`).
* Monthly and weekly derivations unchanged (first two for weekly, last-in-month per month for monthly).
* ATM strike heuristic unchanged (step=100 if price>20000 else 50; default table).

Testing:
* Existing skeleton and symbol filtering/matching tests pass unchanged (validated after extraction).
* No new tests added yet; future step may add direct unit tests for fabricated path using injected instrument slices.

Follow‑Up Candidates:
* Emit structured event `expiry.fabricated` with fields (index, this_week, next_week, instrument_count).
* Cache invalidation TTLs for expiries (currently unlimited until process restart) – consider adding an env/config TTL.
* Integrate ATM strike with optional intra-cycle caching to reduce LTP calls when many expiries requested in rapid succession.

### 11.13 Provider Modularization Wave (Phase A7 Step 3 – 2025-10)

Diagnostics & Health extraction into `src/broker/kite/diagnostics.py`:
* `provider_diagnostics(provider)` – unchanged key set: option_cache_size, instruments_cached, expiry_dates_cached, synthetic_quotes_used, last_quotes_synthetic, used_instrument_fallback, token_age_sec, token_time_to_expiry_sec.
* `check_health(provider)` – identical healthy/degraded/unhealthy determination (price>0 heuristic, auth token error classification).

Motivation:
1. Reduce facade bloat and isolate passive observation logic from active orchestration logic.
2. Simplify future migration to a generic provider interface where diagnostics gatherers can be provider-agnostic utilities.
3. Provide a single import point for monitoring tools without pulling in full provider dependencies.

Parity Notes:
* No change in deprecation behavior for property shims (warnings still emitted first access via facade properties).
* Exceptions still return empty diagnostics dict or unhealthy status; test expectations unchanged.
* Token age/expiry introspection remains best-effort and silently falls back to None values on attribute absence.

Future Enhancements:
* Structured event emission (`provider.diagnostics.snapshot`) with delta detection for noisy fields.
* Optional metrics registration: provider_diagnostics_count, provider_health_status gauge.
* Pluggable health strategies (e.g., include instrument fetch freshness, last successful quote timestamp).

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

### 17.6 Centralized Provider Configuration (ProviderConfig)

The provider credential & mode discovery logic is centralized in `src/provider/config.py` via the immutable `ProviderConfig` dataclass. This replaces scattered environment probing (`os.environ.get('KITE_API_KEY')`, etc.) across broker/auth layers.

Goals:
1. Single source of truth snapshot
2. Safe late completion (API key present first, access token later)
3. Explicit refresh semantics (no silent mutation underneath consumers)
4. Easier logging/redaction & future secret backend integration

Core API:
- `get_provider_config(refresh: bool = False) -> ProviderConfig`
	Returns cached snapshot; with `refresh=True` re-discovers env and updates singleton if changed.
- `update_provider_credentials(api_key: str | None = None, access_token: str | None = None) -> ProviderConfig`
	Overlays provided values over current snapshot (or fresh discovery) producing a new immutable instance.

Snapshot Fields:
- `api_key`, `access_token` (Optional[str])
- `discovered: bool` (any credential material found)
- `complete: bool` (both present)
- `source: str` ("env" | "updated")
- `timestamp: float` (creation epoch seconds)

Usage Pattern:
```python
from src.provider.config import get_provider_config, update_provider_credentials
from src.broker.kite_provider import KiteProvider

cfg = get_provider_config()
if not cfg.complete:
		# Acquire access token somehow (interactive / script)
		cfg = update_provider_credentials(access_token=new_token)

provider = KiteProvider.from_provider_config(cfg)
```

Migration Guidelines:
1. Replace `KiteProvider.from_env()` call sites with the pattern above.
2. For paths obtaining fresh tokens, call `update_provider_credentials` then re-bind the snapshot.
3. Remove direct `os.environ.get('KITE_...')` usages outside `config.py`.
4. Tests mutating env should invoke `get_provider_config(refresh=True)` after setting variables.

Late Completion Semantics:
- Existing snapshot remains valid for in-flight operations; new snapshot opt-in only.
- Idempotent updates (same values) still yield a new timestamp allowing monotonic versioning.

Edge Cases:
- No credentials: snapshot has `discovered=False`; downstream may trigger auth flow.
- Rotated API key: external rotation requires `refresh=True` or explicit `update_provider_credentials(api_key=...)`.

Future Enhancements:
- Multi-provider registry (list keyed by provider id)
- Secret manager backends (Vault/AWS Secrets) layered under discovery
- Expiration metadata + auto-refresh hooks

Tests:
- `tests/test_provider_config.py` covers alias resolution, update layering, late completion.

Action Items:
- Migrate remaining legacy `from_env()` references (tracked in backlog)
- Add structured log redaction helper for masked token preview

Security Note: Never log raw tokens; derive masked forms (e.g., first 4 + '***').

Deprecation Update (2025-10-07):
Legacy implicit environment fallback inside `KiteProvider` has been removed. The class no longer reads `KITE_API_KEY` / `KITE_ACCESS_TOKEN` directly; all credential sourcing flows through `ProviderConfig`. The `from_env()` classmethod is now a thin compatibility shim that retrieves the current snapshot and emits a deprecation warning. External scripts must migrate to:
```python
from src.provider.config import get_provider_config
from src.broker.kite_provider import KiteProvider
prov = KiteProvider.from_provider_config(get_provider_config())
```
This guarantees consistent rotation and eliminates divergent discovery semantics.

Convenience Helper (2025-10-07):
To streamline adoption and suppress constructor credential deprecation warnings in standard code paths, a `kite_provider_factory(**overrides)` helper was introduced. It applies optional overrides (e.g., `api_key=...`, `access_token=...`) via `ProviderConfig.with_updates()` and then constructs the provider through `from_provider_config`, ensuring warning-free instantiation for normal runtime/test usage.

Example:
```python
from src.broker.kite_provider import kite_provider_factory
provider = kite_provider_factory()                 # uses current snapshot
provider2 = kite_provider_factory(access_token=tok)  # overlay new token
```
Prefer this helper (or `from_provider_config`) over passing credentials directly into `KiteProvider(...)` to avoid deprecation churn and to ensure future secret backend integrations remain transparent.

Warning Suppression & Behavior Notes (2025-10-07):
* Direct constructor with credentials => emits `DEPRECATION_MSG_DIRECT_CREDENTIALS` (centralized constant in `kite_provider.py`).
* `KiteProvider.from_env()` => emits `DEPRECATION_MSG_FROM_ENV`.
* `create_provider('kite', {})` with only env credentials => emits `DEPRECATION_MSG_FACTORY_IMPLICIT`.
* `kite_provider_factory()` (no overrides) with env-discovered complete credentials => emits `DEPRECATION_MSG_IMPLICIT_ENV_HELPER` one time.
* `kite_provider_factory(api_key=..., access_token=...)` => no deprecation warnings (preferred pattern in tests & runtime).

Migration Recommendation:
Adopt `kite_provider_factory` with explicit overrides during transitional periods to silence warnings once credential sourcing is verified. Leave at least one test exercising each deprecation path so removal timing can be evaluated confidently.

