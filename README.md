<!--
  CANONICAL README
  This unified README consolidates content previously spread across:
    * README.md (original core overview)
  * (Former variants removed: README_COMPREHENSIVE.md, README_CONSOLIDATED_DRAFT.md, README_web_dashboard.md – unified here)
    * scripts/README.md (init menu & simulator quick start)
  The auxiliary README_* files are now archival stubs and will be removed after one stable release window (R+1) unless external references require a longer grace period.
-->

# G6 Platform

High‑throughput, modular options market data collection & analytics platform for Indian indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, …). It performs minute‑level (configurable) collection cycles, computes derived analytics (IV, Greeks, PCR, breadth), writes durable snapshots (CSV + optional InfluxDB), and exposes rich observability (Prometheus metrics, summary panels, JSON status manifests).

## 1. Key Value Propositions
- Deterministic, market‑hour gated collection cycles
- Unified orchestrator (providers, collectors, metrics, health) with graceful shutdown & resilience patterns
- Backwards additive storage evolution (CSV + Influx)
- In‑process analytics (Newton‑Raphson IV solver, Black‑Scholes Greeks) with feature gating
- Aggregated per‑index overview snapshot (PCR + expiry completeness masks) every cycle
- Extensible, group‑gated Prometheus metrics & integrity‑verified panel artifacts

## 2. Quick Start
```powershell
# (Optional) create & activate venv
python -m venv .venv
./.venv/Scripts/Activate.ps1
pip install -r requirements.txt

# Run orchestrator in mock mode (safe, no external API)
$env:G6_USE_MOCK_PROVIDER='1'
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 30 --cycles 2

# Launch summary (Rich if available, falls back to plain)
python scripts/summary_view.py --refresh 1

# Simulator + summary demo (panels auto-managed)
python scripts/status_simulator.py --status-file data/runtime_status_demo.json --indices NIFTY,BANKNIFTY,FINNIFTY,SENSEX --interval 60 --refresh 0.1 --open-market --with-analytics --cycles 1
python scripts/summary_view.py --refresh 0.5 --status-file data/runtime_status_demo.json
```

VS Code Tasks (recommended):
* `Smoke: Start Simulator` → background status generation
* `Smoke: Start Panels Bridge` (legacy compatibility; panels now usually in‑process) 
* `Smoke: Summary (panels mode)` → interactive summary
* `G6: Init Menu` → interactive configuration & launch helper

## 3. Architecture Snapshot
| Layer | Path(s) | Responsibilities |
|-------|---------|------------------|
| Entry / Orchestration | `src/unified_main.py` | Bootstrap, feature toggles, graceful loop |
| Collectors | `src/collectors/unified_collectors.py` | Per‑cycle orchestration, optional snapshot build |
| Providers Facade | `src/collectors/providers_interface.py`, `src/broker/kite_provider.py` | Expiry & instrument resolution, quotes |
| Analytics | `src/analytics/option_greeks.py`, `src/analytics/option_chain.py` | IV estimation, Greeks, PCR, breadth |
| Storage | `src/storage/csv_sink.py`, `src/storage/influx_sink.py` | Persistent per‑option & overview writes |
| Metrics | `src/metrics/metrics.py` | Registration, grouped gating, metadata dump |
| Panels & Summary | `scripts/summary_view.py`, `src/panels/*` | Real‑time textual panels & JSON artifact emission |
| Panel Integrity | `src/panels/validate.py` | Manifest hash verification & schema validation |
| Health & Resilience | `src/health/*`, `src/utils/*` | Circuit breakers, retries, memory pressure, symbol hygiene |
| Token / Auth | `src/tools/token_manager.py`, `src/tools/token_providers/*` | Provider token acquisition (headless & interactive) |
| Config & Docs Governance | `src/config/*`, tests in `tests/` | Schema validation, doc coverage enforcement |

### 3.1 Module & Workflow Status Matrix
Legend: [C] Completed & stable  |  [P] Planned / design accepted  |  [IP] In Progress / partial refactor  |  [E] Experimental (behind flag)  |  [D] Deprecated (pending removal)

| Domain | Key Paths (Representative) | Purpose / Workflow Role | Current Status | Notes / Next Steps |
|--------|---------------------------|-------------------------|----------------|--------------------|
| Orchestrator | `unified_main.py`, `orchestrator/` | Bootstrap, interval loop, graceful shutdown, feature flag wiring | [C] | Heartbeat & rate-limit stats recently added; monitor for noise tuning |
| Collectors Core | `collectors/unified_collectors.py`, `collectors/pipeline.py` | Per-index cycle coordination, invoke providers, analytics, persistence | [C] | Future: fine-grained concurrency controls (P) |
| Collector Modules | `collectors/modules/*.py` | Strike depth calc, aggregation, synthetic fallbacks, status finalization | [C] | Evaluate adaptive strike window (P) |
| Providers Facade | `collectors/providers_interface.py`, `providers/` | Abstract live / mock provider, expiry + instrument resolution | [IP] | Multi-provider fallback design drafted; implementation pending |
| Token Management | `tools/token_manager.py`, `tools/token_providers/*` | Acquire / validate auth tokens (kite, fake) | [C] | Add secret sanitization (P) |
| Analytics (Greeks/IV) | `analytics/option_greeks.py`, `analytics/iv_solver.py` | Newton-Raphson IV, Greeks, PCR, breadth | [C] | Vol surface interpolation (P); risk aggregation (E) |
| Adaptive / Cardinality | `adaptive/`, `metrics/cardinality_manager.py` | Dynamic emission gating & adaptive detail modes | [IP] | Additional feedback loops & band window tuning (P) |
| Storage CSV | `storage/csv_sink.py` | Durable per-option & overview rows | [C] | Retention / pruning engine (P) |
| Storage Influx | `storage/influx_sink.py` | Optional time-series writes | [C] | Evaluate migration to client batching (P) |
| Panels Writer & Summary | `panels/`, `scripts/summary_view.py`, `summary/` | Real-time textual + JSON panels emission | [C] | Per-index enrichment additions (P) |
| Panel Integrity | `panels/validate.py`, `panels/integrity_monitor.py` | Hash manifest, integrity verification loop | [C] | Consider checksum streaming API (P) |
| Metrics Facade | `metrics/__init__.py`, `metrics/metrics.py` | Registry acquisition, grouped registration, placeholders | [IP] | Continued modular extraction (Phase 3.x) |
| Metrics Group Registry | `metrics/group_registry.py`, `metrics/placeholders.py` | Controlled families, always-on safety sets | [C] | Monitor for alias deprecation removals (D: `perf_cache` soon) |
| Resilience Utilities | `utils/resilience.py`, `utils/circuit_breaker.py` | Retry/backoff, circuit breaking | [C] | Jitter parameterization exposure (P) |
| Rate Limiter & Batching | `utils/rate_limiter.py`, `collectors/helpers/` | Token bucket, micro-batching, quote cache | [C] | Telemetry tuning if provider limits shift |
| Health Checks | `health/health_checker.py` | Component readiness & liveness registry | [C] | Expand with latency percentiles (P) |
| Data Quality Filters | `utils/data_quality.py` | Sanitize abnormal quotes / OI | [C] | Add statistical anomaly detection (P) |
| Symbol Hygiene | `utils/symbol_root.py` | Root / strict matching gating | [C] | Remove legacy matching mode when usage < threshold (D planned) |
| Config Schema & Docs | `config/`, `schema/`, tests | JSON schema v2, doc coverage enforcement | [C] | Evaluate schema v3 (P) |
| Governance Tests | `tests/` (env & config coverage, timing guard) | Prevent drift & performance regression | [C] | Add placeholder metrics order regression (C) |
| Logging Enhancements | `utils/output.py`, structured event formatters | Colorization, suppression, human struct events | [C] | Evaluate JSON lines audit sink (P) |
| Web (Legacy) | `web/` | Deprecated FastAPI dashboard | [D] | Removal target R+1 unless blockers |
| Archived Artifacts | `archived/`, `archive/` | Historical snapshots, retired modules | [C] | Periodic pruning script (P) |
| Security / Supply Chain | `scripts/gen_sbom.py`, `scripts/pip_audit_gate.py` | SBOM + dependency audit | [C] | Automated PR gating (P) |
| Automation / CI | `.github/workflows/auto-maintenance.yml` | Docs regeneration, dependency scans (main only) | [C] | Add lint & type gates (P) |
| Roadmap Tracking | `WAVE*_TRACKING.md` | Phased feature tracking | [C] | Consolidate into issue tracker (P) |

Status Rationale Snapshots:
- Providers Facade [IP]: groundwork for multi-provider orchestrator present; failover logic not integrated.
- Metrics Facade [IP]: modular extraction mid-way; deep imports still supported (shim) until completion.
- Adaptive / Cardinality [IP]: Band rejection & placeholder counters live; advanced feedback heuristics pending.
- Web (Legacy) [D]: Replaced by panels + Grafana; retained for short-term reference only.

Planned (P) High-Impact Upcoming Items (see Section 14 Roadmap also): retention/pruning engine, multi-provider fallback, vol surface interpolation, expiry calendar service, schema v3, lint/type CI gates.

Experimental (E) surfaces remain behind environment flags and are intentionally excluded from strict governance tests to allow iteration without churn.

## 4. Collection Cycle Flow
```
[Start]
  -> Market hours check
  -> For each enabled index:
        Resolve expiries
        Build strike universe (ATM ± depth)
        Fetch & sanitize quotes
        (Optional) Estimate IV & compute Greeks
        Persist per‑option rows (CSV / Influx)
        Aggregate PCR + masks → overview row
        Update per‑index metrics
  -> Global metrics + summary panels refresh
  -> Sleep until next interval (or exit if run-once)
[Repeat]
```

### CSV Output Migration (2025‑09)
Primary path: `data/g6_data` (override via `G6_CSV_BASE_DIR`). Legacy `data/csv` remains for historical artifacts; migrate downstream consumers.

## 5. Overview Snapshot Structure
Per index per cycle capturing PCR per expiry bucket (`this_week`, `next_week`, `this_month`, `next_month`), expected/collected counts & masks (`expected_mask`, `collected_mask`, `missing_mask`), and `day_width`.

## 6. Configuration & Governance
Primary file: `config/g6_config.json` validated against `config/schema_v2.json`.

Example excerpt:
```json
{
  "greeks": {"enabled": true, "estimate_iv": true, "iv_max": 3.0, "iv_precision": 1e-5},
  "index_params": {"NIFTY": {"expiries": ["this_week","next_week"], "strikes_otm": 10, "strikes_itm": 10, "enable": true}},
  "collection": {"interval_seconds": 60}
}
```

### 6.1 Environment Variable Governance
All `G6_` variables referenced in code must be documented in `docs/env_dict.md`.
Automation:
* Test: `tests/test_env_doc_coverage.py`
* CI strict: set `G6_ENV_DOC_STRICT=1`
* Baseline must remain empty; regenerate (if ever needed) via `G6_WRITE_ENV_DOC_BASELINE=1` (exceptional)

Flags:
| Flag | Purpose |
|------|---------|
| `G6_SKIP_ENV_DOC_VALIDATION=1` | Temporary local skip (avoid in CI) |
| `G6_WRITE_ENV_DOC_BASELINE=1` | Rebuild baseline (should stay unused) |
| `G6_ENV_DOC_STRICT=1` | Fail if baseline not empty |

Guidelines:
1. Document new vars in the same PR.
2. Prefer config keys for structured/long‑lived settings.
3. Remove deprecated aliases post window (tracked in docs table).
4. Keep descriptions action‑oriented.

Related: `docs/env_dict.md`, `docs/CONFIG_FEATURE_TOGGLES.md`, `docs/ENVIRONMENT.md`.

### 6.2 Config Key Governance
* Test: `tests/test_config_doc_coverage.py`
* Schema sync: `tests/test_config_schema_doc_sync.py`
* Strict flags analogous to env governance (`G6_CONFIG_DOC_STRICT`, etc.)

### 6.3 Greeks Config Keys
| Key | Meaning | Default |
|-----|---------|---------|
| enabled | Compute Greeks locally | false |
| estimate_iv | Estimate IV when missing | false |
| risk_free_rate | Annual risk‑free rate | 0.05 |
| iv_max_iterations | Newton iteration cap | 100 |
| iv_min | IV lower bound | 0.01 |
| iv_max | IV upper bound | 5.0 |
| iv_precision | Price diff tolerance | 1e-5 |

### 6.4 Feature Toggles & Symbol Matching
Symbol contamination protection enforced via strict root matching (`src/utils/symbol_root.py`).
Environment `G6_SYMBOL_MATCH_MODE`: `strict` (default) | `prefix` | `legacy` (fallback only).
Additional runtime flags centralised in `RuntimeFlags` (e.g., `G6_SYMBOL_MATCH_SAFEMODE`, fallback expiry toggles, tracing flags).

### 6.5 Data Retention Policy
Infinite retention (no auto pruning) by design; see `docs/RETENTION_POLICY.md` for rationale & possible future compression/archival strategies.

## 7. Metrics & Observability
Prometheus exporter embedded. Metrics grouped & gated to control cardinality.

### 7.0 Metrics Modularization Facade (2025-10)
The historical monolithic `src/metrics/metrics.py` has begun phased extraction into smaller focused modules while preserving backward compatibility. A lightweight facade in `src/metrics/__init__.py` now exposes the stable public API:

Preferred imports:
```python
from src.metrics import (
  MetricsRegistry,          # registry class
  setup_metrics_server,     # start HTTP exporter (idempotent)
  get_metrics_singleton,    # acquire existing singleton (legacy helper)
  get_metrics,              # alias for registry acquisition (back compat)
  register_build_info,      # register build metadata gauge
  get_metrics_metadata,     # snapshot of groups / counts (legacy accessor)
)
```

Modularized components (internal but increasingly self‑contained):
| Module | Responsibility |
|--------|----------------|
| `registry.py` | Thin helpers to obtain / manage a registry instance |
| `groups.py` | Group filter parsing & enable/disable evaluation |
| `metadata.py` | `reload_group_filters` & `dump_metrics_metadata` free functions |
| `greek_metrics.py` | Greek / IV specific counters & gauges (extracted logic) |
| `server.py` | HTTP exporter bootstrap logic |
| `registration.py` | Generic safe registration helpers (idempotent wrappers) |

Backward Compatibility Policy:
1. Existing deep imports of `src.metrics.metrics` continue to function (shimmed exports maintained).
2. Public facade (`src.metrics` package) is the stable path moving forward; new code should prefer it.
3. Legacy helpers (`get_metrics`, `get_metrics_singleton`, `register_build_info`) retained until at least one full release window after full modularization completion.

Build Metadata Injection:
`register_build_info(version=..., git_commit=..., config_hash=...)` registers a single-sample gauge `g6_build_info` with labels (`version`, `git_commit`, `config_hash`, `build_time`). Re‑invoking with different values updates (not duplicates) the same sample by clearing internal state before relabeling (idempotent). Environment shortcuts:
| Env Var | Description |
|---------|-------------|
| `G6_BUILD_VERSION` | Optional semantic / CI build version string |
| `G6_BUILD_COMMIT` | Git commit (short or full) injected at startup |
| `G6_BUILD_TIME` | Build timestamp (UTC ISO or epoch); fallback: runtime now |

Group Gating Recap (now powered by `metadata.reload_group_filters`): enable / disable sets are reloaded on metadata dump to provide an up‑to‑date filtered snapshot without requiring full process restart when toggling via environment in test contexts.

Synthetic Group Supplementation: When no explicit enable list is provided, representative metrics for certain groups (e.g. `panel_diff`, `provider_failover`, `analytics_vol_surface`) are synthesized in metadata output if absent, aiding governance tests that assert group presence without forcing all groups on in runtime.

Future Direction (tracked in CHANGELOG “Unreleased”): incremental extraction of registration helpers & per‑domain metric families out of the monolith, followed by optional strict facade enforcement (warnings on deep imports) once test surface reaches parity.

Phase 3 (Unreleased) Enhancements:
- Group registry (`src/metrics/group_registry.py`) now owns all controlled metric family registrations through a unified `_maybe_register` shim aware of group gating and alias mapping.
- Always‑on placeholders (`src/metrics/placeholders.py`) register a minimal, safety‑critical metric set early (expiry remediation, provider failover, SLA health, IV iteration histogram, risk aggregation, panel diff counters, adaptive band rejection) so tests / operations never observe their absence due to gating order or partial failures.
- `ALWAYS_ON_GROUPS`: `expiry_remediation`, `provider_failover`, `adaptive_controller`, `iv_estimation`, `sla_health` bypass pruning in `_apply_group_filters` guaranteeing contract metrics remain visible even under restrictive enable lists.
- New counter `g6_option_detail_band_rejections_total` tracks adaptive detail mode band window rejections (label: `index`). Emitted even when broader cardinality manager feature flags remain off—adaptive gating is considered a core resiliency signal.
- Group alias: spec group `perf_cache` maps internally to `cache` avoiding duplicate collectors while satisfying specification naming.
- Spec fallback: defensive block re‑registers root cache & panels integrity metrics if earlier grouped registration fails (e.g., due to transient import error) ensuring spec conformance tests remain green.
- `_core_maybe_register` now forwards arbitrary constructor kwargs (e.g. histogram `buckets`), eliminating silent omission of histogram metrics under previous fixed signature.
 - New gauge `g6_provider_mode` (label: `mode`) indicates active provider orchestration mode (e.g. `pipeline`, `legacy`, `mixed`). One-hot: only the current mode sample is 1; others 0. Update via `metrics.set_provider_mode(value)` after mode determination.
 - Counter `g6_config_deprecated_keys_total` (label: `key`) increments once per deprecated/legacy config key encountered during validation, enabling observability of residual configuration debt.
 - SSE client resilience: exponential backoff with jitter plus metrics `g6_sse_reconnects_total{reason}` and histogram `g6_sse_backoff_seconds` for reconnect behavior analysis.
 - Deprecated env vars `G6_SUMMARY_PANELS_MODE` / `G6_SUMMARY_READ_PANELS` fully removed (panels mode auto-detect only). Remove from any automation scripts.
 - Group alias `perf_cache` deprecated (maps to `cache` this release; scheduled removal next) – update dashboards to reference `cache`.

Phase 3.1 (Refactor) Updates:
- Extracted spec fallback logic into `_ensure_spec_minimum()` for clarity & future extension.
- Added regression guard test ensuring placeholder metrics exist immediately after registry instantiation (`test_metrics_placeholders_order.py`).
- Promoted `ALWAYS_ON_GROUPS` to module-level constant with rationale; simplifies documentation & introspection.
- Consolidated group alias handling via internal `_resolve_group()` helper.
- Standardized `g6_metric_group_state` to labeled gauge (`group=<name>`). Older unlabeled instantiation path removed (backward compatible for existing processes until restart).

Operational Guidance:
| Scenario | Symptom | Resolution |
|----------|---------|-----------|
| Band rejection counter missing | Attribute `option_detail_band_rejections` absent | Ensure facade import (`from src.metrics import get_metrics`) executed at least once; counter is placeholder (should always be present). |
| IV iterations histogram absent | `g6_iv_iterations_histogram` not exposed | Confirm `G6_ESTIMATE_IV=1`; histogram lives in placeholders (thus present) but only populated when IV solver runs. |
| Root cache / panels integrity metrics missing | Spec test failures listing cache/panels names | Indicates early group import failure; fallback block should have created them—check logs for `group_registry invocation failed`. |
| Always‑on metric unexpectedly pruned | Missing even with no env filters | Regression; verify `_always_on_groups` includes its group and open an issue. |

Adding New Critical Metrics:
1. Choose a group (add to `CONTROLLED_GROUPS` if new domain).
2. If mission‑critical for governance tests or operational safety, register via placeholders and (optionally) add its group to `ALWAYS_ON_GROUPS`.
3. Use `_maybe_register(group, attr, cls, name, help, labels, **kwargs)` inside group registry for standard families.

Band Rejection Flow (Adaptive Detail Mode):
1. Adaptive controller sets `_adaptive_current_mode` on metrics singleton (0=full,1=band,2=aggregate).
2. `CardinalityManager.should_emit` consults config/env for `band_window` or `G6_DETAIL_MODE_BAND_ATM_WINDOW`.
3. Out‑of‑band strike → reject path increments `option_detail_band_rejections` and returns False; callers skip per‑option emission.

Why Placeholders? They eliminate race conditions where a test (or early runtime path) queries a metric before grouped registration completes, reducing flakiness and accidental spec regressions during refactors.

Key metrics (sampling):
| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| g6_iv_estimation_success_total | Counter | index, expiry | Successful IV solves |
| g6_iv_estimation_failure_total | Counter | index, expiry | Failures / aborts |
| g6_root_cache_hit_ratio | Gauge | (none) | 0–1 hit ratio |
| g6_panels_integrity_ok | Gauge | (none) | 1 = all panel hashes match manifest |

Metric Group Gating:
| Env Var | Behavior |
|---------|----------|
| `G6_ENABLE_METRIC_GROUPS` | Whitelist groups (exclusive) |
| `G6_DISABLE_METRIC_GROUPS` | Blacklist after whitelist filtering |
| `G6_VOL_SURFACE` / `G6_VOL_SURFACE_PER_EXPIRY` | Enable extended vol surface families |
| `G6_RISK_AGG` | Enable risk aggregation family |
| `G6_ESTIMATE_IV` | Enable IV iteration histogram |
| `G6_METRICS_STRICT_EXCEPTIONS` | Fail fast on unexpected metric registration errors (default off) |

Precedence: whitelist → blacklist → feature flags.

Troubleshooting Samples:
| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Missing panel diff metrics | Group not enabled | Adjust enable/disable lists |
| `risk_agg_rows` absent | Strict whitelist excludes or flag off | Add group or clear whitelist |
| Vol surface metrics missing | Flag not set | `G6_VOL_SURFACE=1` |

Strict Metrics Mode:
`G6_METRICS_STRICT_EXCEPTIONS=1` (truthy variants: 1,true,yes,on) causes unexpected exceptions during metric construction
in placeholders, spec minimum assurance, or `_maybe_register` to be re-raised instead of silently logged.
Use this in CI or during refactors to surface latent issues earlier. Production default should remain non-strict for
resilience (transient client library edge cases or partial registry duplication will be tolerated and logged).

### 7.1 Panels & Integrity
Panel writer emits JSON panels + `manifest.json` with SHA‑256 hashes (data section only). Integrity monitor (opt‑in) periodically verifies hashes.
Environment:
| Var | Purpose |
|-----|---------|
| `G6_PANELS_INTEGRITY_MONITOR` | Enable monitor thread |
| `G6_PANELS_INTEGRITY_INTERVAL` | Seconds between sweeps (≥5) |
| `G6_PANELS_INTEGRITY_STRICT` | Fail fast on mismatch |

Panel Schema Validation (`G6_PANELS_VALIDATE`): `off` | `warn` (default) | `strict`.

Manifest Hash Rationale: detect corruption / partial writes while excluding timestamp churn.

### 7.2 Metrics Glossary (Auto‑Generated)
<!-- METRICS_GLOSSARY_START -->
### Metrics Glossary (Auto-Generated)
_The section below is managed by `scripts/gen_metrics_glossary.py`. Do not edit manually._

_No metric annotations found._
<!-- METRICS_GLOSSARY_END -->

### 7.3 Observability Surfaces
1. Summary dashboard (`scripts/summary_view.py` Rich / plain)
2. Panels JSON artifacts (consumable by lightweight UI or tests)
3. Grafana dashboards over Prometheus metrics (`grafana/` JSON)
4. (Deprecated) Standalone FastAPI web dashboard → replaced by above; remaining code is legacy and subject to removal.

## 8. Storage & Schema Evolution
Principles: additive columns, distinct measurements (`option_data`, `options_overview`), bitmask completeness, stable naming (`ce_` / `pe_` prefixes). CSV partitioning: `<base>/<INDEX>/<EXPIRY_KEY>/<STRIKE_BUCKET>/<DATE>.csv`.

## 9. Resilience & Error Handling
| Pattern | Location | Purpose |
|---------|----------|---------|
| Retry + backoff | `src/utils/resilience.py` | Transient upstream tolerance |
| Circuit breaker | `src/utils/circuit_breaker.py` | Prevent hammering failing provider |
| Memory pressure scaling | `src/utils/memory_pressure.py` | Drop high-cardinality load |
| Data quality validation | `src/utils/data_quality.py` | Filter anomalous quotes |
| Health checks registry | `src/health/health_checker.py` | Component readiness |

## 10. Operational Modes
| Mode | Command | Use Case |
|------|---------|---------|
| Continuous | `run_orchestrator_loop.py --interval 60` | Production collection |
| Single Cycle | `--run-once` | Smoke / diagnostics |
| Analytics Only | Enable `features.analytics_startup` | Snapshot analytics without loop |

## 11. Tokens & Auth
Provider abstraction: `src/tools/token_providers/` (`kite`, `fake`). Headless mode via `G6_TOKEN_HEADLESS=1`.
| Var | Purpose |
|-----|---------|
| `KITE_API_KEY` / `KITE_API_SECRET` | Credentials |
| `KITE_ACCESS_TOKEN` | Persisted token |
| `KITE_REQUEST_TOKEN` | One‑time for headless kite flow |
| `G6_TOKEN_PROVIDER` | `kite` | `fake` |
| `G6_TOKEN_HEADLESS` | Force headless mode |

Fast‑exit behavior for non‑interactive/headless paths ensures deterministic CI.

## 12. Testing & Coverage
Run suite:
```powershell
pytest -q
```
Coverage gate (starter): `fail_under=50`. Improve gradually; raise threshold only after sustained uplift.

Selective test example:
```powershell
pytest tests/test_token_providers.py::test_fake_provider_headless
```

Timing Guard: Autouse fixture enforces soft (~5s warning) & hard (~30s fail) per‑test budgets unless marked with `@pytest.mark.allow_long`.

## 13. Deprecations & Cleanup
Active & historical entries in `DEPRECATIONS.md`. Suppress runtime warnings (migration only) via `G6_SUPPRESS_DEPRECATIONS=1`.
Recently Removed Scripts: `run_live.py`, `terminal_dashboard.py`, `panel_updater.py`.
Deprecated Launcher Shim: `start_live_dashboard_v2.ps1` → canonical `scripts/start_live_dashboard.ps1`.

## 14. Roadmap (Excerpt)
| Priority | Item | Rationale |
|----------|------|-----------|
| High | Live panel per-index enrichment | Close minor observability gap |
| High | Retention / pruning strategy | Disk growth management |
| High | Robust expiry calendar service | Holidays / special expiries |
| Medium | Vol surface interpolation | Advanced analytics |
| Medium | Alert pack (Prom alerts) | Faster ops readiness |
| Low | Multi-provider fallback | Resilience |

## 15. Known Limitations
* No automated retention / compaction yet
* Live panel lacks some per‑index enrichments
* Extended vol surface analytics off by default (cardinality cost)
* Web dashboard deprecated (legacy code retained briefly)

## 16. Onboarding a New Index
1. Add entry in `index_params` (expiries + strike depth + enable)
2. Verify symbol root mapping logic covers it
3. Run `--run-once` smoke
4. Confirm overview row & PCR populate
5. Add to Grafana dashboard variable(s)

## 17. Security & Supply Chain
* Tokens excluded by `.gitignore`
* SBOM: `scripts/gen_sbom.py`
* Dependency audit: `scripts/pip_audit_gate.py`
* Avoid logging secrets (sanitization planned for expanded patterns)

## 17.1 Retention Scan (Pre-Retention Engine Tool)
`g6 retention-scan` provides a lightweight on-demand snapshot of CSV storage footprint before a formal pruning/retention service is implemented.

Outputs (text mode): total files, aggregate size (MB), oldest/newest file timestamps, count of distinct index subdirectories.

JSON mode:
```
g6 retention-scan --json
{
  "csv_dir": "data/g6_data",
  "total_files": 1234,
  "total_size_mb": 456.789,
  "oldest_file_utc": "2025-09-15T09:15:00",
  "newest_file_utc": "2025-10-03T10:25:30",
  "per_index_counts": {"NIFTY": 400, "BANKNIFTY": 410, "FINNIFTY": 220, "SENSEX": 204}
}
```

Heuristic index detection: first path component under `--csv-dir` (default `data/g6_data`). This tool is read‑only and safe to run in production. Integrate results into dashboards or external alerting until automatic retention (Roadmap: Section 14) lands.

## 18. Glossary
| Term | Meaning |
|------|---------|
| PCR | Put/Call Ratio (put OI / call OI per expiry) |
| ATM | Strike closest to underlying spot |
| IV | Implied Volatility (inverted from premium) |
| Greeks | Delta, Gamma, Theta, Vega, Rho |
| Masks | Bit flags for expected vs collected expiries |
| Overview Snapshot | Aggregated per‑index per‑cycle row |

## 19. Quick Reference Cheat Sheet
| Action | Command |
|--------|---------|
| Single cycle | `python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 1` |
| Enable fancy console | `$env:G6_FANCY_CONSOLE=1` then run main |
| Enable Greeks & IV | Set in config (`greeks.enabled`, `estimate_iv`) |
| Curl metrics | `curl http://localhost:<port>/metrics` |
| Tail logs (PS) | `Get-Content g6_platform.log -Wait` |
| Panels integrity check | `python scripts/panels_integrity_check.py --strict` |

## 20. Change Log (Doc‑Only Snippets)
* 2025‑10‑01: Unified README consolidation; panel integrity enhancements
* 2025‑09‑28: Token provider abstraction & headless mode

---
Feedback & contributions welcome. Keep governance tests green (env/config docs, schema sync, timing guard) and update `DEPRECATIONS.md` for any removed surfaces.
Hotspot triage: see `TECH_DEBT_HOTSPOTS.md` and run:
```
coverage xml && python scripts/coverage_hotspots.py --top 20
```
Baseline diff (show ΔRisk vs prior run):
```
coverage xml && python scripts/coverage_hotspots.py --json > prev_hotspots.json
# ... add tests ...
coverage xml && python scripts/coverage_hotspots.py --baseline prev_hotspots.json --top 15
```

## Panels & Manifest Integrity Monitor

An optional background thread periodically verifies that emitted panel files match the hashes recorded in `manifest.json` (panels directory). Disabled by default for zero overhead.

Enable:
```
G6_PANELS_INTEGRITY_MONITOR=1
```

Key Environment Variables:
- `G6_PANELS_INTEGRITY_MONITOR` – Master switch.
- `G6_PANELS_INTEGRITY_INTERVAL` – Seconds between checks (default 30; coerced minimum 5).
- `G6_PANELS_INTEGRITY_STRICT` – Fail fast (SystemExit 2) on first mismatch (CI enforcement).

Metrics (Prometheus):
- Core (spec / legacy):
  - `g6_panels_integrity_ok` (Gauge: 1 = all hashes match, 0 = mismatch detected)
  - `g6_panels_integrity_mismatches_total` (Counter: cumulative mismatches)
- Extended (additive observability – may be absent in older builds):
  - `g6_panels_integrity_checks_total` (Counter: total integrity checks executed)
  - `g6_panels_integrity_failures_total` (Counter: checks that observed >=1 mismatch)
  - `g6_panels_integrity_last_elapsed_seconds` (Gauge: duration of last check)
  - `g6_panels_integrity_last_gap_seconds` (Gauge: gap since last successful check)
  - `g6_panels_integrity_last_success_age_seconds` (Gauge: age of last successful pass)
  - (Legacy monitor-only gauges no longer emitted: `g6_panels_integrity_last_mismatch_count`, `g6_panels_integrity_last_run_unixtime`) – superseded by the extended set above. Existing dashboards can migrate without breakage (old gauges simply stabilize if still scraped).

Mismatch Conditions:
- Panel file missing that is listed in manifest.
- Hash of panel `data` section differs from manifest recorded hash.

Typical Uses:
1. Continuous artifact drift detection in long‑running publisher processes.
2. CI gate ensuring reproducible panel artifacts across build steps.
3. Operational alerting (Grafana alerts on `g6_panels_integrity_ok == 0`).

Overhead: hashing small JSON files once per interval (negligible). Safe to enable broadly; keep disabled in ephemeral one‑shot scripts.

Strict Mode: Activate only in environments where any corruption must abort immediately (e.g., release packaging). The monitor logs metrics before exit for post‑mortem analysis.

Do not rely on bypass in CI; only for local iteration. If a refactor temporarily dips coverage just below threshold, either add minimal tests or (as a last resort) lower `fail_under` a single point with a follow-up TODO to restore.

Suggested near-term high-impact areas for coverage uplift:
- `src/orchestrator/catalog_http.py` branch edges (error paths, adaptive theme SSE diff mode)
- `src/panels/factory.py` panel assembly fallbacks
- `src/metrics/metrics.py` rarely triggered exception branches
- `src/storage/csv_sink.py` multi-path retention / error handling
- `src/utils/*` time / retry backoff logic branches

To mark intentionally untestable lines, continue using `# pragma: no cover`. Keep pragmas surgical; broad blocks should instead gain tests.


# Enable all defaults plus extended vol surface analytics
G6_VOL_SURFACE=1

# Add high-cardinality per-expiry surface metrics (use sparingly)
G6_VOL_SURFACE_PER_EXPIRY=1
```

Troubleshooting gating:
| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Expected panel diff counters missing | `panel_diff` not enabled (whitelist) or explicitly disabled | Adjust `G6_ENABLE_METRIC_GROUPS` / `G6_DISABLE_METRIC_GROUPS` |
| `risk_agg_rows` missing in metadata | Neither neutral environment nor `G6_RISK_AGG=1` with group allowed | Clear enable list or enable risk agg group/flag |
| Vol surface interpolation metrics absent | `G6_VOL_SURFACE` unset or group not allowed | Set `G6_VOL_SURFACE=1` and ensure group enabled |
| Per-expiry vol surface metrics absent | `G6_VOL_SURFACE_PER_EXPIRY` unset | Set `G6_VOL_SURFACE_PER_EXPIRY=1` (consider cost) |

Design intent: gating should be transparent (no hidden always‑on surprises) while still allowing the neutral environment to expose a representative sample for metadata validation and documentation generation.

### Panels Runtime Schema Validation (2025-10)
Panels emitted by `PanelsWriter` follow a wrapped schema:
```
{
  "panel": "<name>",
  "updated_at": "<ISO8601 Z>",
  "data": { ... }   # or array/null depending on panel type
}
```
Validation Modes (env `G6_PANELS_VALIDATE`):
| Value  | Behavior | Notes |
|--------|----------|-------|
| off    | Skip runtime JSON Schema validation | Fastest path (no protection) |
| warn   | Validate each panel; log warning if invalid | Default when unspecified / unknown value |
| strict | Validate; raise `ValueError` on the first invalid panel | Causes summary loop / writer to fail fast |

Implementation details:

Operational Guidance:

Example:
```
G6_PANELS_VALIDATE=strict python scripts/summary_view.py --refresh 1
```

Future Enhancements (candidates):

# Panels Manifest Hash Integrity (2025-10)
Each panel file now has its canonical content hash embedded in `manifest.json` under a top-level `hashes` object:
```
{
  "panels": ["summary", "indices", ...],
  "hashes": {
    "summary_panel.json": "<sha256>",
    "indices_panel.json": "<sha256>",
    ...
  }
}
```
Hash Definition:
* Algorithm: sha256
* Input: Canonical JSON serialization of the panel's `data` member only (NOT including the wrapper fields `panel` or `updated_at`). Serialization uses `sort_keys=True` and compact separators `(',', ':')` to ensure determinism.
* Empty / null `data` serializes as the JSON literal (`null`, `[]`, `{}` respectively) prior to hashing.

Rationale:
* Detects silent corruption or partial writes (e.g., truncated file, external tampering) between emission and consumption.
* Allows inexpensive integrity sweep without re-reading or diffing large payloads.
* Excluding wrapper metadata stabilizes hashes across routine timestamp updates.

Verification Helper:
The function `verify_manifest_hashes(panels_dir) -> dict[str,str]` (in `src/panels/validate.py`) returns a mapping of filename → issue code when mismatches are detected. Empty dict ⇒ all verified.

Issue Codes:
* `mismatch` – File's recomputed hash differs from manifest entry.
* `file_missing` – Listed file absent on disk.
* `invalid_hash_format` – Manifest entry not a 64‑hex string.
* `read_error:<Type>` – Exception while loading or hashing the panel file.
* `error:<Type>` – Unexpected top-level error (manifest unreadable etc.).

Operational Usage Examples:
```python
from src.panels.validate import verify_manifest_hashes
issues = verify_manifest_hashes('data/panels')
if issues:
    print('Integrity problems:', issues)
```
CLI / Manual:
```
python -c "from src.panels.validate import verify_manifest_hashes; import json; print(json.dumps(verify_manifest_hashes('data/panels'), indent=2))"
```

Failure Policy Suggestions:
* Development / CI: treat any non-empty result as failure.
* Production: log & optionally trigger re-emission if only a subset mismatched.

Caveats & Future Work:
* Manifest currently omits its own hash (self-referential recursion). Could add second file (`manifest.hash.json`) if meta-level integrity needed.
* No replay prevention—hashes attest to content integrity, not freshness. Combine with generation counters or signed attestations for stronger guarantees.
* Potential extension: Metric `panel_hash_mismatch_total` during periodic verification sweeps.

Testing: `tests/test_panels_manifest_hashes.py` covers happy path, mismatch (content change), and missing file scenarios.

# Panels Integrity CLI
The script `scripts/panels_integrity_check.py` provides a lightweight command‑line interface around `verify_manifest_hashes`.

Usage:
```
python scripts/panels_integrity_check.py [--panels-dir data/panels] [--strict] [--json] [--quiet]
```

Flags:
* `--strict` – Exit code 1 if any issues detected (default exit 0 even with issues when not strict).
* `--json` – Emit JSON object `{ "issues": {...}, "count": N }` (machine friendly).
* `--quiet` – Suppress OK line when no issues (still outputs JSON if `--json`).
* `--panels-dir` – Override panels directory (default `data/panels`).

Exit Codes:
* 0 – No issues (or issues allowed in non-strict mode)
* 1 – Issues found (strict mode)
* 2 – Unexpected execution error (I/O, manifest parse failure)

Examples:
```
# Human output (non-strict)
python scripts/panels_integrity_check.py

# Strict CI gate (fail on mismatch)
python scripts/panels_integrity_check.py --strict

# JSON for tooling integration
python scripts/panels_integrity_check.py --json --strict > integrity_report.json
```

Integration Suggestion (CI):
Add a pipeline step after panel generation tests:
```
python scripts/panels_integrity_check.py --strict --json
```
Parse `count` to ensure zero mismatches before deployment.

# ...existing code...
````
