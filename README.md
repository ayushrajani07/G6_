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

# Launch summary (unified loop; Rich if available, automatic plain renderer with --no-rich)
python -m scripts.summary.app --refresh 1

# Simulator + summary demo (panels auto-managed)
python scripts/status_simulator.py --status-file data/runtime_status_demo.json --indices NIFTY,BANKNIFTY,FINNIFTY,SENSEX --interval 60 --refresh 0.1 --open-market --with-analytics --cycles 1
python -m scripts.summary.app --refresh 0.5 --status-file data/runtime_status_demo.json
```

VS Code Tasks (recommended):
* `Smoke: Start Simulator` → background status generation
* `Smoke: Start Panels Bridge` (legacy compatibility; panels now usually in‑process) 
* `Smoke: Summary (panels mode)` → interactive summary
* `G6: Init Menu` → interactive configuration & launch helper

### Testing (two-phase recommended)
Default pytest is configured for parallel runs excluding serial-marked tests. For best UX and stability, use the two-phase flow:

```powershell
# Phase 1: parallel (exclude serial)
pytest -q

# Phase 2: serial-only follow-up
pytest -q -m serial -n 0
```

Or run the VS Code task “pytest: two-phase (parallel -> serial)” to chain both.

Notes:
- Some tests are marked optional/slow/integration and may be skipped unless explicitly enabled.
- If a local port is blocked by your OS/firewall, tests will use ephemeral ports or non-network code paths.

## 3. Architecture Snapshot
| Layer | Path(s) | Responsibilities |
|-------|---------|------------------|
| Entry / Orchestration | `src/unified_main.py` | Bootstrap, feature toggles, graceful loop |
| Collectors | `src/collectors/unified_collectors.py` | Per‑cycle orchestration, optional snapshot build |
| Providers Facade | `src/collectors/providers_interface.py`, `src/broker/kite_provider.py` | Expiry & instrument resolution, quotes |
| Analytics | `src/analytics/option_greeks.py`, `src/analytics/option_chain.py` | IV estimation, Greeks, PCR, breadth |
| Storage | `src/storage/csv_sink.py`, `src/storage/influx_sink.py` | Persistent per‑option & overview writes |
| Metrics | `src/metrics/metrics.py` | Registration, grouped gating, metadata dump |
| Panels & Summary | `scripts/summary/app.py`, `src/panels/*` | Real‑time textual panels & JSON artifact emission |
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
| Collector Modules | `collectors/modules/*.py` | Strike depth calc, aggregation, coverage/status finalization | [C] | Evaluate adaptive strike window (P) |
| Providers Facade | `collectors/providers_interface.py`, `providers/` | Abstract live / mock provider, expiry + instrument resolution | [IP] | Multi-provider fallback design drafted; implementation pending |
| Token Management | `tools/token_manager.py`, `tools/token_providers/*` | Acquire / validate auth tokens (kite, fake) | [C] | Add secret sanitization (P) |
| Analytics (Greeks/IV) | `analytics/option_greeks.py`, `analytics/iv_solver.py` | Newton-Raphson IV, Greeks, PCR, breadth | [C] | Vol surface interpolation (P); risk aggregation (E) |
| Adaptive / Cardinality | `adaptive/`, `metrics/cardinality_manager.py` | Dynamic emission gating & adaptive detail modes | [IP] | Additional feedback loops & band window tuning (P) |
| Storage CSV | `storage/csv_sink.py` | Durable per-option & overview rows | [C] | Retention / pruning engine (P) |
| Storage Influx | `storage/influx_sink.py` | Optional time-series writes | [C] | Evaluate migration to client batching (P) |
| Panels Writer & Summary | `panels/`, `scripts/summary/app.py`, `summary/` | Real-time textual + JSON panels emission | [C] | Per-index enrichment additions (P) |
| Panel Integrity | `panels/validate.py`, `panels/integrity_monitor.py` | Hash manifest, integrity verification loop | [C] | Consider checksum streaming API (P) |
| Metrics Facade | `metrics/__init__.py`, `metrics/metrics.py` | Registry acquisition, grouped registration, placeholders | [IP] | Continued modular extraction (Phase 3.x) |
| Metrics Group Registry | `metrics/group_registry.py`, `metrics/placeholders.py` | Controlled families, always-on safety sets | [C] | Monitor for alias deprecation removals (D: `perf_cache` soon) |
| Resilience Utilities | `utils/resilience.py`, `utils/circuit_breaker.py` | Retry/backoff, circuit breaking | [C] | Jitter parameterization exposure (P); design policy details in Pipeline Design §4.6 |
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

Consolidated Runtime Flags (A23/A24): High‑traffic collector toggles (salvage, outage thresholds, heartbeat interval, quiet/trace; formerly synthetic fallback disable) are hydrated once via `CollectorSettings`. The synthetic fallback toggle was removed in Oct 2025 (see CHANGELOG – rationale: eliminate silent data fabrication and simplify coverage reasoning). Changing the corresponding environment variables after startup has no effect unless the process restarts or `get_collector_settings(force_reload=True)` is explicitly called (discouraged in hot paths). This improves determinism and removes repeated env parsing overhead.

Human Settings Summary: On first hydration a single structured line `collector.settings.summary ...` is logged. Enable a multi-line aligned block for readability by setting `G6_SETTINGS_SUMMARY_HUMAN=1` (optional; emits once, low noise). Example:

```
SETTINGS SUMMARY
  min_volume                 : 0
  salvage_enabled            : 0
  outage_threshold           : 3
  outage_log_every           : 5
  heartbeat_interval         : 0.0
  pipeline_v2_flag           : 0
```

Related: `docs/env_dict.md`, `docs/CONFIG_FEATURE_TOGGLES.md`, `docs/ENVIRONMENT.md`.

### 6.1.1 Automation Enhancements (CI)
The following automation layers reinforce governance and performance:
| Workflow | Purpose | Notes |
|----------|---------|-------|
| `pr-checklist.yml` | Strict gating (env docs, readiness run) | Fails PR if critical items missing |
| `pr-checklist-comment.yml` | Posts/upserts a summarized checklist comment | Uses `--summary-line` output for quick scan |
| `nightly-sse-soak.yml` | Long-run SSE stability monitoring | Soft-fail; artifacts retained (gaps, reconnect counts) |

The checklist script (`scripts/pr_checklist.py`) supports a compact machine-readable line (`--summary-line`) consumed by the PR comment workflow, while full markdown is retained for manual audit.

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

### 7.1 SSE Streaming Security & Hardening
See `docs/SSE_SECURITY.md` for end-to-end details on:
* Authentication & IP allow list
* Per-IP connection rate limiting
* User-Agent allow list enforcement
* Request correlation (X-Request-ID)
* Event size truncation & sanitization
* Metrics reference (counters + histograms)
* Structured diff mode & latency tracking

The SSE server (and unified HTTP server) now auto-enable when summary runs; legacy gating flags are ignored (documented in the security guide). Use `G6_DISABLE_RESYNC_HTTP=1` only if you must disable the resync endpoint.

### 7.2 Structured Diff & Clients (Phase 7)
Structured diff mode (`G6_SSE_STRUCTURED=1`) emits `panel_diff` events containing only changed panels instead of `panel_update` lists. Reference clients:
* Python: `clients/python_sse_client.py` (reconnect, state merge, heartbeat handling)
* JavaScript: `clients/js_sse_client.js` (Node/browser compatible, manual SSE frame parsing)

### 7.3 Performance Instrumentation & Benchmark
Optional publisher performance profiling: set `G6_SSE_PERF_PROFILE=1` to enable histograms:
* `g6_sse_pub_diff_build_seconds`
* `g6_sse_pub_emit_latency_seconds`

Micro-benchmark harness:
```powershell
python scripts/bench_sse_loop.py --cycles 500 --panels 80 --change-ratio 0.15 --structured
```
Outputs per-cycle processing latencies (avg/p50/p95/p99) and events/sec.

### 7.4 Release Readiness Automation
Pre-release gate script consolidates critical checks:
```powershell
python scripts/release_readiness.py --strict --check-deprecations --check-sse --check-metrics
```
Optional short performance smoke:
```powershell
python scripts/release_readiness.py --check-sse --bench --bench-cycles 120
```
Ensures env docs coverage, absence of deprecated scripts, core SSE security metrics presence, and initial event emission.

### 7.5 Soak & Stability Harness
Long-running stability validation for SSE streaming:
```powershell
python scripts/sse_soak.py --duration 900 `
  --budget-max-reconnects 5 `
  --budget-max-gap-p95 12 `
  --budget-max-rss-growth-mb 50
```
Outputs aggregate stats (events, reconnects, p95 inter-event gap, RSS growth). Non-zero exit on any budget breach; integrate into nightly CI for regression detection. RSS sampling uses psutil when available or /proc fallback.

### 7.6 Performance Budgets (Benchmark Gate)
Synthetic micro-benchmark latency enforcement via readiness script:
```powershell
python scripts/release_readiness.py --perf-budget-p95-ms 5.0 `
  --perf-budget-cycles 220 `
  --perf-budget-panels 70 `
  --perf-budget-change-ratio 0.12 `
  --perf-budget-structured
```
Fails if `SSEPublisher.process()` p95 latency exceeds budget. Use alongside `--strict --check-deprecations --check-env` for holistic gating.

### 7.6.1 One-Shot Startup Summaries
Core subsystems emit a single structured summary line at first initialization for deterministic operator visibility. Optional human-readable multi-line blocks (aligned key/value) can be enabled via environment flags below.

| Subsystem | Structured Event (always once) | Human Block Flag | Notes |
|-----------|--------------------------------|------------------|-------|
| Settings Collector | `collector.settings.summary` | `G6_SETTINGS_SUMMARY_HUMAN=1` | Emits consolidated env-derived collector flags & thresholds |
| Provider (Kite) | `provider.kite.summary` | `G6_PROVIDER_SUMMARY_HUMAN=1` | Presence & throttle / fabrication configuration |
| Metrics Registry | `metrics.registry.summary` | `G6_METRICS_SUMMARY_HUMAN=1` | Families count, always-on group count, init profiling total |
| Orchestrator | `orchestrator.summary` | `G6_ORCH_SUMMARY_HUMAN=1` | High-level runtime mode (indices count, pipeline, diff mode, provider/metrics presence) |

Guidance:
* Human blocks are opt-in to keep default logs compact.
* All summaries are sentinel-guarded to avoid duplicate emission on re-imports.
* Structured lines are stable key-order to simplify log parsing & diffing.
* Future: potential JSON emission variant (planned) and masking of sensitive values if introduced.

#### 7.6.2 Operator Diagnostics Examples
Example structured + human + JSON trio for settings (truncated):
```
collector.settings.summary min_volume=0 min_oi=0 vol_pct=0.00 salvage=0 foreign_salvage=0 ... pipeline_v2=1

SETTINGS SUMMARY
  min_volume            : 0
  min_oi                : 0
  salvage_enabled       : 0
  pipeline_v2_flag      : 1

{"type":"collector.settings.summary.json","ts":1738888888,"fields":{"heartbeat_interval":0.0,"min_oi":0,"min_volume":0,"pipeline_v2_flag":1,"quiet_mode":0},"hash":"d3adbeefcafe1234","emit_ms":0.221}
```

Troubleshooting quick hints:
| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| `provider.kite.summary` missing or `has_client=0` | Credentials absent or invalid | Ensure `KITE_API_KEY` / token env set before start |
| `metrics.registry.summary families=-1` | Collector failure reading registry | Check earlier errors; ensure prometheus_client installed |
| `orchestrator.summary provider_client=0` but settings show salvage enabled | Provider not initialized yet | Inspect logs for provider init errors; may retry later |
| `env.deprecations.summary count>0` | Deprecated env vars set | Remove or migrate before enabling strict mode |
| JSON summaries absent | JSON flags not enabled | Set `G6_*_SUMMARY_JSON=1` for subsystems needed |

Composite hash line aids diffing across deploys:
```
startup.summaries.hash count=5 composite=4e1f9a02b3cd77ab998812aa ts=1738888889
```
If composite hash changes unexpectedly between deploys, compare individual JSON hashes to isolate changed fields.

### 7.7 Grafana Dashboards (Extended)
Additional focused dashboards for SSE performance, security, and panels integrity are provided under `grafana/dashboards/`:
| Domain | File | Purpose |
|--------|------|---------|
| SSE Performance | `g6_perf_latency.json` | Diff build & emit latency, queue delay, event size distribution |
| SSE Security | `g6_sse_security.json` | Auth failures, forbidden IP/UA, rate limiting, security drops |
| Panels Integrity | `g6_panels_integrity.json` | Diff vs full ratio, integrity health, need_full episodes |

See `docs/OBSERVABILITY_DASHBOARDS.md` for PromQL mappings, alert suggestions, and provisioning notes.

#### 7.7.1 Modular Generation & Drift Guard
Dashboards under `grafana/dashboards/generated/` are produced by the modular generator (`scripts/gen_dashboards_modular.py`).

Key features:
* Deterministic panel IDs (stable hash of semantic signature)
* Auto synthesis: counter rate, histogram p95/p99 (recording rules), limited label splits (topK & by <label>)
* Cross-metric efficiency panels (diff bytes/write, ingest bytes/row, backlog ETA) for selected dashboards
* Plan-driven composition (families → dashboards) with manifest summarizing panel counts & spec hash
* Panel metadata (`g6_meta`) enrichment: metric, family, kind, source (spec|auto_rate|auto_hist_quantile|auto_label_split|placeholder|cross_metric|alerts_aggregate|governance_summary)

Drift verification (CI-friendly):
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify
```
Exit code 6 signals semantic drift (added/removed/changed panels or spec hash mismatch). Set `G6_DASHBOARD_DIFF_VERBOSE=1` for human-readable JSON lines of changed/added/removed panel titles.

Partial regeneration for rapid iteration:
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only bus_health
```
Skipped dashboards show `panel_count: 0` in manifest until a full regeneration is performed.

Further details: `GRAFANA_GENERATION.md`.

### 7.7.2 Multi-Pane Explorer (Experimental)
A lightweight exploratory dashboard `multi_pane_explorer` is generated via the modular generator. Current structure (post consolidation & delta integration):

Base template panels (repeat per selected `$metric`):
* Raw series & 5m rate overlay (optional 30s overlay when `overlay=on`)
* 1m vs 5m rate comparison
* 5m / 30m rate ratio (trend acceleration / degradation signal)
* Cumulative total (sum)

Histogram-aware panels (repeat per `$metric_hist` and driven by `q` quantile variable):
* Quantile summary table – 5m, 30m, ratio, delta (% change) with symmetric color thresholds
* Quantile 5m vs 30m window timeseries

The standalone histogram ratio panel was collapsed into the summary table to reduce vertical footprint. Delta thresholds now use symmetric bands (default: red ≤ -20%, yellow -20%..-5%, green -5%..+5%, yellow +5%..+20%, red > +20%).

Compact variant `multi_pane_explorer_compact`:
* Removes the cumulative total panel
* Reduces base panel heights from 8 → 6
* Pulls summary + histogram window panels upward (overall 5 panels instead of 6)

Generation:
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only multi_pane_explorer
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only multi_pane_explorer_compact
```
Open the corresponding `g6-multi_pane_explorer*` dashboards in Grafana and multi-select metrics. See `TIME_SERIES_MULTI_PANE_PANEL.md` for the phased design & roadmap.

#### 7.8 Dashboard Distribution Bundle
Package all production dashboards and a manifest with:
```powershell
python scripts/package_dashboards.py --version 1.0.0 --out dist
```
Outputs: `dashboards_<ver>.tar.gz`, checksum, and `dashboards_manifest_<ver>.json`. See `docs/DASHBOARD_DISTRIBUTION.md` for integrity verification and CI automation (workflow `dashboards-package.yml`).

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

### 7.6.3 CI Gate: Parity & Fatal Guard (W4-20)
Lightweight quality gate ensuring collection health (parity maintained, fatal errors bounded) before merging or deploying.

Weight Calibration Note (W4-18): Default parity component weights are currently equal. For adopting empirically tuned weights, run `scripts/parity_weight_study.py` and see Pipeline Design Section 4.7 (Parity Weight Tuning Study) for methodology, schema, and adoption workflow.

Metrics Enforced:
* Rolling Parity: `g6_pipeline_parity_rolling_avg` (must be >= min parity)
* Fatal Ratio: `g6:pipeline_fatal_ratio_15m` (must be <= max fatal ratio)

Script: `scripts/ci_gate.py`

Usage Examples:
```powershell
# Scrape live metrics endpoint with defaults (min parity 0.985, max fatal ratio 0.05)
python scripts/ci_gate.py --metrics-url http://127.0.0.1:9108/metrics --json

# Offline evaluation of captured snapshot with custom thresholds
python scripts/ci_gate.py --metrics-file metrics_snapshot.txt --min-parity 0.990 --max-fatal-ratio 0.03 --json

# Allow missing metrics (soft exit 2) during early warm-up
python scripts/ci_gate.py --metrics-url http://127.0.0.1:9108/metrics --allow-missing --json
```

Exit Codes:
| Code | Meaning |
|------|---------|
| 0 | Pass (thresholds satisfied) |
| 1 | Failure (threshold breach or fetch/parse error under strict mode) |
| 2 | Soft-missing (metrics absent with `--allow-missing`) |

Key Flags:
| Flag | Purpose |
|------|---------|
| `--min-parity FLOAT` | Minimum rolling parity (default 0.985) |
| `--max-fatal-ratio FLOAT` | Maximum fatal ratio (default 0.05) |
| `--metrics-url URL` | Prometheus exporter endpoint |
| `--metrics-file PATH` | Local metrics text file |
| `--allow-missing` | Downgrade missing metrics to soft exit (2) |
| `--json` | Emit JSON report |
| `--parity-metric NAME` | Override parity metric name |
| `--fatal-metric NAME` | Override fatal ratio metric name |
| `--strict` | Treat fetch/parse errors as hard failure (default behavior) |

Sample JSON Output (failure):
```json
{
  "status": "fail",
  "parity": 0.9621,
  "fatal_ratio": 0.081,
  "min_parity": 0.985,
  "max_fatal_ratio": 0.05,
  "reasons": [
    "parity_below_threshold(0.9621 < 0.985)",
    "fatal_ratio_above_threshold(0.081 > 0.05)"
  ]
}
```

GitHub Actions Snippet:
```yaml
  - name: Start collector (background)
    run: |
      python scripts/run_orchestrator_loop.py --interval 30 --cycles 6 &
      echo $! > collector.pid
  - name: Warm-up
    run: powershell -Command "Start-Sleep -Seconds 120"
  - name: CI Gate (Parity & Fatal)
    run: python scripts/ci_gate.py --metrics-url http://127.0.0.1:9108/metrics --min-parity 0.987 --max-fatal-ratio 0.04 --json
```

#### 7.6.3.1 Fatal Ratio Alert Rules (W4-02)
Operational alerting complements the CI gate with three Prometheus alerts backed by the recording rule `g6:pipeline_fatal_ratio_15m`:
* Spike: `G6PipelineFatalSpike` fires when fatal ratio > 0.05 for 10m
* Sustained: `G6PipelineFatalSustained` fires when fatal ratio > 0.10 for 5m
* Parity Combo: `G6PipelineParityFatalCombo` fires when parity < 0.985 AND fatal ratio > 0.05 for 5m

Test coverage: `tests/test_fatal_ratio_alert_rule.py` asserts expression thresholds, `for:` durations, and recording rule presence to prevent silent drift.

Operational Guidance:
1. Run after a few cycles so rolling parity stabilizes.
2. Tune thresholds conservatively; tighten once variance bounds understood.
3. Pair with benchmark & readiness gates for holistic regression detection.
4. Capture metrics snapshot on failure for post-mortem: `curl http://127.0.0.1:9108/metrics > failed_metrics.txt`.
5. To disable temporarily, skip the step (avoid trivially permissive thresholds long term).

### 7.6.3.2 Parity Snapshot CLI (W4-14)
Generates a JSON snapshot summarizing parity components, rolling window simulation, and alert category deltas.

Script: `scripts/parity_snapshot_cli.py`

Flags:
| Flag | Purpose |
|------|---------|
| `--legacy FILE` | Legacy baseline JSON (optional) |
| `--pipeline FILE` | Pipeline JSON (optional) |
| `--weights comp:weight,...` | Override component weights |
| `--extended` / `--shape` / `--cov-var` | Enable extended parity components (env shims) |
| `--rolling-window N` | Simulate rolling window size (>=2) |
| `--version-only` | Emit only version & score fields |
| `--pretty` | Pretty-print JSON |
| `--output FILE` | Write snapshot to file instead of stdout |

Example:
```powershell
python scripts/parity_snapshot_cli.py --legacy legacy.json --pipeline pipe.json --rolling-window 10 --extended --pretty > parity_snapshot.json
```

Sample Output (abridged):
```json
{
  "generated_at": "2025-10-08T12:34:56.789012+00:00",
  "parity": {"version": 3, "score": 0.9825, "components": {"index_count": 1.0, "option_count": 0.97, "alerts": 0.98}},
  "rolling": {"window": 10, "avg": 0.9812, "count": 1},
  "alerts": {"categories": {"critical": {"legacy": 2, "pipeline": 3, "delta": 1}}, "sym_diff": [], "sym_diff_count": 0, "union_count": 5}
}
```

Test: `tests/test_parity_snapshot_cli.py` ensures schema stability and prevents silent drift in required fields.

### 7.6.3.3 Alert Parity Anomaly Event (W4-15)
Emits structured event `pipeline.alert_parity.anomaly` when the weighted alert parity difference crosses an operator-defined threshold.

Environment:
| Var | Default | Purpose |
|-----|---------|---------|
| `G6_PARITY_ALERT_ANOMALY_THRESHOLD` | -1 | Enable & set threshold (0..1). -1 disables. |
| `G6_PARITY_ALERT_ANOMALY_MIN_TOTAL` | 3 | Minimum alert category union size to consider emission |

Payload (logged as JSON via logger extra structured_event):
```
{
  "event": "pipeline.alert_parity.anomaly",
  "ts": 1700000000.123,
  "score": 0.9721,
  "weighted_diff_norm": 0.41,
  "threshold": 0.30,
  "parity_version": 3,
  "components": {"index_count":1.0, "option_count":0.98, "alerts":0.92},
  "categories": { "critical": {"legacy":2, "pipeline":4, "diff_norm":1.0, "weight":1.0 }, ... }
}
```

Test: `tests/test_parity_anomaly_event.py` ensures correct emission gating (enabled, below threshold, disabled).

### 7.1 Panels & Integrity
Panel writer emits JSON panels + `manifest.json` with SHA‑256 hashes (data section only). Integrity monitor (opt‑in) periodically verifies hashes.
Environment:
| Var | Purpose |
|-----|---------|
| `G6_PANELS_INTEGRITY_MONITOR` | Enable monitor thread |
| `G6_PANELS_INTEGRITY_INTERVAL` | Seconds between sweeps (≥5) |
| `G6_PANELS_INTEGRITY_STRICT` | Fail fast on mismatch |

## Git Push Menu Utility

An interactive helper script to streamline common git push workflows (default behavior: push to `main`).

Script: `scripts/git_push_menu.ps1`

Usage examples (PowerShell):
```powershell
pwsh scripts/git_push_menu.ps1              # Interactive menu
pwsh scripts/git_push_menu.ps1 -Option 1    # Push to main directly
pwsh scripts/git_push_menu.ps1 -Option 1 -Message "chore: regenerate dashboards"  # Auto-commit & push
pwsh scripts/git_push_menu.ps1 -Option 5 -Tag v0.6.0   # Create lightweight tag then push
```

Menu Options:
1 Push to main (fetch + rebase onto origin/main, then push)
2 Push current branch
3 Pull --rebase then push current branch
4 Force-with-lease push current branch (safe force)
5 Create tag (lightweight) then push (requires -Tag)
6 Push existing tag (requires -Tag)
7 Push all tags
8 Status + ahead/behind summary
9 Dry-run push (no changes transferred)
10 Fetch --prune (clean up deleted remote branches)
0 Exit

Flags:
 -Option <n> Select menu item non-interactively.
 -Tag <name> Provide tag for options 5/6.
 -Message <msg> Auto-commit staged & unstaged changes (if any) before action.

Safety: Aborts on uncommitted changes unless you confirm auto-commit or supply -Message. Uses `--force-with-lease` for safer force pushes.

Python alternative (cross-platform):
```powershell
python scripts/git_push_menu.py --option 1 --message "chore: sync"   # push to main after auto-commit
python scripts/git_push_menu.py          # interactive menu
python scripts/git_push_menu.py --option 5 --tag v0.6.0
```



Panel Schema Validation (`G6_PANELS_VALIDATE`): `off` | `warn` (default) | `strict`.

Manifest Hash Rationale: detect corruption / partial writes while excluding timestamp churn.

### 7.2 Metrics Glossary (Auto‑Generated)
<!-- METRICS_GLOSSARY_START -->
### Metrics Glossary (Auto-Generated)
_The section below is managed by `scripts/gen_metrics_glossary.py`. Do not edit manually._

_No metric annotations found._
<!-- METRICS_GLOSSARY_END -->

### 7.3 Observability Surfaces
1. Summary dashboard (`scripts/summary/app.py` Rich / plain)
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

## 21. Release Automation & Supply Chain Tooling (New)

### 21.1 Unified Release Orchestrator
`g6-release-automation` (wrapper for `scripts/release_automation.py`) bundles readiness, dashboard packaging, optional signing, and SBOM generation into a single JSON-emitting step.

Example (local dry run, manifest only):
```powershell
g6-release-automation --manifest-only --perf-budget-p95-ms 5 --perf-budget-panels 60 --perf-budget-cycles 160 --sbom --allow-soft-fail sign
```
JSON summary fields:
| Field | Meaning |
|-------|---------|
| `version` | Resolved version (env / git describe / explicit) |
| `stages.readiness.ok` | Readiness script succeeded |
| `stages.dashboards.manifest` | Path to generated manifest |
| `stages.dashboards.archive` | Archive path (if built) |
| `stages.sign` | Signing result / skipped reason |
| `stages.sbom` | SBOM artifact path |

GitHub Workflow: `.github/workflows/release-automation.yml` triggers on tag `v*` and creates a GitHub Release with attached dashboards + SBOM.

### 21.2 Dashboard Diff & Changelog
`dashboard_diff` compares two manifests, producing added / removed / changed lists and prepending to `CHANGELOG_DASHBOARDS.md`.
```powershell
python scripts/dashboard_diff.py --prev dist/dashboards_manifest_v1.1.0.json `
  --curr dist/dashboards_manifest_v1.2.0.json --version v1.2.0 `
  --changelog CHANGELOG_DASHBOARDS.md --json
```
Use with CI to fail if no changes when a dashboard-only release is expected (`--fail-if-no-change`).

### 21.3 Dashboard Signing
`sign_dashboards.py` adds detached integrity metadata for packaged dashboards.
Priority: Ed25519 key (base64 private) via `G6_SIGN_KEY`; fallback HMAC via `G6_SIGN_SECRET` if key absent.
```powershell
python scripts/sign_dashboards.py --archive dist/dashboards_1.2.0.tar.gz
```
Outputs `<archive>.sig` JSON metadata (algorithm, public key when Ed25519). Verification:
```powershell
python scripts/sign_dashboards.py --archive dist/dashboards_1.2.0.tar.gz --verify --signature dist/dashboards_1.2.0.tar.gz.sig --public-key <base64_pub>
```

### 21.4 SBOM Generation
`gen_sbom.py` emits CycloneDX-lite JSON (`sbom_<version>.json`). Workflow `.github/workflows/sbom.yml` publishes artifacts on `main` pushes and tags. Enable partial hashing with:
```
G6_SBOM_INCLUDE_HASH=1
```
(_Partial hashing limits scanned files for performance_).

### 21.5 Prometheus Recording & Alert Rules (SSE Extensions)
Added files:
| File | Purpose |
|------|---------|
| `prometheus/recording_rules_g6.yml` | Derived SSE rates, diff ratio, latency p95, security drops |
| `prometheus/alert_rules_g6.yml` | Queue latency, diff efficiency, security drop, auth failure, rate-limited spikes |

Key Derived Metrics:
| Record | Description |
|--------|-------------|
| `g6_sse_panel_diff_ratio_15m` | Efficiency ratio (diff vs diff+full) |
| `g6_sse_http_event_queue_latency_p95_5m` | Enqueue→write p95 |
| `g6_sse_http_security_drop_rate_5m` | Sanitization drop rate |

Alert Threshold Rationale:
| Condition | Threshold | Justification |
|-----------|-----------|---------------|
| Queue p95 warn | 400ms | Above typical internal budget (diff build+emit < ~200ms) |
| Queue p95 crit | 750ms | Indicates backlog or client blocking writes |
| Diff ratio warn | <0.85 | Efficiency regression; more full snapshots than expected |
| Security drops | >1/s | Sustained anomalies / malicious clients |

### 21.6 Flaky Test & Slow Test Profiler
`test_flakiness.py` executes multiple pytest runs (default 3):
```powershell
python scripts/test_flakiness.py --runs 5 --json --fail-on-flaky
```
JSON output includes `flaky`, `always_fail`, and `top_slow` arrays. Integrate as an optional CI job to quarantine unstable tests early.

### 21.7 CLI Entry Points Summary
| Command | Script | Purpose |
|---------|--------|---------|
| `g6-readiness` | `release_readiness.py` | Pre-release gate & perf budget |
| `g6-pr-checklist` | `pr_checklist.py` | PR governance summary line / markdown |
| `g6-dashboards-package` | `package_dashboards.py` | Bundle dashboards + manifest |
| `g6-dashboards-diff` | `dashboard_diff.py` | Manifest diff + changelog update |
| `g6-dashboards-sign` | `sign_dashboards.py` | Sign / verify dashboard archive |
| `g6-release-automation` | `release_automation.py` | Orchestrated release pipeline |
| `g6-sbom` | `gen_sbom.py` | CycloneDX-lite SBOM generation |
| `g6-test-flakiness` | `test_flakiness.py` | Flaky & slow test detection |

### 21.8 Operational Workflow (End-to-End)
1. Developer adds/updates dashboards & code.
2. PR triggers checklist + readiness (strict). Nightly soak keeps latency budgets honest.
3. Tag push (`vX.Y.Z`): release workflow runs orchestrator → readiness, packaging, (optional sign), SBOM, GitHub Release.
4. (Optional) Dashboard diff job compares previous version manifest to generate changelog.
5. Prometheus ingests new recording/alert rules; Grafana dashboards auto-refresh reflect new derived metrics.

### 21.9 Future Enhancements (Planned)
| Area | Candidate |
|------|-----------|
| Signing | Cosign-style OCI artifact attestation |
| SBOM | Merge with `pip_audit` vulnerability snapshot |
| Release | Provenance statement (SLSA draft) |
| Flakiness | Historical trend storage & regression gating |
| Alerts | Adaptive thresholds (EWMA-based) |

### 21.10 Provenance Statement (Experimental v0)
Lightweight supply-chain provenance describing release artifacts.

Generation (included automatically in tag release workflow):
```powershell
g6-release-automation --provenance --sbom --sign --allow-soft-fail sign
```
Standalone:
```powershell
g6-provenance --version 1.2.3 --auto
```
Outputs: `dist/provenance_<version>.json` (schema `g6.provenance.v0`).

Key Fields:
| Field | Purpose |
|-------|---------|
| `builder` | Tool & version producing artifacts |
| `source.git_commit` | Immutable commit identifier |
| `artifacts[]` | Each artifact with sha256 + size |
| `signing` | Archive signature metadata (if present) |
| `metrics_snapshot` | Alert threshold context baked into release |

Verification:
```powershell
python scripts/verify_provenance.py --provenance dist/provenance_1.2.3.json --strict
```
JSON mode (`--json`) facilitates pipeline gating. Fails on checksum mismatch or missing artifacts.

Signing (optional): run release automation with `--sign` to produce archive signature; provenance JSON captures algorithm & public key (Ed25519). Future enhancement may sign the provenance file itself.

Trust Model: Provides evidence of artifact origin & integrity; does not yet attest build steps or environment reproducibility. Suitable as a precursor to in-toto/SLSA integration.

## 22. Adaptive Degrade Exit, Flush Latency & Tracing (Phase 9)
Focus: minimize time spent in degraded mode while preventing thrash, add server publish→flush latency visibility, and introduce lightweight end‑to‑end trace context.

Motivation:
* Static thresholds (Phase 8) entered degraded mode but used only backlog size to exit → risk of lingering longer than needed.
* Operators lacked direct metric for publish→flush latency (only serialization phase captured).
* Difficult to correlate serialization vs flush without a minimal trace timeline.

### 22.1 Adaptive Degrade Exit Controller
File: `src/events/adaptive_degrade.py`

State Machine:
| State | Meaning |
|-------|---------|
| NORMAL | Not degraded |
| DEGRADED | Static threshold triggered (diff minimization active) |
| EXIT_PENDING | Exit pre‑conditions satisfied; hysteresis window validating stability |

Exit Preconditions (evaluated while degraded):
1. Average backlog ratio over sliding window ≤ `G6_ADAPT_EXIT_BACKLOG_RATIO`.
2. P95 serialization latency within budget (`G6_ADAPT_LAT_BUDGET_MS`).
3. Minimum samples collected (`G6_ADAPT_MIN_SAMPLES`).
4. Stability persists for entire `G6_ADAPT_EXIT_WINDOW_SECONDS` while in EXIT_PENDING.

On success: transition emits `'exit_degraded'`; caller restores normal diff behavior and increments `g6_adaptive_transitions_total{reason="exit"}`.

Hysteresis / Anti‑Thrash:
* Cooldown (`G6_ADAPT_REENTRY_COOLDOWN_SECONDS`) timestamp recorded on exit (used by caller logic to avoid immediate re‑entry loops—future enhancement may expose a labeled metric for re‑entry suppression events).
* Abort exit if backlog or latency regress before window elapses (revert to DEGRADED).

Metrics:
| Metric | Type | Description |
|--------|------|-------------|
| `g6_adaptive_backlog_ratio` | Gauge | Latest backlog ratio sample (0‑1) |
| `g6_adaptive_transitions_total{reason}` | Counter | Transition counts (`exit`, future: `enter`, `abort`) |

Environment Variables (Adaptive):
| Var | Default | Purpose |
|-----|---------|---------|
| `G6_ADAPT_EXIT_BACKLOG_RATIO` | 0.4 | Target avg backlog ratio to start exit sequence |
| `G6_ADAPT_EXIT_WINDOW_SECONDS` | 5.0 | Stability window length / EXIT_PENDING dwell |
| `G6_ADAPT_LAT_BUDGET_MS` | 50.0 | P95 serialization latency budget |
| `G6_ADAPT_REENTRY_COOLDOWN_SECONDS` | 10.0 | Cooldown after exit before allowing new degraded period |
| `G6_ADAPT_MIN_SAMPLES` | 10 | Min samples before evaluating exit conditions |

Operational Guidance:
* Lower `EXIT_BACKLOG_RATIO` only if you observe frequent oscillations; too low increases dwell time.
* Increase `LAT_BUDGET_MS` if legitimate spikes (e.g., large full snapshot) delay exit; prefer optimizing serialization first.
* Shorten `EXIT_WINDOW_SECONDS` cautiously—very small windows (<2s) may cause flapping under bursty load.

### 22.2 Flush Latency Instrumentation
Metric: `g6_sse_flush_latency_seconds` (Histogram)
Scope: Measures server internal publish timestamp → network flush (write + flush to `wfile`).
Buckets: `[1ms,2ms,5ms,10ms,20ms,50ms,100ms,200ms,500ms,1s]`.
Activation: `G6_SSE_FLUSH_LATENCY_CAPTURE=1`.

Interpretation:
* P95 > 100ms indicates I/O contention or downstream client slowness.
* Divergence between `sse_serialize_seconds` p95 and flush p95 highlights network / write path bottlenecks vs serialization CPU.

### 22.3 Lightweight Trace Context
When `G6_SSE_TRACE=on`, each event payload embeds a `_trace` dict:
| Field | Description |
|-------|-------------|
| `id` | Monotonic or UUID style identifier (per event) |
| `publish_ts` | Timestamp captured at `EventBus.publish` entry |
| `serialize_ts` | Timestamp after serialization (if instrumentation enabled) |
| `flush_ts` | Timestamp just before/after flush in SSE HTTP handler |

Metric `g6_sse_trace_stages_total` increments per stage (serialize + flush) aiding detection of stalled stage emission (alert uses rate). Future work may add client apply timestamp for full diff→apply latency.

### 22.4 Snapshot Guard (Re‑exposed)
Method `enforce_snapshot_guard` reinstated to guarantee full snapshot emission after certain diff patterns—ensures downstream parity correctness post degraded recovery.

### 22.5 Alerting Extensions
Added (Prometheus) conditions (file: `prometheus_rules.yml`):
| Alert | Condition (example) | Purpose |
|-------|---------------------|---------|
| FlushLatencyHigh | `p95 > 0.1s` sustained | Early I/O / write path pressure |
| FlushLatencyCritical | `p95 > 0.25s` | Severe downstream blockage |
| AdaptiveDegradedStuck | `g6_events_degraded_mode==1` AND no exit > window | Detect lingering degraded state |
| TraceStagesStalled | Low rate of `g6_sse_trace_stages_total` while publishes occur | Trace pipeline stall |
| AdaptiveNoRecentExits | No `exit` transition over long horizon while degraded periods observed | Mis-tuned thresholds or logic fault |

Tune thresholds based on baseline post‑deployment—initial suggestions: warn at 100ms, crit at 250ms for flush p95.

### 22.6 Testing Additions
`tests/test_adaptive_trace.py` accelerates controller timing via env overrides (tiny window, minimal samples) to deterministically assert exit & cooldown behavior without long sleeps. Snapshot guard tests validate post‑publish enforcement.

### 22.7 Future Enhancements (Planned)
| Area | Candidate |
|------|----------|
| Tracing | Add diff→apply client timestamp to realize full E2E latency metric |
| Adaptive | Labelled transitions (`enter`, `abort_exit`) & reentry suppression counter |
| Metrics | Rolling backlog variance gauge for burstiness detection |
| Alerts | Dynamic adaptive latency budget (EWMA) experiment |

### 22.8 Quick Ops Checklist
1. Enable tracing (temp) for diagnosis: `G6_SSE_TRACE=1` (disable in steady state to keep payload lean).
2. Enable flush latency histogram in staging to baseline p95 before production: `G6_SSE_FLUSH_LATENCY_CAPTURE=1`.
3. Monitor `g6_adaptive_backlog_ratio` & transitions counter after synthetic load—ensure exit within target window.
4. Set alert thresholds once p95 steady (<50ms typical); adjust budgets only after verifying no serialization regression.

---

## 22. Performance & Scalability Enhancements (Phase 8)
Focus: reduce CPU per fan-out, add observability for serialization and backlog health, introduce controlled degrade mode.

New Components:
- Serialization Cache (`utils/serialization_cache.py`): LRU keyed by (event_type, payload hash).
- Backpressure & Degraded Mode in Event Bus: thresholds trigger diff downgrades to conserve resources.
- Benchmark Harness: `scripts/perf_bench.py` produces latency & cache efficiency snapshot.

Environment Variables:
| Variable | Default | Description |
|----------|---------|-------------|
| `G6_SERIALIZATION_CACHE_MAX` | 1024 | Max cached payload encodings (0 disables) |
| `G6_SERIALIZATION_CACHE_HASH` | sha256 | Hash mode (sha256|fast) |
| `G6_SSE_EMIT_LATENCY_CAPTURE` | off | Enable serialization latency histogram |
| `G6_EVENTS_BACKLOG_WARN` | 60% max | Backlog size warning threshold |
| `G6_EVENTS_BACKLOG_DEGRADE` | 80% max | Enter degraded mode (diffs replaced) |

Metrics Added:
- `g6_serial_cache_hits_total`, `g6_serial_cache_misses_total`, `g6_serial_cache_evictions_total`, `g6_serial_cache_size`, `g6_serial_cache_hit_ratio`
- `g6_sse_serialize_seconds` (histogram serialization latency)
- `g6_events_backpressure_events_total{reason}` (warn_threshold, enter_degraded)
- `g6_events_degraded_mode` (gauge 0/1)

Operational Flow:
1. Normal: panel_diff events serialized once; cache yields high hit ratio with many subscribers.
2. Warn Threshold: metric increments; monitor capacity planning.
3. Degraded Mode: further panel_diff events replaced by minimal marker payload until backlog recovers.

Benchmark Example:
```powershell
python scripts/perf_bench.py --events 1000 --panel-diffs 200 --subscribers 800 --json
```
Sample Output:
```json
{
  "events": 1000,
  "panel_diffs": 200,
  "subscribers": 800,
  "serialize_p95_ms": 1.4,
  "cache_hit_ratio": 0.82,
  "avg_payload_bytes": 540.0
}
```

Tuning Guidance:
- Increase `G6_SERIALIZATION_CACHE_MAX` if hit ratio < 0.5 and memory headroom available.
- Use `fast` hash mode for lower CPU at small collision risk (suitable when payload variance high and integrity validated elsewhere).
- Set explicit numeric `G6_EVENTS_BACKLOG_WARN/DEGRADE` for deterministic thresholds in load tests.
- Alert on sustained `g6_events_degraded_mode == 1` > 2m (indicates persistent overload or consumer slowness).

Future Extensions:
- Flush latency measurement (publish -> client flush) histogram.
- Adaptive backlog scaling & dynamic degrade exit criteria.
- Memory growth sentinel metrics.


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

Quantile selector: Use `q` (p50,p90,p95,p99) to switch histogram panels to different recording rule series (`<metric>:<quantile>_5m`, `_30m`, `_ratio_5m_30m`). Default p95.

Troubleshooting gating:
| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Expected panel diff counters missing | `panel_diff` not enabled (whitelist) or explicitly disabled | Adjust `G6_ENABLE_METRIC_GROUPS` / `G6_DISABLE_METRIC_GROUPS` |
| `risk_agg_rows` missing in metadata | Neither neutral environment nor `G6_RISK_AGG=1` with group allowed | Clear enable list or enable risk agg group/flag |
| Vol surface interpolation metrics absent | `G6_VOL_SURFACE` unset or group not allowed | Set `G6_VOL_SURFACE=1` and ensure group enabled |
| Per-expiry vol surface metrics absent | `G6_VOL_SURFACE_PER_EXPIRY` unset | Set `G6_VOL_SURFACE_PER_EXPIRY=1` (consider cost) |

Design intent: gating should be transparent (no hidden always‑on surprises) while still allowing the neutral environment to expose a representative sample for metadata validation and documentation generation.

### Panels Runtime Schema & Envelope (2025-10)
Panels emitted by `PanelsWriter` now use a finalized envelope schema (Wave 4 – W4-13). Each panel JSON file has this structure:
```
{
  "panel": "<name>",                # Stable logical panel identifier
  "version": 1,                      # Envelope schema version (increment on breaking change)
  "generated_at": "<ISO8601 Z>",    # File generation timestamp (UTC)
  "updated_at": "<ISO8601 Z>",      # Logical data freshness timestamp (may equal generated_at)
  "data": { ... },                   # Panel payload (object / array / primitive / null)
  "meta": {
    "source": "summary",           # Emission source/subsystem
    "schema": "panel-envelope-v1", # Human-readable schema tag
    "hash": "<sha256-12>"          # First 12 hex chars of sha256 over canonical JSON of `data`
  }
}
```
Key Field Semantics:
* `hash`: Deterministic hash over only the `data` member (sorted keys, compact separators) – excludes timestamps to stabilize across refresh cycles.
* `generated_at` vs `updated_at`: Distinguishes write time from data logical update. They may diverge if a write retries without new data.
* `version`: Governs compatibility. Additive, backward-compatible fields do not require a bump; removals or semantic shifts do.
* `meta.schema`: Descriptive label; tooling should primarily rely on `version`.

#### Legacy Plain Format & Compatibility
Earlier plain files (`<panel>.json`) either exposed raw fields or an early wrapper `{panel, updated_at, data}` without `version/meta`. Legacy emission is disabled by default; to temporarily dual-write for rollback safety:
```
G6_PANELS_LEGACY_COMPAT=1
```
This writes both `<panel>.json` (legacy) and `<panel>_enveloped.json`. The flag will be removed after the deprecation window; consumers must migrate to the enveloped form immediately.

#### Validation Modes (env `G6_PANELS_VALIDATE`)
| Value  | Behavior | Notes |
|--------|----------|-------|
| off    | Skip runtime JSON Schema validation | Fastest path (no protection) |
| warn   | Validate each panel; log warning if invalid | Default when unspecified / unknown value |
| strict | Validate; raise `ValueError` on the first invalid panel | Fails summary loop early |

Envelope Schema Fields (panel-envelope-v1):
| Field        | Type      | Req | Description |
|--------------|-----------|-----|-------------|
| panel        | string    | yes | Stable panel identifier |
| version      | integer   | yes | Envelope version (1) |
| generated_at | string    | yes | File generation timestamp (UTC ISO8601) |
| updated_at   | string    | yes | Logical data update timestamp (UTC ISO8601) |
| data         | any JSON  | yes | Panel payload |
| meta         | object    | yes | Metadata container |
| meta.source  | string    | yes | Emission source tag |
| meta.schema  | string    | yes | Schema tag (`panel-envelope-v1`) |
| meta.hash    | string    | yes | 12-hex sha256 prefix of canonical data |

Operational Examples:
```
G6_PANELS_VALIDATE=strict python -m scripts.summary.app --refresh 1
G6_PANELS_LEGACY_COMPAT=1 python -m scripts.summary.app --refresh 1   # temporary dual write
```

Operational Guidance:
* Prefer enveloped files exclusively; do not rely on implicit fallback to legacy names.
* Use `meta.hash` (or manifest) for change detection instead of full diff.
* Tests can assert parity between legacy and enveloped payloads under the compat flag (see `tests/test_panels_enveloped_only.py`).

Future Enhancements (candidates):
* Optional compression (`meta.encoding`, `data_b64`).
* Digital signatures / provenance chain.
* Incremental delta emission referencing prior `hash` lineage.

Implementation details from earlier wrapper design remain (manifest integrity hashing); only new fields (`version`, `generated_at`, `meta.*`) were added.

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

## Runtime Benchmark & P95 Regression Alert (Wave 4 – W4-09 / W4-10)
Continuous micro-benchmarks (legacy vs pipeline collectors) can be enabled to emit latency delta gauges:
```
G6_BENCH_CYCLE=1 G6_BENCH_CYCLE_INTERVAL_SECONDS=300 python -m scripts.summary.app --refresh 1
```
Key Gauges: `g6_bench_delta_p50_pct`, `g6_bench_delta_p95_pct`, `g6_bench_delta_mean_pct` plus absolute legacy/pipeline p50/p95.

Configure a p95 regression alert threshold (percentage):
```
G6_BENCH_P95_ALERT_THRESHOLD=25
```
This emits gauge `g6_bench_p95_regression_threshold_pct` consumed by Prometheus alert `BenchP95RegressionHigh`:
```
(g6_bench_delta_p95_pct > g6_bench_p95_regression_threshold_pct) and (g6_bench_p95_regression_threshold_pct >= 0)
```
Fires (warning) after 5m sustained breach. See `OPERATOR_MANUAL.md` (section 13.7) and `PIPELINE_DESIGN.md` (8.3.2) for deeper guidance.

Alert Validation: `tests/test_bench_p95_regression_alert_rule.py` enforces presence, expression tokens, and `for: 5m` duration to prevent drift.

Testing References:
* `tests/test_bench_cycle_integration.py` – periodic benchmark emission.
* `tests/test_bench_threshold_gauge.py` – threshold gauge & delta comparison.
* `tests/test_bench_alert_rule_present.py` – alert rule YAML presence & expression.

## Panel Read Performance Benchmark (Wave 4 – W4-19)
Lightweight benchmark measuring JSON read+parse latency for all `*_enveloped.json` panels.

Usage:
```
python scripts/bench_panels.py --panels-dir data/panels --iterations 50 --json
```
Output (saved to `panels_bench.json` by default) schema:
```
{
  "panels_dir": ".../data/panels",
  "iterations": 50,
  "generated_at": "<ISO8601>",
  "missing_read_errors": 0,
  "panels": {
    "indices_panel_enveloped.json": {"count": 50, "mean_s": 0.00012, "p95_s": 0.00021, "min_s": 0.00010, "max_s": 0.00025},
    "alerts_enveloped.json": { ... }
  },
  "aggregate": {"samples": 250, "mean_s": 0.00014, ... }
}
```
Intended for regression detection after envelope/schema or payload size changes. Integrate into CI by asserting `aggregate.p95_s` below a guardrail.

Test Reference: `tests/test_panels_perf_benchmark.py` (schema invariants).

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

### Explorer Enhancements (Phase 8)
#### 1. Overlay Toggle
Overlay toggle: Set the `overlay` variable to `on` to inject a 30s short-window rate target (refId C) alongside raw & 5m rate for faster responsiveness (approximation of near-real-time trend). Default is `off` (no extra query load).

#### 2. Quantile Summary Panel
Quantile summary: A compact table panel (`$metric_hist $q summary (5m vs 30m)`) lists last pXX 5m value, 30m value, and 5m/30m ratio for selected histogram metrics (repeats per selection).

The ratio timeseries panel has been collapsed into the summary table: it now includes 5m, 30m, ratio, and delta ((5m-30m)/30m) with color thresholds (ratio >1.2 red, <0.8 green, mid neutral).
