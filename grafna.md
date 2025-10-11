# Grafana / Metrics Strategy Roadmap

(Refreshed after repository scan on 2025-10-05)

## Core Principle
Separate operational Prometheus metrics (low/medium cardinality) from high-cardinality option chain data (delivered via streaming / query layer). Prometheus for health, aggregates, distributions—not every option contract.

## Immediate Improvements (Status After Scan)
1. Metric specification layer (YAML) -> generate code + docs. **DONE** (base spec `metrics/spec/base.yml`, generated accessors, provenance hash gauges). Dashboard seeds now committed and expanded.
2. Unified metric factory & cardinality guard; emit self-metrics for series counts. **DONE** (registry + guard metrics + growth diagnostics & alert rules present).
3. Structured emission scheduling (batch/handoff). **PARTIAL** (counter batching via `emission_batcher`; pending: histogram pre-aggregation, adaptive flush sizing, async producer/flush separation).
4. Auto-doc generation & drift check in CI. **DONE** (generation scripts + duplicate/fail-fast + spec/build hash governance). Catalog wording still references `spec.py` instead of YAML (docs cleanup pending).
5. Panel template generation from spec. **PARTIAL → EXPANDED** (multiple committed dashboard JSONs; generator currently covers option chain + governance; many additional domain dashboards are curated manually pending generator generalization).
6. Error-tolerant wrappers with rate-limited logging. **DONE** (`safe_emit` decorator + `g6_emission_failures_total`, `g6_emission_failure_once_total`).

## Future Option Chain Path
Introduce dual path: streaming bus (NATS/Redis/Kafka) + column/time-series store (ClickHouse/Timescale). Grafana uses plugin for historical queries; Live/WebSocket for near-ATM window.

## Data Modeling Guidelines
- Avoid per-contract labels in Prometheus.
- Bucket by moneyness, time-to-expiry.
- Version histogram buckets.
- Warm initialize metrics to avoid panel gaps.

## Migration Phases (Updated Reality)
0. Current foundation complete. **DONE**
1. Spec + generator. **DONE**
2. Aggregated chain metrics. **DONE (metrics + seed)** (generated dashboard `grafana/dashboards/generated/option_chain.json` present; panels cover OI, volume, IV, spread, listings; future enhancement: latency & provider health overlays).
3. Streaming bus. **NOT STARTED** (only in-process bus metrics, no external streaming infra yet).
4. Column Store Integration. **PLANNING** (metrics skeleton + tests; see `COLUMN_STORE_INTEGRATION.md`; ingestion pipeline tests exist but no deployed store adapter).
5. Live narrow slice (ATM window). **NOT STARTED**
6. Historical replay & advanced analytics. **NOT STARTED**

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Cardinality explosion | Strict spec + guard + pre-aggregation |
| Scrape latency spikes | Batching + snapshotting |
| Silent metric failures | Safe wrapper w/ once-per-signature logging |
| Drift dashboard <-> code | Generated panels & spec hash |
| Data gaps in fallback | Stub emits baseline counters |

## First Concrete Steps
- Create `metrics/spec/base.yml`. **DONE**
- Implement `scripts/gen_metrics.py` -> outputs `src/metrics/generated.py` & `METRICS_CATALOG.md`. **DONE**
- Add `src/metrics/cardinality_guard.py` with series budget enforcement. **DONE** (extended with growth diagnostics & fail-fast duplicate option)
- Refactor a pilot file (`providers_interface.py`) to use generated accessors. **PARTIAL** (multiple modules now using accessors; need explicit audit of remaining direct client uses)

## Added (Post-Roadmap) Governance Enhancements
- Spec & build/config hash metrics with provenance embedding in generated artifacts.
- Duplicate registration counter + optional fail-on-duplicate env flag.
- Cardinality growth diagnostic metrics + alert rule.
- Import latency benchmarking harness.
- Domain grouped spec migration (risk aggregation & vol surface) with env-gated predicates.
- Emission batching layer (counters) with utilization & queue depth internal metrics (see `src/metrics/emission_batcher.py`).

## Prometheus Rule / Alert Coverage Snapshot (Not Previously Summarized)
Recording & alert rules now implemented beyond initial roadmap description:
- Health score aggregation & degradation alerts (`g6:aggregated_health_score`, warning/critical thresholds).
- Memory pressure multi-layer recording + transitions + downgrade + actions + flapping alerts.
- Panel diff vs full bytes efficiency & diff generation mismatch / need_full / recovery / latency staging metrics.
- Event latency quantiles (diff/full/overall) + SSE flush latency + degraded mode & adaptive backlog ratio alerts.
- Lifecycle retention efficiency, p95 scan latency, delete cap utilization + efficiency degradation alerts.
- Column store ingest metrics (rows, bytes, latency p95, failures, retries, backlog, backpressure).

Recommendation: incorporate this inventory into governance docs or auto-generate a rules catalog for drift detection.

## Immediate Action Items (High-Impact)
1. Dashboard Seed Gap – **DONE** (generated dashboards present under `grafana/dashboards/generated/` with `manifest.json`; includes `option_chain.json`, `governance.json`, `bus_stream.json`, etc.).
2. Panel Templates – **DONE (initial)** (`scripts/gen_dashboards.py` emits option chain + governance dashboards; future: richer domain panels & validation).
3. Accessor Audit – **DONE** (`scripts/audit_metrics_accessors.py`; integrate in CI to block regressions).
4. Emission Batcher Enhancements – **DESIGN DOC ADDED** (`EMISSION_BATCHER_ENHANCEMENTS.md`; implementation phases pending).
5. Catalog Wording Cleanup – **DONE** (updated header in `docs/METRICS_CATALOG.md` & generation script to cite YAML spec). Current metric count: 61 (regenerate script to verify).
6. Rules Catalog – **DONE (script + placeholder)** (`scripts/gen_rules_catalog.py`, initial `docs/RULES_CATALOG.md`).
7. Streaming Bus Prototype – **DESIGN OUTLINE ADDED** (`STREAMING_BUS_PROTOTYPE.md`; implementation not started).

## Near-Term (Secondary) Tasks
- Document current emission batcher capabilities vs planned (matrix: counters OK, hist pre-agg NO, adaptive flush NO, async flush NO).
- Clarify expected dashboard provisioning method (Grafana provisioning files vs manual import) in this roadmap.
- Ensure spec-driven panel hints have 1:1 mapping to generated JSON (add validation step).

## Status Drift Risks
- Roadmap previously indicated dashboard seeds present; absence may cause confusion for onboarding—address promptly.
- Mixed wording in catalog generation source may cause stale regeneration instructions.
- Two rule files (`prometheus_rules.yml`, `prometheus_alerts.yml`) without documented separation rationale; consolidate or document split purpose.

---

### Option Chain Aggregation Provider Wiring

`option_chain` aggregated metrics support dynamic provider injection:

Env `G6_OPTION_CHAIN_PROVIDER` formats:
	* `package.module:AttributeOrFactory` – If attribute is callable it is invoked to obtain provider instance, otherwise used directly.
	* `package.module` – Module object used as provider.

Provider contract (any satisfied path):
	1. `get_option_chain_snapshot() -> iterable[dict] | pandas.DataFrame` with columns/keys:
		 `strike, expiry (date/datetime optional), type (CE/PE optional), oi, volume_24h|volume, iv, spread_bps, underlying|spot, mny(optional), dte_days(optional)`.
	2. `fetch_option_chain(index_symbol, expiry_date, strike_range, strike_step=None)` plus optional `get_atm_strike(index_symbol)`; the aggregator derives moneyness & DTE.

Fallback: If provider load fails or returns empty, a synthetic snapshot is generated (logged once) to keep metrics alive for panel continuity.

Disable entirely with `G6_OPTION_CHAIN_AGG_DISABLED=1`.

## Next Focus Candidates (Revalidated)
1. Dashboard & Panel Generation (Action Items 1–2) – unblock visual governance & close roadmap/documentation drift.
2. Emission Batcher Evolution – implement adaptive & histogram strategies (Action Item 4) with performance instrumentation.
3. Streaming Bus Prototype – minimal NATS/Redis/Kafka adapter design to progress Phase 3.
4. Rules & Catalog Automation – script-generated rule inventory + spec/catalog provenance alignment.
5. Accessor Adoption Completion – eliminate any residual direct client usage (Action Item 3) then mark pilot refactor DONE.

(End of strategic note)
\n+### Generator Phase A & D/E/F (Consolidated Enhancements)
Status: COMPLETE (2025-10)

Additions over Phases 6+ (numbering continues logically):

#### Phase A (Foundational Consolidation)
* Added `health_core` dashboard (system + bus + governance high-signal metrics) for rapid triage.
* Manifest enrichment: `panel_count`, `generated_at_unix`, stable spec hash propagation.
* Generator provenance: `g6_meta.generator_version` introduced (initial `phaseA-1`).

#### Phase D (Focused Health Dashboards)
* New plans: `bus_health` (publish latency & throughput focus) and `system_overview_minimal` (2‑panel compact snapshot) appended to default plan set.

#### Phase E (Panel Metadata Enrichment)
* Uniform `g6_meta` augmentation for every panel:
	- `metric`, `family`, `kind`, `source` (one of: spec|auto_rate|auto_hist_quantile|auto_topk|auto_label_split|placeholder|cross_metric|alerts_aggregate|governance_summary)
	- Optional `split_label` for label-split panels
	- `panel_uuid` stable 16-hex identity prefix (already present from Phase 5, reiterated for completeness)
* Cross-metric efficiency panels annotated with `source=cross_metric` improving automated audits.

#### Phase F (Enhanced Drift Diagnostics)
* Verbose drift mode (`G6_DASHBOARD_DIFF_VERBOSE=1`): emits JSON lines with `changed_titles`, `added_titles`, `removed_titles` boundaries (`DRIFT_DETAILS_BEGIN/END`).
* Core drift tokens unchanged (hash, added, removed, changed) preserving CI contract.

#### Efficiency & Latency Extensions
* Multi-window latency ratio panels (5m vs 30m) for column store ingest & bus publish latency added to efficiency dashboards.
* Ratio expression surfaces short-term degradation signals without bespoke alert queries.

#### Governance Enhancements
* Recording Rule Usage Summary table (governance dashboard): counts rule-based vs inline histogram quantile panels with migration percentage.
* Supports deprecation of inline `histogram_quantile` usage as recording rules mature.

#### Current Dashboard Inventory (Post D/E/F)
`provider_ingestion`, `bus_stream`, `emission_pipeline`, `panels_summary`, `column_store`, `governance`, `option_chain`, `system_overview`, `panels_efficiency`, `lifecycle_storage`, `health_core`, `bus_health`, `system_overview_minimal`.

#### Planned Next Steps
1. Partial regeneration flag `--only <slug[,slug2]>` (accelerate local iteration & CI).
2. Panel inventory export (CSV / JSONL) with key metadata (slug,title,metric,source,uuid) for governance audits.
3. CI coverage check: ensure each spec panel hint is represented in at least one generated dashboard (fail on gap).
4. Alert suggestion integration loop: automatically generate heuristics for newly introduced cross-metric ratios.
5. Optional panel stability map to preserve identity through title renames (legacy title aliases).

Generator version advanced to `phaseDEF-1` after Phases D/E/F (bump required on any semantic change affecting panel synthesis to aid forensics during drift events).

\n+### Emission Batcher Adaptive Enhancements (2025-10-05)
Implemented advanced adaptive batching controls:
* Metrics Added:
	- `g6_metrics_batch_adaptive_utilization` (gauge) – last flush distinct entries / adaptive target.
	- `g6_metrics_batch_dropped_ratio` (gauge) – cumulative dropped / merged ratio.
* Adaptive Behavior Improvements:
	- Idle decay path: if instantaneous merged rate < (min_batch / target_interval)/4 uses `G6_EMISSION_BATCH_DECAY_ALPHA_IDLE` (default 0.6) to accelerate target shrink.
	- Under-utilization downshift: if utilization < `G6_EMISSION_BATCH_UNDER_UTIL_THRESHOLD` (default 0.3) for N consecutive flushes (`G6_EMISSION_BATCH_UNDER_UTIL_CONSEC`, default 3) target reduced by 25% (floor at min batch).
	- Max-wait enforcement: forced flush if pending entries exist and time since last activity exceeds `G6_EMISSION_BATCH_MAX_WAIT_MS` (default 750ms).
* Env Tunables Introduced:
	- `G6_EMISSION_BATCH_UNDER_UTIL_THRESHOLD`
	- `G6_EMISSION_BATCH_UNDER_UTIL_CONSEC`
	- `G6_EMISSION_BATCH_DECAY_ALPHA_IDLE`
	- `G6_EMISSION_BATCH_MAX_WAIT_MS`
* Instrumentation: Utilization & dropped ratio gauges empower governance panels to track batching efficiency versus contention savings.
* Stubs: Added `register_histogram` and `batch_observe` no-op stubs for future histogram pre-aggregation phase.
* Tests: Added `test_emission_batcher_utilization.py` verifying target downshift and utilization metric emission; existing adaptive tests still pass.

Next potential batcher steps:
1. Histogram bucket coalescing (latency distribution reduction) using ring buffer.
2. Dynamic alpha selection based on variance of instantaneous rate (volatility-sensitive smoothing).
3. Alerting on low utilization (<10%) sustained while merged rate high (indicative of too-large target).
4. Recording rules for utilization and dropped ratio to enable multi-window governance panels.

### Generator Enrichment Phase 6 (Recording Rules & CI Integration)
Implemented automated recording rule suggestion & governance pipeline integration:
* Script `scripts/gen_recording_rules.py` now derives recommended Prometheus recording rules from spec (counters → 5m rate & total aggregate, histograms → p95/p99 quantiles, labeled gauges → topk(5)).
* Added `--check` mode (exit 8 on drift) enabling CI to fail when the generated `prometheus_recording_rules_generated.yml` is stale.
* Extended CI workflow (`metrics_governance_extended.yml`) executes:
	1. Metrics generation (ensures catalog & accessors up-to-date).
	2. Dashboard semantic verify (`scripts/gen_dashboards_modular.py --verify`) – layout-insensitive drift detection with stable panel IDs.
	3. Recording rules check (`scripts/gen_recording_rules.py --check`).
	4. Git diff gate to ensure regenerated artifacts are committed.
* Governance Principle: heavy / repeated dashboard PromQL is migrated to precomputed recording rules early to reduce per‑query CPU and enforce consistent rate window semantics.
* Exit Codes Summary: generator drift=6 (dashboards), recording rules drift=8. Both fail the workflow distinctly aiding triage.
Future Enhancements (Phase 6+):
	- Ratio / composite rule synthesis using spec panel hints (e.g., efficiency = diff_bytes / full_bytes).
	- Histogram adaptive window (auto choose 1m vs 5m based on volatility flag in spec).
	- Promtool validation step (lint + test expressions) inside CI to catch syntax before deployment.
	- Rules catalog auto-refresh with provenance hash similar to dashboards manifest.
	- Optional slack/PR comment summarizing drift categories (added/removed/changed panels, new rules proposed).

### Generator Enrichment Phase 7 (Efficiency & Lifecycle Coverage)
New focused dashboards & heuristic panels added:
* Dashboards: `panels_efficiency` (diff bytes per write, cumulative avg) and `lifecycle_storage` (column store ingest + emission batching) added to default plan set.
* Efficiency Ratios (auto panels):
	- Diff Bytes per Write (5m rate) = rate(diff_bytes_total) / rate(diff_writes_total)
	- Cumulative Avg Diff Bytes per Write = total diff bytes / total diff writes
	- Column Store Bytes per Row (5m rate) = rate(cs_ingest_bytes_total) / rate(cs_ingest_rows_total)
	- Cumulative Avg CS Bytes per Row = total bytes / total rows
	- CS Backlog Drain ETA (mins) = backlog_rows / rate(rows_total) / 60
	- CS Ingest Success Ratio = 1 - failures_rate / rows_rate (floor clamped)
* Heuristic function `_efficiency_ratio_panels` only activates for slugs: `panels_efficiency`, `column_store`, `lifecycle_storage`.
* Safety: Panels appended after per-metric generation respecting 36 panel safety cap; failures are non-fatal (logged warning).

Rationale: Provide immediate observability into compression/efficiency trends without manually curating panels for each environment.

#### Phase 7 Extension: Suggested Alerts Automation
Script `scripts/gen_alert_suggestions.py` generates a `prometheus_alert_suggestions.yml` file containing heuristic alert rules for newly derived efficiency metrics:
* CS Ingest Success Ratio (warning <99.5% over 10m, critical <99% over 5m)
* CS Backlog Drain ETA (warning >10m over 10m, critical >30m over 5m)

Design Notes:
* Uses direct expressions (no recording rule dependency) to reduce indirection; future enhancement may map to recording rules once stabilized.
* Provides `--check` mode (exit code 9 on drift) mirroring recording rules & dashboards governance pattern.
* Thresholds chosen to surface early degradation while avoiding noise from transient blips (>=5m sustained windows).
* File intentionally separate (`prometheus_alert_suggestions.yml`) so operators can selectively merge into production rule files after review.

Next alert suggestions candidates: diff truncation spike rate, backlog growth acceleration (2nd derivative), bytes-per-row regression vs 7d baseline, provider error ratio volatility.

#### Phase 7 Extension: Multi-Window Latency Panels
Added automatic p95 latency comparison panels (5m vs 30m) with ratio panels (5m / 30m) for:
* Column Store Ingest Latency (`g6_cs_ingest_latency_ms_bucket`)
* Bus Publish Latency (`g6_bus_publish_latency_ms_bucket`)

Purpose: expose short-term latency spikes relative to a longer smoothing window without requiring manual overlay creation.
Ratio Interpretation:
* ~1.0 steady state
* >1 indicates short-term degradation (5m spike)
* <1 sustained may indicate recent improvement or under-utilization

Implementation: heuristics injected via `_efficiency_ratio_panels` for relevant dashboards (column_store, lifecycle_storage, panels_efficiency) respecting existing panel cap. Uses explicit histogram_quantile over both 5m & 30m windows rather than recording rules for immediate feedback; may migrate to recording rules if query cost grows.

#### Phase 7 Extension: Recording Rules Optimization (Multi-Window p95 & Ratio)
Expanded `scripts/gen_recording_rules.py` to synthesize for every histogram:
* `<metric>:p95_30m` – 30m smoothing window p95 (histogram_quantile over 30m rate sum by le)
* `<metric>:p95_ratio_5m_30m` – short-term vs baseline ratio (`p95_5m / clamp_min(p95_30m, 0.001)`)

Motivation: dashboards previously executed duplicate `histogram_quantile` computations for both 5m and 30m windows; precomputing reduces query CPU and standardizes window semantics across panels & alerts.

Implementation Details:
* Generator preserves existing rules (checks `prometheus_rules.yml`) to avoid collisions.
* Automatically back-fills `p95_5m` if not already in existing rules file (ensuring ratio expression validity).
* Applies to all histograms (not only ingest/publish) giving broad future leverage for latency regression detection.
* Denominator guarded with `clamp_min(..., 0.001)` to prevent spikes due to near-zero baseline.

Next Step (optional): Update dashboards to prefer recorded series over inline quantile expressions for further cost savings; keep at least one raw quantile panel in governance dashboard for validation.

Status (uncommitted change applied locally): Dashboard generator updated so auto histogram p95/p99 panels now reference `<metric>:p95_5m` / `<metric>:p99_5m` recording rules, and multi-window ingest latency panels use `<metric>:p95_5m`, `<metric>:p95_30m`, and `<metric>:p95_ratio_5m_30m`. Bus publish panels still inline due to additional `bus` label (pending decision on recording rule dimensionality).
Update (local, uncommitted): Added per-bus recording rules (`g6_bus_publish_latency_ms:p95_5m_by_bus`, `:p95_30m_by_bus`, `:p95_ratio_5m_30m_by_bus`) and refactored dashboard panels to use them (removes last inline multi-window histogram_quantile usage in generator).
Governance Audit (local): Added `scripts/audit_dashboard_quantiles.py` to enforce migration away from inline `histogram_quantile` where recording rules exist (exit 10 on violations). Governance dashboard allowed up to two raw quantiles per histogram (p95 + p99) for validation.
Latency Regression Alert Suggestions (local): Extended `scripts/gen_alert_suggestions.py` to include p95 latency ratio regression alerts:
	* CS ingest p95 ratio >1.25 (10m warn), >1.50 (5m critical)
	* Bus publish p95 ratio >1.30 (10m warn), >1.60 (5m critical) over 5m vs 30m baseline using recording rule series.
Spec Panel Coverage Validation (local): Added `scripts/validate_spec_panel_coverage.py` (exit 11 on uncovered spec panel expressions). Current uncovered panels: system family simple gauges (API success rate %, API avg response time) pending generator inclusion or manual dashboard mapping.
Update: Added `system_overview` dashboard plan (system family) so coverage now 100% (78/78 spec panels represented in generated dashboards).
Governance Dashboard Enhancement (local): Added automatic "Recording Rule Usage Summary" table panel summarizing counts of panels using recording rules vs inline histogram quantiles and overall migration percent.

Next Targets (Phase 7+):
	- Add storage success ratio panels (success vs failures) and backlog burn rate (backlog_rows / rows_rate window).
	- Introduce multi-window (5m/30m) comparative panels for ingestion latency p95.
	- Auto classify efficiency degradation (diff bytes per write 7d p95 vs last hour) for alert candidate generation.
	- Add retention & pruning metrics (once implemented) into lifecycle dashboard automatically.

## Current Dashboard Snapshot (2025-10-09)
Metrics (Prometheus spec-driven): 61 active metrics (see `docs/METRICS_CATALOG.md`). Newly added spec families: `stream`, `panels` (panel diff) migrated from dynamic registration into YAML; future governance uses spec as sole source.
Generated via modular generator (`scripts/gen_dashboards_modular.py`):
* Option Chain Aggregated: `grafana/dashboards/generated/option_chain.json`
* Governance: `grafana/dashboards/generated/governance.json`
* Also present: `provider_ingestion.json`, `bus_stream.json`, `emission_pipeline.json`, `panels_summary.json`, `column_store.json`, `panels_efficiency.json`, `lifecycle_storage.json`, `health_core.json`, `bus_health.json`, `system_overview.json`, `system_overview_minimal.json` (all under `grafana/dashboards/generated/`).
* Manifest: `grafana/dashboards/generated/manifest.json` lists 16 dashboards (with `spec_hash` and `generated_at_unix`).

Curated (manually maintained) dashboards (non-exhaustive categories):
* Core / Health: `g6_core_overview.json`, `g6_health_status.json`, `g6_core_ops.json`, `g6_observability.json`
* Events / Stream / SSE: `g6_events_stream.json`, `g6_events_stream_mega.json`, `g6_events_latency_freshness.json`, `g6_summary_sse_overview.json`
* Lifecycle / Storage: `g6_lifecycle_glance.json`, `g6_lifecycle_hygiene.json`, `g6_storage_pipeline.json`, `g6_storage_minimal.json`
* Panel Integrity & Diff: `g6_panel_diff_efficiency.json`, `g6_panels_integrity.json`, `g6_summary_render_metrics.json`
* Data Quality & Remediation: `g6_data_quality.json`, `g6_data_quality_unified.json`, `g6_csv_quality.json`, `g6_expiry_remediation.json`
* Option Chain Aggregation: `g6_option_chain_agg.json`
* Performance & Memory: `g6_perf_latency.json`, `g6_memory_adaptation.json`
* Provider & Index: `g6_provider_system_health.json`, `g6_index_health.json`, `g6_master_index.json`
* Overlays & Specialized: `overlay_critical_panels.json`, `weekday_overlay_panel_snippet.json`

Gap Analysis:
* Generator does not yet cover: lifecycle/storage, panel diff efficiency, data quality, SSE latency.
* Some governance dashboards overlap; evaluate consolidation of spec & generated dashboards into a single curated governance view.
* Newly spec'd families (`stream`, `panels`) not yet auto-rendered; pending generator refactor.

## Drift Watch & Governance
Triggers for doc update:
* Metrics count change > +5 without dashboard additions → add panels or annotate deferred.
* New spec family introduced without generator extension within 1 sprint.
* Duplicate governance/spec dashboards proliferate (>2 overlapping) → consolidate.
* Generator output filename mismatch (add governance JSON name normalization).

Proposed Backlog:
1. Extend generator to lifecycle/storage & diff efficiency panels.
2. Add validation script comparing spec panel hints to actual dashboards (exit non-zero on drift).
3. Normalize governance dashboard naming (use `grafana/dashboards/generated/governance.json`).
4. Introduce a provisioning manifest snippet under `grafana/provisioning/` enumerating required dashboards.
5. Optional: add panel test harness verifying PromQL expressions compile (dry-run via promtool if available).

## Spec-First Consolidation (2025-10-05)
Implemented changes:
* Added `stream` family (indices stream gating metrics with panel hints).
* Added `panels` family (panel diff metrics) – removed legacy dynamic-only ownership.
* Introduced linter `scripts/validate_metrics_spec.py` (CI candidate) enforcing required fields and basic hygiene (names, buckets, budgets, panel hints).
* Regenerated metrics catalog (61 metrics) post-migration.

Pending cleanup:
* Remove or guard dynamic `panel_diff` MetricDef registrations in `src/metrics/spec.py` (pruned now in code; kept under legacy comment until full removal window passes).
* Confirm no runtime path depends on old predicate gating before deleting legacy block.

## Generator Refactor (Planned Design Stub)
Goals:
* One generator pass builds a set of dashboards from YAML spec families + grouping config.
* Use panel hints when present; synthesize defaults when absent.

Design Elements:
* Config mapping (inline Python or YAML):
	- provider_ingestion: [provider, provider_mode]
	- bus_stream: [bus, stream]
	- emission_pipeline: [emission]
	- panels_summary: [panels, stream]
	- column_store: [column_store]
	- governance: [governance]
	- option_chain: [option_chain]
* Default synthesis:
	- counter → rate(...[5m]) + (optional by-label split if <=5 labels & label list non-empty)
	- histogram → p95/p99 (if bucketed) + bucket rate table panel
	- gauge (labeled) → topk or sum by label (depending on semantics)
* Panel naming normalization rules (Title Case, units appended if provided, window tokens unified: 5m/10m/30m).
* Alert embedding (phase 2): optionally append alert annotation panel referencing each active rule.
* Output location: `grafana/dashboards/generated/` (distinct from curated) with a manifest JSON listing dashboards + spec hash.

Validation Hook:
* New script `scripts/gen_dashboards_modular.py` returns non-zero if any referenced family missing or if diff between synthesized and repo dashboards (enforces regen discipline).

Migration Plan:
1. Implement modular generator alongside existing script (keep old until parity confirmed for option_chain & governance).
2. Compare generated JSON (semantic hash excluding layout coordinates) to curated dashboards; iterate until acceptable.
3. Mark legacy curated dashboards with `legacy_` prefix or move to `dashboards/legacy/`.
4. Add CI step: run linter + modular generator + fail on diff.

### Generator Enrichment Phase 1 (2025-10-05)
Implemented in `scripts/gen_dashboards_modular.py`:
* Parses spec `panels:` definitions per metric; converts each to a concrete Grafana panel (title/promql/unit/panel_type).
* Auto-synth rules when spec lacks coverage:
	- counter: add 5m sum(rate()) panel if no rate panel present.
	- histogram: add p95 / p99 quantile panels if absent (expects *_bucket metric).
	- labeled gauge: add Top 5 panel (topk) if no panel referencing metric.
* Safety cap: 36 panels per dashboard (prevent runaway during early phases).
* Annotates dashboards with `g6_meta.enriched=true` and `placeholder_panels=false` when at least one spec-derived panel exists.
Next steps (Phase 2+) will handle label splitting heuristics (multi-column grouping), alert rule surfacing, and layout density optimization.

### Generator Enrichment Phase 2 (Label Splitting Heuristics)
Added automatic label split panels in `scripts/gen_dashboards_modular.py`:
* Applies to counters & gauges with labels.
* Heuristic rules:
	- Limit to first 2 labels to cap explosion (`label_split_cap=2`).
	- For counters: generate `sum by (label) (rate(metric[5m]))` if no existing panel expression already aggregates by that label.
	- For gauges: generate `sum by (label) (metric)` similarly.
	- Skips if a spec-defined panel already contains `by (label)` or a custom expression referencing that label grouping.
* Continues to add Top 5 time series panel for labeled gauges when no explicit panel references the metric name.
* All auto-generated titles suffixed `(auto)` and may be refined later for UX consistency.
Future improvements: compute distinct series counts (cardinality guard integration) to dynamically decide which labels to split; implement layout grouping by label dimension.

### Generator Enrichment Phase 3 (Alert Surfacing)
Implemented aggregated alert surfacing:
* For each dashboard, parses alerts from metrics in included families and prepends a "Spec Alerts Overview" table panel.
* Panel encodes alert rows (alert|metric|severity|summary|expr prefix) inside a placeholder PromQL comment expression; future enhancement may pivot to a JSON backend or annotation queries.
* Dashboard metadata now includes `alerts_panel` and `alerts_count` fields for drift/CI checks.
* Rationale: ensures on-call immediately sees governed alert inventory aligned with spec hash shown in governance dashboards.
Next steps: generate synthetic recording rules doc panel, surface last evaluation timestamps, and optionally cross-link to firing alert status via Prometheus Alertmanager API (out-of-scope for static generation; requires runtime datasource).

### Generator Enrichment Phase 4 (Semantic Diff & Verify)
Semantic drift detection integrated into `--verify` mode:
* Panel semantic signature: JSON of {type,title,exprs(sorted),datasource_type,unit} ignoring layout (gridPos) and ordering.
* Drift categories reported: `missing:<slug>`, `unreadable:<slug>`, `hash:<slug>`, `added:<slug>:<n>`, `removed:<slug>:<n>`.
* Exit code `6` reserved for semantic drift (distinct from earlier placeholder exit code `5`).
* Use-case: CI enforces regeneration when spec changes or synthesis rules evolve; layout-only edits do not trigger failure.
Refinement: Added `changed:<slug>:<n>` detection (title-stable signature replacement). Title matching pairs removed+added panels sharing identical titles; counted as changes and excluded from added/removed tallies.
Limitations: Multiple panels with identical titles may over-count or under-pair; heuristic picks min(old,new) pairings. Future improvement could use fuzzy expr similarity or a UUID persisted in panel metadata.

### Generator Enrichment Phase 5 (Stable Panel IDs / UUIDs)
Implemented stable per-panel identifiers:
* Deterministic ID = first 8 hex of sha256(slug + semantic_signature) stored as numeric `id` (Grafana-compatible) and `panel_uuid` (first 16 hex) under each panel's `g6_meta`.
* Semantic signature fields: type, title, sorted target expr list, datasource type, unit.
* Purpose: Preserve panel identity across layout moves or grid size tweaks; allow future diff tooling to track modifications vs replacements.
* Drift logic ignores ids (still signature-based) to avoid false positives if hashing algorithm remains stable.
Future: Persist previous signature->uuid mapping for renamed panels (title changes) by embedding an optional `legacy_titles` array.
(End of strategic note)

---

## Repo reality check (2025-10-09)

- Generator: `scripts/gen_dashboards_modular.py` is present and primary; supports `--verify` and `--only <slug[,slug2]>` for partial regeneration.
- Generated dashboards are under `grafana/dashboards/generated/`; `manifest.json` currently lists 16 dashboards including `option_chain.json`, `governance.json`, `bus_stream.json`, `lifecycle_storage.json`, `health_core.json`, and `system_overview_minimal.json`.
- Prometheus artifacts: `prometheus_rules.yml`, `prometheus_alerts.yml`, and the generated `prometheus_recording_rules_generated.yml` exist and align with governance goals.
- The in‑process EventBus and SSE endpoints are live; external streaming bus remains a future phase.

## Immediate next steps

1) Provisioning: add Grafana provisioning files under `grafana/provisioning/dashboards/` to auto-import dashboards from `grafana/dashboards/generated/`.
2) CI: run `python scripts/gen_dashboards_modular.py --verify` and fail on drift (exit 6); add `scripts/gen_recording_rules.py --check` (exit 8). Commit regenerated artifacts when these fail.
3) Dashboard naming: consistently reference `grafana/dashboards/generated/<slug>.json` (avoid legacy `g6_*.json` names in docs).
4) Coverage: extend generator coverage for lifecycle/storage and panels efficiency where still partial, and validate spec panel hints map 1:1 to panels.
