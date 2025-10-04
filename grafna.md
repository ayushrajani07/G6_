# Grafana / Metrics Strategy Roadmap

(Refreshed after repository scan on 2025-10-04)

## Core Principle
Separate operational Prometheus metrics (low/medium cardinality) from high-cardinality option chain data (delivered via streaming / query layer). Prometheus for health, aggregates, distributions—not every option contract.

## Immediate Improvements (Status After Scan)
1. Metric specification layer (YAML) -> generate code + docs. **DONE** (base spec `metrics/spec/base.yml`, generated accessors, provenance hash gauges). Dashboard seed generation is NOT yet committed.
2. Unified metric factory & cardinality guard; emit self-metrics for series counts. **DONE** (registry + guard metrics + growth diagnostics & alert rules present).
3. Structured emission scheduling (batch/handoff). **PARTIAL** (counter batching via `emission_batcher`; pending: histogram pre-aggregation, adaptive flush sizing, async producer/flush separation).
4. Auto-doc generation & drift check in CI. **DONE** (generation scripts + duplicate/fail-fast + spec/build hash governance). Catalog wording still references `spec.py` instead of YAML (docs cleanup pending).
5. Panel template generation from spec. **PARTIAL** (spec embeds panel hints; no committed Grafana dashboard JSON outputs yet).
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
2. Aggregated chain metrics. **METRICS DONE / DASHBOARD SEED PENDING** (buckets implemented: contracts, OI, volume, IV mean, spread bps, new listings; heatmap/table queries defined in spec; referenced dashboard `g6_option_chain_agg.json` not found in repo — needs generation or roadmap wording adjustment).
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
1. Dashboard Seed Gap – **DONE** (`grafana/dashboards/g6_option_chain_agg.json` committed).
2. Panel Templates – **DONE (initial)** (`scripts/gen_dashboards.py` emits option chain + governance dashboards; future: richer domain panels & validation).
3. Accessor Audit – **DONE** (`scripts/audit_metrics_accessors.py`; integrate in CI to block regressions).
4. Emission Batcher Enhancements – **DESIGN DOC ADDED** (`EMISSION_BATCHER_ENHANCEMENTS.md`; implementation phases pending).
5. Catalog Wording Cleanup – **DONE** (updated header in `docs/METRICS_CATALOG.md` & generation script to cite YAML spec).
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
