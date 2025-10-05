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
2. Aggregated chain metrics. **DONE (metrics + seed)** (`g6_option_chain_agg.json` present; panels cover OI, volume, IV, spread, listings; future enhancement: latency & provider health overlays).
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
1. Dashboard Seed Gap – **DONE** (`grafana/dashboards/g6_option_chain_agg.json` present; governance & multiple ancillary dashboards curated).
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

Next Targets (Phase 7+):
	- Add storage success ratio panels (success vs failures) and backlog burn rate (backlog_rows / rows_rate window).
	- Introduce multi-window (5m/30m) comparative panels for ingestion latency p95.
	- Auto classify efficiency degradation (diff bytes per write 7d p95 vs last hour) for alert candidate generation.
	- Add retention & pruning metrics (once implemented) into lifecycle dashboard automatically.

## Current Dashboard Snapshot (2025-10-05)
Metrics (Prometheus spec-driven): 61 active metrics (see `docs/METRICS_CATALOG.md`). Newly added spec families: `stream`, `panels` (panel diff) migrated from dynamic registration into YAML; future governance uses spec as sole source.
Generated via script (`scripts/gen_dashboards.py`):
* Option Chain Aggregated: `g6_option_chain_agg.json`
* Governance (planned output name `g6_metrics_governance.json`) – generator present; additional governance/spec dashboards exist (`g6_generated_spec_dashboard.json`, `g6_spec_panels_dashboard.json`). Consider harmonizing naming.

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
3. Normalize governance dashboard naming (`g6_metrics_governance.json`).
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
