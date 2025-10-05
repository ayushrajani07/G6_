# G6 Platform Future Enhancements & Implementation Roadmap

_Last updated: 2025-09-29_

This document consolidates the platform assessment and provides a structured, actionable roadmap to improve efficiency, robustness, scalability, and user/developer experience. It has been de-duplicated (previous refocused header & repeated change log entries removed for clarity).

---
## 1. Current Strengths Snapshot
- Clear modular intent: providers, collectors, analytics, storage, metrics, health, console UX.
- Extensive Prometheus metrics (rich dimensionality, forward-compatible labeled families).
- Adaptive memory pressure scaffolding + resilience primitives (circuit breakers, retries, mock provider).
- Backward-compatible config evolution + strong architectural documentation.

## 2. Recently Completed Milestones (Context)
The following were completed and are no longer roadmap items (retained briefly for historical continuity):
- Parallel per-index collection (experimental) with metrics & timeouts
- Cycle SLA breach + data gap + missing cycle detection metrics
- Junk row suppression (threshold + stale + whitelist + per-leg thresholds)
- Expiry misclassification detection instrumentation (canonical mapping + metrics + skip/debug flags)
- Event log subsystem with sampling & tail queries
- Environment & config documentation governance (zero undocumented baseline)
- Metrics doc unification / build info gauge
- Adaptive strike scaling (initial heuristic + scale factor gauge)
- Integrity checker & missing cycles counter
- Composite provider failover + fail-fast flag
- Domain model layer + snapshot cache HTTP endpoint
- Cardinality guard (series-based disable + re-enable hysteresis)
- Developer automation (dev_tasks, pre-commit, secret scanning)
 - Panel diff runtime integration (automatic diff/full artifact emission behind `G6_PANEL_DIFFS`)
 - Provider capability validation (`G6_CONFIG_VALIDATE_CAPABILITIES`)
 - SBOM generation + pip audit gating (supply chain hardening)
 - Integrity auto-run hook (`G6_INTEGRITY_AUTO_RUN` / `G6_INTEGRITY_AUTO_EVERY`)
 - Adaptive alerts severity phases & follow-up guard extensions (multi-phase delivery 2025-09-27)

## 2.a Pre-Market Sanity Checklist (Operational Gate)

Purpose: Fast, deterministic go/no‑go signal before enabling full market hour collection. Automate sequentially (future: `scripts/pre_market_check.py`) – until then operators can follow manually.

| Step | Check | Command / Source | Pass Criteria | Action if Fail |
|------|-------|------------------|---------------|---------------|
| 1 | Config loaded | Startup log | No ERROR about config / index_params present | Fix path / JSON syntax |
| 2 | Metrics server | Log: "Metrics server started" | URL responds 200 | Free port / restart |
| 3 | Catalog HTTP | Log: catalog_http serving | Port bound | Confirm env flags |
| 4 | Cycle duration headroom | First 2 cycles vs interval | duration < 0.5 * interval | Tune parallel/interval |
| 5 | Per-index success | Logs contain collection for each index | No index missing twice | Inspect provider creds |
| 6 | Data Quality baseline | status JSON / dashboard | DQ scores non-null, > threshold | Provider feed / validation modules |
| 7 | Alerts noise | data/panels/alerts_log.json | <10 alerts on boot (expected synthetic <=1) | Investigate duplication thresholds |
| 8 | Memory tier | status.memory.rss_mb | < mem.tier2.mb (thresholds registry) | Restart / investigate leak |
| 9 | Disk writable | data/ directory updated timestamps | New alerts_log.json & panel outputs written | Fix permissions / disk space |
| 10 | Parallel safe | Compare cycle time with/without --parallel | Parallel adds <30% duration | Disable parallel for session |
| 11 | Expiry coercions | WARN lines about expiry tokens | Coercions < expected (document baseline) | Update provider / mapping logic |
| 12 | Retry/backoff health | Metrics: error counters stable | No rapid growth in collection_errors_total | Inspect provider latency / circuit breaker |

Automation Plan:
1. Implement `scripts/pre_market_check.py` reading metrics endpoint + latest status file.
2. Aggregate failures into single summarized table with exit code 2 on failure.
3. Optional flag `--auto-fix-expiry` to precompute canonical expiries and warm caches.
4. Emit summary event for dashboard if any soft warnings remain.

Operator Quick Run (manual current):
```
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 2 --parallel --auto-snapshots
Invoke-WebRequest http://127.0.0.1:9108/metrics | Select-Object -ExpandProperty StatusCode
Get-Content data\panels\alerts_log.json -TotalCount 40
```

Add checklist updates to ops runbook when automated script lands.
## 3. Remaining Key Gaps (Post-Cleanup)
| Theme | Gap | Impact |
|-------|-----|--------|
| Orchestrator Migration | Legacy loop & new loop coexist; duplicated logic paths | Higher maintenance & drift risk |
| Expiry Canonicalization | Detection only; no rewrite/quarantine policy | Persistent anomaly ingress |
| Data Lifecycle | Retention pruning & full quarantine indexing incomplete (compression & partial retention now present) | Storage growth & forensic clutter |
| Advanced Analytics | Remaining: richer risk aggregation plugins, model hooks | Limited insight for advanced strategy eval |
| Cardinality Evolution | Hysteresis polish & UI exposure for detail modes pending | Potential observability mode churn |
| Pipeline Default | Pipeline collector behind flag | Cannot deprecate legacy complexity |
| Event→Panel Wiring | Event-driven diffs emitted; subscription/UI push path pending | Residual latency & redundant polling |
| Security Hardening | Remaining: dependency drift report, secret scan enforcement in CI, SBOM publishing/signing | Residual supply chain exposure |
| Config Schema | Core + provider capability validation done; advanced semantic checks (expiry ordering, strike step heuristics) pending | Edge misconfigs may slip through |
| Adaptive Controller | Core multi-signal + severity feedback delivered; advanced reinforcement logic pending | Suboptimal long-horizon tuning |
| Integrity Expansion | Auto-run implemented; remediation actions & anomaly auto-suppression pending | Gaps detected but not auto-mitigated |
| Snapshot Consistency | Cache & panels converging; single authoritative snapshot abstraction not finalized | Divergent operator views |
| Test Coverage | Boundary expiry, retention pruning stress, panel diff latency benchmarks pending | Regression risk |

_Table notes_: Rows updated 2025-09-27 to reflect partial completion of security, config schema, integrity, panel diff wiring, adaptive controller, and cardinality detail mode milestones delivered in recent sprint.

## 4. Strategic Pillars (Refined)
1. Orchestrator Convergence & Legacy Loop Removal
2. Canonical Data Integrity (auto correction + quarantine)
3. Multi-Signal Adaptive Performance & Graceful Degradation
4. Unified Observability (event-driven panels + advanced analytics)
5. Secure & Predictable Configuration (schema + supply chain)
6. Sustainable Metrics & Cardinality (tiered detail modes)
7. Data Lifecycle & Storage Efficiency (compression, retention, quarantine audit)
8. Extensibility & Provider Capability Abstraction

## 5. Implementation Tracks
### 5.1 Orchestrator Convergence
Goal: Make new loop default; retire legacy.
Actions:
1. Feature parity audit matrix (market gating, adaptive scaling, failover, panel writes, metrics markers).
2. Add warning when legacy path used; schedule removal (2 release horizon).
3. Snapshot parity test harness (legacy vs new) with golden JSON.
4. Remove legacy loop after test green window (2 weeks).
Exit: `run_loop` default; no legacy imports; docs updated.

Status (2025-09-27) Summary:
- Legacy loop removed (2025-09-28); former gating flag `G6_ENABLE_LEGACY_LOOP` retired.
- Majority of tests migrated to orchestrator fixtures.
- Max cycles alias resolved: orchestrator loop honors `G6_MAX_CYCLES` while preferring `G6_LOOP_MAX_CYCLES` (parity matrix row now ✅).
- Removal readiness checklist: `docs/legacy_loop_removal_checklist.md` kept current.
Remaining: dashboard panel diff parity (event-driven mode), prune residual opportunistic imports; transition deprecation row to "REMOVAL SCHEDULED" once two green windows complete (DEPRECATIONS.md updated 2025-09-27). Basic panel status parity (one-cycle structural) now enforced via `tests/test_panel_status_parity.py`.

Removal target: R+1 (pending parity stability window).

### 5.2 Expiry Canonicalization Remediation
Goal: Rewrite or quarantine misclassified rows (beyond detection).
Actions: canonical registry, policy env `G6_EXPIRY_MISCLASS_POLICY` (rewrite|quarantine|reject), quarantine dir + counter `g6_expiry_quarantined_total`, daily summary event.
Exit: Misclassification counter near zero under rewrite.

### 5.3 Multi-Signal Adaptive Controller
Signals: SLA breach streak, memory tier, series count, misclassification spikes.
Outputs: scale factor, detail mode (full/band/agg), strike window bounds.
Metrics: `g6_adaptive_controller_actions_total{reason,action}`.
Exit: Synthetic stress maintains SLA & retains at least band mode.

### 5.4 Event-Driven Panel Diffs
Diff emitter subscribed to cycle_end / anomalies; write diff JSON + periodic full snapshots.
Metrics: `g6_panel_diff_bytes_total`, `g6_panel_full_bytes_total`.
Exit: p95 panel latency <1s; >40% disk write reduction.

**Display facilitator decision (2025-09-28):** extend the existing terminal summary (`scripts/summary_view.py`) with an SSE consumer mode. This keeps the low-latency Rich/TTY dashboard as the primary operator touchpoint while reusing its mature formatting logic. Additional adapters (e.g., web dashboards) can attach later via the same SSE feed without changing producers.

**Event transport plan:** deliver EventBus + SSE in the current milestone with all outward-facing timestamps normalized to Asia/Kolkata (IST) before emission so every frontend renders consistent clocks. A WebSocket control/bi-directional channel remains a future enhancement; capture requirements but defer implementation until after SSE rollout stability.

#### Unified Push-Based Observability (SSE EventBus Integration Summary – 2025-09-28)
This section embeds the comprehensive architectural & implementation summary of the newly delivered push-based panel update stack (sourced from the prior full engineering response) for future reference.

1. Objective & Rationale
	- Reduce operator latency and redundant file polling via real-time streaming while reusing the mature terminal summary renderer.
	- Establish a single producer→EventBus→multi-consumer pattern enabling incremental addition of web/demo clients without touching producers.
	- Enforce global time normalization (IST) at emission for consistency across all frontends.

2. Delivered Components
	- EventBus: In-process deque ring buffer (bounded) with per-event IST timestamp, sequence IDs, optional coalescing key (currently for `panel_full`).
	- Panel Producers: `panel_full` (bootstrap, coalesced) + `panel_diff` events emitted at diff/full artifact generation sites (diff runtime integration complete).
	- SSE Endpoint `/events`: Supports backlog replay (`backlog`), type filtering (`types` query), resume (`Last-Event-ID` / `last_id`), heartbeats (comment frames), and client retry hints.
	- Terminal SSE Client: Added `--sse-url`, `--sse-types`; background reader with exponential backoff + resume, robust frame parsing, diff merge on top of last full snapshot, generation tracking.
	- Documentation: Decision rationale (terminal as facilitator) & WebSocket deferral captured; time normalization policy noted.
	- Tests: Coalescing (latest `panel_full` only), IST offset correctness, SSE backlog replay ordering.

3. Architectural Traits
	- Coalescing Strategy: Only most recent snapshot retained to cap memory while ensuring fast bootstrap; diffs accumulate transiently until next full.
	- Extensible Envelope: Future event families (severity_update, severity_resolved, followup_alert, adaptive_action, risk_agg_update, provider_failover, remediation_result, integrity_anomaly) will reuse the same schema (type, data, timestamp_ist, id, seq).
	- Resilience: Client reconnect logic with Last-Event-ID ensures minimal data loss; heartbeats prevent idle timeouts.
	- Time Discipline: Outward-facing timestamps pre-normalized to IST, avoiding per-client conversion complexity.

4. Pending / Planned Enhancements
	- Emit remaining domain events (severity lifecycle → explicit streaming, follow-up weight & suppression events, adaptive controller actions, risk & surface quality deltas, expiry remediation outcomes, provider failover, integrity anomalies).
	- Event metrics & introspection: publish counters (per-type), backlog utilization gauge, active consumers gauge, `/events/stats` endpoint JSON.
	- Snapshot Guard: On reconnect, validate generation; if mismatch or missing baseline, force new `panel_full` before applying queued diffs.
	- Backpressure Controls: Adaptive backlog trimming & per-type retention ceilings; optional high-frequency type throttling.
	- Additional Clients: Static HTML EventSource demo, piping/tee tool, optional file sink, later WebSocket control plane (pause/resubscribe, filter mutation).
	- Test Expansion: Stress (burst diffs), resume-after-gap, out-of-order diff safeguarding, list/complex structure merge correctness, churn & flapping connection scenarios.

5. Guiding Principles
	- Event payloads remain minimal & semantic (no pre-rendering); formatting stays client-side.
	- Add new event types instead of overloading existing ones; maintain backward compatibility.
	- Instrument everything before scaling producer variety or rate.
	- Operator-first ergonomics: terminal summary is canonical real-time view; others additive.
	- Consistency & determinism: strict timestamp, sequence ordering, and predictable coalescing semantics.

6. Baseline Completion Criteria (Push Stack)
	- Streaming includes panel + severity + follow-up + provider failover events reflected live in terminal (no polling fallback required for those domains).
	- Event metrics exported; `/events/stats` returns backlog size, per-type counts, active connections.
	- Reconnect + resume tests green (including forced mismatch path).
	- p95 end-to-terminal render latency < 1s under synthetic diff burst without unbounded backlog growth.

7. Explicit Deferrals
	- WebSocket bi-directional control & dynamic subscription mutation mid-connection.
	- Persistent event store / multi-process distributed bus.
	- Historical replay beyond in-memory ring buffer window.

Note: Future deep dives (design evolution, distributed fan-out, retention policies) should migrate to a dedicated `docs/design/push_observability.md`; this inline section is a frozen snapshot for roadmap traceability.


### 5.5 Cardinality Detail Modes
Introduce `g6_option_detail_mode{index}`: full=0, band=1, agg=2.
Guard demotes rather than disables; restore after hysteresis window.
Exit: Under series explosion test system auto-demotes and later recovers.

### 5.6 Advanced Analytics & Risk
Deliver IV iterations histogram (`g6_iv_iterations_histogram`), volatility surface JSON, risk aggregation (banded Greeks sum), plugin registry.
Exit: Surface & risk metrics visible; plugin example test passes.

### 5.7 Data Lifecycle & Storage
Compression (previous day gzip), retention policy config, quarantine indexer CLI, nightly integrity auto-run.
Metrics: `g6_compressed_files_total`, implement `g6_retention_files_deleted_total`.
Exit: Optional retention toggled w/out test regressions; storage growth curve flattened.

### 5.8 Security & Supply Chain
CI SBOM (cyclonedx), `pip-audit` gating (HIGH severity fail), dependency drift report, secret scan enforcement.
Exit: Build fails on unreviewed high vulnerabilities; SBOM artifact downloadable.

### 5.9 Config Schema Hardening
Add strike step bounds, provider capability validation, expiry ordering semantic checks, structured error codes.
Exit: New tests cover each invalid case; schema rejects them.

### 5.10 Test Suite Expansion
Add: expiry edge cases, cardinality mode transitions, adaptive multi-signal harness, panel diff latency test, quarantine rewrite test.
Exit: Coverage to 70% core; all new features guarded.

### 5.11 Deprecations & Cleanup
Introduce `DEPRECATIONS.md`; warn on deprecated flags; removal schedule documented.
Exit: No internal references remain to deprecated helpers.

## 6. Revised 90-Day Roadmap
| Phase | Weeks | Focus | Deliverables |
|-------|-------|-------|--------------|
| 1 | 1–3 | Orchestrator + Canonicalization | New loop default, rewrite/quarantine, parity tests |
| 2 | 4–6 | Adaptive + Cardinality Modes | Multi-signal controller, detail mode metrics |
| 3 | 7–9 | Event Panels + Analytics | Panel diffs, IV histogram, vol surface stub |
| 4 | 10–12 | Lifecycle + Security | Compression, retention, SBOM, audit gating |
| 5 | 13 | Cleanup & Deprecation | Legacy removal, DEPRECATIONS.md |

## 7. Metrics Backlog (Remaining / New)
| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| g6_expiry_quarantined_total | Counter | index,expiry_code | Rows quarantined (misclassification) |
| g6_adaptive_controller_actions_total | Counter | reason,action | Scaling/mode decisions |
| g6_option_detail_mode | Gauge | index | Detail tier (0/1/2) |
| g6_panel_diff_bytes_total | Counter | index | Bytes written (diff) |
| g6_panel_full_bytes_total | Counter | index | Bytes written (full) |
| g6_compressed_files_total | Counter | type | Files compressed |
| g6_quarantine_scan_seconds | Histogram | type | Quarantine scan latency |
| g6_iv_iterations_histogram | Histogram | index,expiry | IV iteration distribution |

## 8. KPIs (Adjusted)
| KPI | Target |
|-----|--------|
| Legacy loop removal | End Phase 1 |
| Misclassification residual | <1/day post remediation |
| Avg cycle time (4 indices) | <0.65 * interval |
| Panel latency p95 | <1s |
| Detail continuity under stress | >= band mode |
| Storage growth (compressed) | <50% uncompressed baseline (14d) |
| High severity vulns | 0 (fail build) |
| Coverage (lines) | 70% by Phase 3 |

## 9. Next Immediate Action
Legacy loop deprecation sequence: emit deprecation warning on import/use, add `DEPRECATIONS.md` entry, schedule removal after 2 green releases with parity harness confidence.

## 10. Change Log (Roadmap)
2025-09-26: Refocused roadmap replacing completed hygiene and instrumentation items with forward-looking convergence, remediation, adaptive control, event-driven panels, lifecycle, and security tracks.
2025-09-26: Added expiry remediation scaffolding: metrics (`g6_expiry_quarantined_total`, `g6_expiry_rewritten_total`, `g6_expiry_rejected_total`, `g6_expiry_quarantine_pending`), env flags (`G6_EXPIRY_MISCLASS_POLICY`, `G6_EXPIRY_QUARANTINE_DIR`, `G6_EXPIRY_REWRITE_ANNOTATE`) and policy placeholders in `csv_sink` (no enforcement yet).
2025-09-26: Expiry remediation policy ENFORCED (rewrite|quarantine|reject) with quarantine ndjson emission & counters; legacy G6_EXPIRY_MISCLASS_SKIP treated as reject alias.
2025-09-26: Orchestrator parity harness added (`src/orchestrator/parity_harness.py`, test `tests/test_orchestrator_parity.py`) producing normalized legacy vs new loop snapshots; environment flag `G6_REGEN_PARITY_GOLDEN` documented for golden regeneration.
2025-09-26: Legacy loop deprecation warning inserted (one-time) in `unified_main.collection_loop`; suppression flag `G6_SUPPRESS_LEGACY_LOOP_WARN` added. 2025-09-28: loop & both flags removed.
2025-09-27: Orchestrator parity matrix updated (max cycles alias row ✅); DEPRECATIONS.md annotated with alias resolution and updated date.
2025-09-27: Added basic panel status parity test (`tests/test_panel_status_parity.py`) validating indices list + structural meta fields between legacy and orchestrator one-cycle snapshots.
2025-09-26: Orchestrator startup migration began: added `scripts/run_orchestrator_loop.py` (preferred entry) using `run_loop`; implemented `G6_LOOP_MAX_CYCLES` for bounded dev/test runs; documented env and added tests (`test_orchestrator_loop_max_cycles.py`).
2025-09-26: Developer tooling migration: `dev_tools.py` run-once/dashboard now use orchestrator cycle (no unified_main import); `run_live.py` marked deprecated (warns, points to run_orchestrator_loop); `start_mock_mode.ps1` updated to invoke orchestrator loop runner.
 - 2025-09-26: Junk filtering enhancement implemented (threshold + stale + whitelist + periodic summary) with metrics (`g6_csv_junk_rows_skipped_total`, `g6_csv_junk_rows_threshold_skipped_total`, `g6_csv_junk_rows_stale_skipped_total`) and environment controls (`G6_CSV_JUNK_*`). Added tests for stale, whitelist bypass, variants, summary emission. Added pruning heuristic for stale signature map.
 - 2025-09-26: Parallel per-index execution (experimental) added to `run_cycle` with env flags `G6_PARALLEL_INDICES` / `G6_PARALLEL_INDEX_WORKERS` and metrics (`g6_parallel_index_workers`, `g6_parallel_index_failures_total`). Test `tests/test_parallel_collection.py` added.
 - 2025-09-26: Cycle time histogram metric `g6_cycle_time_seconds` added and instrumented.
 - 2025-09-26: Adaptive strike scaling (`G6_ADAPTIVE_STRIKE_SCALING`) with gauge `g6_strike_depth_scale_factor{index}` and test `tests/test_adaptive_strike_scaling.py`.
 - 2025-09-26: Added SLA breach detection metric `g6_cycle_sla_breach_total` (env `G6_CYCLE_SLA_FRACTION`, default 0.85) and data gap gauges `g6_data_gap_seconds` (global) + `g6_index_data_gap_seconds{index}`.
 - 2025-09-26: Implemented missing cycles detection inside `run_cycle` storing `_last_cycle_start` and incrementing `g6_missing_cycles_total` when start gap > 1.5 * `G6_CYCLE_INTERVAL`.
 - 2025-09-26: Added IV solver iterations histogram `g6_iv_solver_iterations` alongside existing average gauge; instrumentation in `_iv_estimation_block`.
 - 2025-09-26: Introduced component health gauge `g6_component_health{component}` emitted during status snapshot from health monitor.
 - 2025-09-26: Implemented cardinality guard (`src/orchestrator/cardinality_guard.py`) with env thresholds (`G6_CARDINALITY_MAX_SERIES`, `G6_CARDINALITY_MIN_DISABLE_SECONDS`, `G6_CARDINALITY_REENABLE_FRACTION`); increments `g6_cardinality_guard_trips_total` and sets context flag to disable per-option metrics when exceeded.
 - 2025-09-26: Added context fields for cardinality & per-index success timestamps enabling per-index gap calculation.
 - 2025-09-26: Added `g6_provider_failover_total{from,to}` counter and `CompositeProvider` (`src/providers/composite_provider.py`) enabling sequential failover with optional fail-fast env (`G6_PROVIDER_FAILFAST`) and composite enable flag (`G6_COMPOSITE_PROVIDER`). Added tests `tests/test_provider_failover.py` for success, fail-all, and fail-fast modes.
 - 2025-09-26: Added integrity checker utility `scripts/check_integrity.py` scanning `events.log` for missing `cycle_start` sequence numbers, emitting JSON summary and incrementing `g6_missing_cycles_total` counter when invoked with `--metrics`. Added tests `tests/test_integrity_checker.py` covering no-gap, gap, and missing file scenarios.
 - 2025-09-26: Hardened config schema (`config/schema_v2.json`): added index symbol pattern constraints, expiry date regex, strike bounds, application name pattern, and disabled additional arbitrary index properties. Introduced loader `src/config/loader.py` with normalized emit & strict mode flags (`G6_CONFIG_STRICT`, `G6_CONFIG_EMIT_NORMALIZED`). Added metric `g6_config_deprecated_keys_total{key}` and tests `tests/test_config_validation.py` validating valid config, invalid index key, and deprecated key metric increments.
 - 2025-09-26: Hardened config schema (`config/schema_v2.json`): added index symbol pattern constraints, expiry date regex, strike bounds, application name pattern, and disabled additional arbitrary index properties. Introduced loader `src/config/loader.py` with normalized emit & strict mode flags (`G6_CONFIG_STRICT`, `G6_CONFIG_EMIT_NORMALIZED`). Deprecated keys that were previously counted (e.g., legacy `index_params`) are now hard failures — metric `g6_config_deprecated_keys_total{key}` retained for future soft deprecation modes but currently will not increment because disallowed keys are rejected pre-load. Updated `tests/test_config_validation.py` to assert hard-fail semantics.
 - 2025-09-26: Introduced initial domain model layer (`src/domain/models.py`) with `OptionQuote`, `EnrichedOption`, and `ExpirySnapshot` dataclasses. (Historical note: originally integrated via deprecated `enhanced_collector`; now served by `snapshot_collectors`.) Added tests `tests/test_domain_models.py` validating construction and snapshot option count.
 - 2025-09-26: (Deprecated path) enhanced collector previously returned in-memory `ExpirySnapshot` objects; this capability lives in `snapshot_collectors` after deprecation. Legacy test `tests/test_enhanced_collector_snapshots.py` removed; coverage provided by auto-snapshots test.
 - 2025-09-26: Added snapshot cache (`src/domain/snapshots_cache.py`) gated by `G6_SNAPSHOT_CACHE` and HTTP exposure via `/snapshots` route (same lightweight server as catalog when `G6_CATALOG_HTTP=1`). Added serialization methods to domain models and tests `tests/test_snapshots_http.py` for endpoint & index filtering.
 - 2025-09-26: Added `OverviewSnapshot` aggregate model (totals, crude PCR, placeholder max pain) integrated into snapshot cache serialization (`overview` field in `/snapshots` response) and env flag `G6_AUTO_SNAPSHOTS` to auto-build snapshots each cycle via enhanced collectors.
 - 2025-09-26: Introduced optional HTTP Basic Auth for catalog & snapshots endpoints via `G6_HTTP_BASIC_USER` / `G6_HTTP_BASIC_PASS` (health endpoint excluded) with initial implementation.
 - 2025-09-26: Refined Basic Auth 401 challenge: now emits proper `WWW-Authenticate: Basic realm="G6"` header before ending headers to ensure clients can prompt for credentials.
 - 2025-09-26: Central expiry service integrated behind feature flag `G6_EXPIRY_SERVICE`; roadmap status updated to SERVICE IMPLEMENTED & FLAGGED.
 - 2025-09-26: Environment variable documentation coverage automation added (`tests/test_env_doc_coverage.py`) with baseline file (`tests/env_doc_baseline.txt`), skip & regenerate flags (`G6_SKIP_ENV_DOC_VALIDATION`, `G6_WRITE_ENV_DOC_BASELINE`). Initial undocumented baseline reduced from ~135 → 114 by documenting circuit breaker, cardinality guard, events, bootstrap/orchestrator, provider failover, SLA fraction, parallelism, and calendar alias flags in `docs/env_dict.md`.
 - 2025-09-26: Added cardinality guard env variables (`G6_CARDINALITY_MAX_SERIES`, `G6_CARDINALITY_MIN_DISABLE_SECONDS`, `G6_CARDINALITY_REENABLE_FRACTION`) and documented provider fail-fast (`G6_PROVIDER_FAILFAST`), SLA fraction (`G6_CYCLE_SLA_FRACTION`), parallel workers (`G6_PARALLEL_INDEX_WORKERS`), and calendar alias (`G6_CALENDAR_HOLIDAYS_JSON`).
 - 2025-09-26: Roadmap Testing & Quality Gates section expanded with env var doc enforcement objective (baseline burn-down path).
2025-09-26: Volatility surface coverage metrics: `g6_vol_surface_rows{index,source}` and `g6_vol_surface_interpolated_fraction{index}`.
2025-09-26: Risk aggregation coverage & exposure metrics: `g6_risk_agg_rows`, `g6_risk_agg_notional_delta`, `g6_risk_agg_notional_vega`.
2025-09-26: Instrumentation in `vol_surface.build_surface` and `risk_agg.build_risk` capturing row density, interpolation reliance, and aggregate notionals.
2025-09-26: Documentation updates in `docs/METRICS.md` (Panel Diff & Analytics section) including operational guidance.
2025-09-26: Tests: `tests/test_analytics_depth_metrics.py` validating gauge emission surface-level semantics.

2025-09-27: Follow-on analytics depth enhancements DELIVERED:
- Per-expiry volatility surface metrics gated by `G6_VOL_SURFACE_PER_EXPIRY` (`g6_vol_surface_rows_expiry{index,expiry,source}`, `g6_vol_surface_interpolated_fraction_expiry{index,expiry}`) with instrumentation in `vol_surface.build_surface`.
- Risk aggregation bucket utilization gauge `g6_risk_agg_bucket_utilization` emitted in `risk_agg.build_risk` (fraction of populated buckets).
- Internal `_register` helper introduced in metrics registry to reduce repetitive try/except registration boilerplate; FULL ADOPTION COMPLETED 2025-09-27 across all metric clusters (analytics, panel write/runtime status, panel diff, storage & CSV + junk filtering, field coverage & quality, expiry remediation, labeled errors, deprecation/provider/config, overlay quality, sampling & cardinality guard, parallel collection, SLA/gap/health, memory pressure & Greeks). Remaining follow-ups limited to ordering & minor consolidation (see Tech Debt section).
- Tests: `tests/test_followon_analytics_metrics.py` asserting per-expiry emission (flag on) and bucket utilization gauge presence.
- METRICS.md updated with new section 'Analytics Depth (Vol Surface & Risk Aggregation) – Implemented' including operational PromQL examples.
- Roadmap table 12 updated removing delivered items (see below) and leaving remaining proposed analytics.

Rationale: Provides baseline density & exposure insight enabling future adaptive decisions (e.g., dynamic interpolation throttling if interpolated fraction spikes; risk bucket gap detection if row count unexpectedly drops).
2025-09-27: Extended metric group tagging scaffolding beyond analytics (initial tagging for storage, panel diff; placeholders for parallel, SLA/health, overlay quality) plus environment-driven disable control `G6_DISABLE_METRIC_GROUPS` (documented) enabling coarse-grained observability cardinality reduction. Metrics documentation generator updated to use explicit registry group map and timezone-aware timestamps (no deprecated utcnow usage).
2025-09-27: Storage metrics group ('storage') fully integrated into enable/disable gating (migrated from always-on). Converted storage metric registrations to `_maybe_register('storage', ...)` ensuring they respect `G6_DISABLE_METRIC_GROUPS` / `G6_ENABLE_METRIC_GROUPS` precedence. Updated tests to include 'storage' in controlled groups; all gating scenarios pass (254 passed, 16 skipped). Regenerated metrics docs to reflect new group.
2025-09-27: Storage metrics bulk spec consolidation: replaced individual `_maybe_register` calls with `_bulk_register` spec list (group 'storage'); removed redundant manual tagging loop since group captured automatically.
2025-09-27: Unified metric group filtering logic: introduced `_get_group_filters` + `_group_allowed` helpers used by both `_bulk_register` and `_maybe_register` to eliminate duplicated env parsing, ensuring consistent precedence (allow-list then disable) and simplifying future gating changes.
2025-09-27: Metrics registry incremental improvements: added public `get_metric_groups()`, `reload_group_filters()` (test/debug hook), introspection dump (`G6_METRICS_INTROSPECTION_DUMP` env) and converted additional legacy direct registrations to `_register` helper for uniform idempotency.
2025-09-27: Metrics registry follow-ups implemented: persisted `_g6_group` attribute on metric objects, added `g6_metric_group_state{group}` gauge (1=registered,0=skipped), reload behavior test (`test_metrics_group_reload.py`), state gauge test (`test_metric_group_state.py`), and utility script `scripts/dump_metrics.py` for JSON metadata export.
2025-09-27: Potential Next Steps (partial) IMPLEMENTED: scaffolded proposed metrics (`g6_vol_surface_quality_score`, `g6_vol_surface_interp_seconds`, `g6_vol_surface_model_build_seconds`, `g6_compressed_files_total`, `g6_quarantine_scan_seconds`, `g6_adaptive_controller_actions_total`, `g6_option_detail_mode`) with new `adaptive_controller` group + gating. Added adaptive controller stub module (`src/adaptive/controller.py`) exposing `record_controller_action` and `set_detail_mode` helper functions under env flag `G6_ADAPTIVE_CONTROLLER`. Added tests (`test_adaptive_controller_metrics.py`) for registration & gating, updated `docs/METRICS.md` entries. No production logic yet (metrics remain inert until future controller implementation). Remaining roadmap items unaffected.
2025-09-27: Adaptive multi-signal controller logic IMPLEMENTED (`src/adaptive/logic.py`): evaluates SLA breach streak (`g6_cycle_sla_breach_total`), memory pressure (`g6_memory_pressure_level`), and cardinality guard trips (`g6_cardinality_guard_trips_total`) to demote/promote option detail mode (`g6_option_detail_mode{index}`) with action audit counter `g6_adaptive_controller_actions_total{reason,action}`. Added env thresholds `G6_ADAPTIVE_MAX_SLA_BREACH_STREAK`, `G6_ADAPTIVE_MIN_HEALTH_CYCLES`; integrated into `orchestrator.cycle.run_cycle` after core collection; tests added (`tests/test_adaptive_logic_and_surface_metrics.py`).
2025-09-27: Volatility surface quality & phase timing instrumentation DELIVERED: `vol_surface.build_surface` now emits `g6_vol_surface_quality_score{index}` (heuristic: coverage * (1 - interpolated_fraction)), interpolation latency histogram `g6_vol_surface_interp_seconds`, and placeholder model timing histogram `g6_vol_surface_model_build_seconds` (gated by `G6_VOL_SURFACE_MODEL`). Tests extended to assert quality & interpolation samples; documentation updated (env dict + metrics sections).
2025-09-27: Lifecycle maintenance job STUB ADDED (`src/lifecycle/job.py`): compression simulation (age & extension gated) increments `g6_compressed_files_total{type="option"}` and quarantine directory scan latency observed via `g6_quarantine_scan_seconds`. Environment flags introduced: `G6_LIFECYCLE_JOB`, `G6_LIFECYCLE_COMPRESSION_EXT`, `G6_LIFECYCLE_COMPRESSION_AGE_SEC`, `G6_LIFECYCLE_MAX_PER_CYCLE`, `G6_LIFECYCLE_QUAR_DIR`. Integrated invocation at end of `run_cycle`. Test `tests/test_lifecycle_job.py` validates compression side-effects & histogram observation (with gating-aware skip logic). Future: retention pruning & deletion counter integration.
2025-09-27: Metrics group gating FOLLOW-UP: ensured lifecycle (storage) metrics respect `G6_DISABLE_METRIC_GROUPS` / `G6_ENABLE_METRIC_GROUPS` precedence; lifecycle test adjusted to clear disable list for deterministic registration when required.
2025-09-27: Lifecycle retention pruning IMPLEMENTED: extended lifecycle job with retention window & delete cap envs (`G6_LIFECYCLE_RETENTION_DAYS`, `G6_LIFECYCLE_RETENTION_DELETE_LIMIT`) deleting aged `.gz` artifacts and incrementing `g6_retention_files_deleted_total` (metric attr `retention_files_deleted`). Added safeguard ordering (compression before retention) and per-cycle deletion cap.
2025-09-27: Adaptive controller COOLDOWNS ADDED: new env flags `G6_ADAPTIVE_DEMOTE_COOLDOWN`, `G6_ADAPTIVE_PROMOTE_COOLDOWN` prevent rapid demote/promote flapping; stateful cycle counter & last action cycle tracking integrated into `adaptive.logic` with new tests (`test_adaptive_cooldown.py`).
2025-09-27: Cardinality Detail Modes IMPLEMENTED: integrated adaptive detail modes (full/band/agg) with per-option emission gating in `cardinality_manager.should_emit`. Aggregate mode blocks all per-option metrics; band mode restricts to ATM window using new env `G6_DETAIL_MODE_BAND_ATM_WINDOW`; full mode remains unrestricted. Added tests (`test_cardinality_detail_modes.py`). Roadmap item 5.5 now partially satisfied (remaining: hysteresis polish & panel UI exposure).
2025-09-27: Adaptive Alerts Severity Phase 1 IMPLEMENTED: added severity classification (info|warn|critical) with per-type thresholds (interpolation fraction, risk delta drift pct, bucket utilization low inverted), min streak gating (`G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK`), env rule overrides (`G6_ADAPTIVE_ALERT_SEVERITY_RULES`), and force reclassification flag (`G6_ADAPTIVE_ALERT_SEVERITY_FORCE`). Alerts enriched at emission; panel now exposes `severity_counts` and `by_type_severity`; summary badge augmented with `[C:x W:y]`. Tests added (`test_severity_thresholds.py`, `test_severity_disabled.py`); documentation updated (`METRICS.md` severity section & design doc extract). Future phases (not yet implemented): decay/resolution logic, color palette externalization, controller feedback loop.
2025-09-27: Adaptive Alerts Severity Phase 2 IMPLEMENTED: activated decay & resolution lifecycle. Added per-type decay state with `active_severity` + `last_change_cycle` tracking; enabled multi-step downgrades after `G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES` idle windows (critical→warn→info). Introduced `resolved` flag emitted only on decay transition from elevated (warn/critical) back to info; panel aggregation now includes `resolved_total`. Summary badge now conditionally suppresses severity counts when zero and appends `(stable)` plus resolved count `R:n`. Added tests (`test_severity_decay.py`) covering multi-step decay, inverted rule decay, disabled decay (no resolution), and resolved emission predicate. Updated env docs & design acceptance criteria (Phase 2) in `docs/design/adaptive_alerts_severity.md`.
2025-09-27: Adaptive Alerts Severity Phase 3 IMPLEMENTED: controller feedback integration & palette exposure. Added env flags `G6_ADAPTIVE_CONTROLLER_SEVERITY`, `G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES`, `G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES`. Adaptive controller now demotes detail mode on configured critical severities (reason `severity_critical`) and blocks promotions while configured warn severities persist. Panel `severity_meta` now includes `palette` (color overrides) and `active_counts`. Added helper APIs `get_active_severity_state()`, `get_active_severity_counts()` and test `test_adaptive_severity_controller_integration.py`. Design doc updated to Phase 3 DELIVERED.
2025-09-27: Follow-up Guards SUGGESTED NEXT IMPLEMENTED: Added persistence + panel exposure enhancements to follow-up guard system (`followups.py`). Features: event emission (`followup_alert` via events subsystem), per (index,type,severity) suppression window (`G6_FOLLOWUPS_SUPPRESS_SECONDS`), recent alerts ring buffer with panel integration (`followups_recent`, limit `G6_FOLLOWUPS_PANEL_LIMIT`), rolling weight accumulation window (`G6_FOLLOWUPS_WEIGHT_WINDOW`) with configurable per-type severity weights (`G6_FOLLOWUPS_WEIGHTS`) feeding adaptive controller demotion (`followups_weight` when >= `G6_FOLLOWUPS_DEMOTE_THRESHOLD`), and buffer size control (`G6_FOLLOWUPS_BUFFER_MAX`). New tests `test_adaptive_followups_extended.py` covering suppression, weight accumulation, controller demotion, panel exposure, and event emission. Env docs updated with new variables. This closes Suggested Next scope for follow-up guards.
2025-09-27: Adaptive Alerts Severity Phase 3.1 IMPLEMENTED: severity trend smoothing + theme endpoint. Added env flags `G6_ADAPTIVE_SEVERITY_TREND_SMOOTH`, `G6_ADAPTIVE_SEVERITY_TREND_WINDOW`, `G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO`, `G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO`. Controller uses ratio-based thresholds for critical demotion and warn promotion blocking when smoothing enabled. New HTTP endpoint `/adaptive/theme` serves palette, active_counts, and trend statistics. Tests added (`test_adaptive_theme_endpoint_and_trend.py`). Design doc annotated (Phase 3.1).
2025-09-27: Follow-Up Guards OPTIONAL SCOPE IMPLEMENTED: guard triggers now emit structured alerts (`interpolation_high`, `risk_delta_drift`, `bucket_util_low`) into internal sink drained by orchestrator; alerts enriched with severity (if enabled). Added helper `get_and_clear_alerts()` and debug accessor `get_debug_state()` (flag `G6_FOLLOWUPS_DEBUG`). Documented risk drift sign label semantics (`sign=up|down`) and bucket utilization inverted threshold logic.

2025-09-27: Panel Diff Runtime Integration FINALIZED: integrated `emit_panel_artifacts` invocation directly in `status_writer.write_runtime_status` (diff/full artifacts now emitted automatically when `G6_PANEL_DIFFS` enabled). Added metrics wiring (`panel_diff_writes`, `panel_diff_bytes_*`, truncation counter) already present; docs updated (env_dict) consolidating panel diff flags. No additional tests required beyond existing `test_panel_diffs` & `test_panel_diff_truncation` (validated still green).
2025-09-27: Provider Capability Validation IMPLEMENTED: `G6_CONFIG_VALIDATE_CAPABILITIES` flag triggers post-schema validation check ensuring configured provider names expose required callables (`get_index_data`, `get_option_chain`). Emits aggregated `ConfigValidationError` with codes `E-PROV-NOTFOUND` / `E-PROV-MISSING`. Test `test_config_provider_capabilities.py` added.
2025-09-27: SBOM & pip-audit Gating ADDED: `scripts/gen_sbom.py` generates CycloneDX-style JSON (rich if cyclonedx library present, fallback minimal). `scripts/pip_audit_gate.py` enforces max allowed severity (`G6_PIP_AUDIT_SEVERITY`, default HIGH) with ignore list support. Tests `test_sbom_and_pip_audit.py` cover generation & gating pass/fail logic. New envs documented (SBOM hash toggle, pip audit severity/ignore).
2025-09-27: Integrity Auto-Run HOOK: Added optional end-of-cycle integrity checker invocation (`G6_INTEGRITY_AUTO_RUN` + `G6_INTEGRITY_AUTO_EVERY`, default 60) writing `logs/integrity_auto.json`. Test `test_integrity_autorun.py` validates periodic execution with modulus=1.

## 12. Immediate Next Analytics Iteration (Proposed)
| Item | Description | Objective | Metric Impact | Priority |
|------|-------------|-----------|---------------|----------|
| Per-Expiry Surface Stats | (DELIVERED 2025-09-27) | – | – | – |
| Surface Quality Score | Derive quality heuristic (e.g., (raw_rows/total_rows)*weight - empty_strikes_penalty) | Alerting on deterioration | `g6_vol_surface_quality_score{index}` | Medium |
| Risk Bucket Utilization | (DELIVERED 2025-09-27) | – | – | – |
| Per-Index Risk Notionals | Add index label to risk notionals (behind env) once multi-index aggregation introduced | Break out exposures by index | Extend existing gauges with index label (opt-in) | Low |
| Interpolation Latency Split | Histogram of interpolation time vs raw aggregation time | Performance tuning | `g6_vol_surface_interp_seconds` (histogram) | Low |
| SABR / Model Hooks Scaffold | Pluggable model interface + timing histograms | Future advanced modeling | `g6_vol_surface_model_build_seconds` | Low |

## 13. Forward-Looking Adaptive Use Cases
1. Interpolation Guard: If `g6_vol_surface_interpolated_fraction` > configurable threshold (e.g., 0.6) for N builds, reduce interpolation density or log anomaly event.
2. Risk Exposure Drift: Alert when abs(Δ `g6_risk_agg_notional_delta`) over rolling 5m window exceeds X% while option count stable (potential pricing/glitch).
3. Bucket Coverage Alert: Once bucket utilization metric added, fire warning when utilization < 70% for consecutive 10 minutes (liquidity thinning / config mismatch).

## 14. Tech Debt / Cleanup Follow-Ups
- (Completed 2025-09-27) Vol surface emission consolidation: single emitter in `vol_surface.build_surface` handles global + per-expiry + late-binding removal of duplicate blocks.
- (Completed 2025-09-27) Metrics registry reordering: analytics depth (vol surface + risk aggregation) moved adjacent to performance/build latency metrics for discoverability.
- (Completed 2025-09-27) Bulk registration helper `_bulk_register` introduced enabling declarative metric spec lists (initially applied to analytics depth families).
- (Completed 2025-09-27) Declarative spec collapse for volatility surface & risk aggregation metrics; attribute names preserved for test stability.
- (Completed 2025-09-27) Full adoption of `_register` helper; all legacy try/except blocks removed (no remaining ad-hoc duplicates). Residual tidy opportunities: optional grouping of remaining heterogeneous sections and doc generation script.
- (Completed 2025-09-27) Metric group tagging added (groups: `analytics_vol_surface`, `analytics_risk_agg`) with env-driven disable list `G6_DISABLE_METRIC_GROUPS` processed during bulk registration to skip entire spec families.
- (Completed 2025-09-27) Auto-generated metrics documentation script (`scripts/gen_metrics_docs.py`) producing `docs/metrics_generated.md` enumerating all registered metrics (name, type, labels, help, inferred group). Initial version infers groups by name pattern; future enhancement may persist explicit group metadata on metric objects to avoid inference.
- (Completed 2025-09-27) Extended group tagging to storage, panel_diff, parallel, SLA/GAP, overlay_quality and implemented complementary allow-list `G6_ENABLE_METRIC_GROUPS` with precedence (disable list wins on overlap).

## 15. Acceptance Criteria for Next Merge Window
- No duplicate metric registration exceptions with optional per-expiry analytics flag toggled on/off repeatedly during a single process run.
- New metrics documented + test coverage asserting label cardinality gating when env disabled.
- Alert playbooks updated referencing new quality / utilization metrics.

## 16. Adaptive Alerts Severity & Color Mapping (Design Doc Extract)
Detailed design moved to `docs/design/adaptive_alerts_severity.md`.

Summary: Introduce configurable severity (info/warn/critical) classification for adaptive alerts with panel enrichment (severity_counts, per-type severity stats) and summary badge augmentation, behind `G6_ADAPTIVE_ALERT_SEVERITY` flag. Defaults include numeric thresholds per alert type; overrides supported via JSON env. No new Prometheus metrics phase 1 (panel/UI only). Future phases: decay, resolved state, possible adaptive controller feedback loop. See design doc for rules, data model, env vars, rollout plan, and acceptance criteria.
Operator Quick Reference: `docs/cheatsheets/adaptive_alerts_badge.md` covers badge formatting, resolved lifecycle, and tuning cues.

