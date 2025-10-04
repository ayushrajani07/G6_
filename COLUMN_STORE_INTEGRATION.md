# Column Store Integration (Phase 4)

Status: PLANNING  
Owner: Platform Observability / Data Infra  
Last Updated: 2025-10-04

## 1. Goals
Provide durable, query-efficient historical storage for higher-cardinality metrics & option chain aggregates beyond Prometheus retention limits.

Key capabilities:
- Near-real-time ingestion (< 5s p95 batch commit) of aggregated option chain snapshots & derived analytics.
- Backfill / replay from existing runtime status or snapshot files.
- Query surfaces for dashboards (historical heatmaps, trend overlays) and downstream research tooling.
- Operational transparency: backlog, latency, failure, retry, backpressure metrics (already spec'd under `column_store`).

Non-goals (Phase 4):
- Full ad‑hoc arbitrary SQL API exposure to end-users.
- Per-trade tick ingestion (will consider in later phase after validating cost & data volume).

## 2. Candidate Technologies
| Candidate | Pros | Cons |
| --------- | ---- | ---- |
| ClickHouse | Columnar, great compression, materialized views, low-latency inserts via batches | Operational overhead (cluster mgmt), requires merge tree tuning |
| TimescaleDB | Postgres compatible, simpler ops for existing PG shops | Insert performance lower for very wide column sets, compression window mgmt |
| DuckDB (embedded) | Zero external service, easy prototyping | Concurrency limits, durability patterns, not ideal for multi-process writer |

Initial selection bias: ClickHouse (native batching + TTL + PARTITION BY + ubiquitous tooling). Abstract interfaces to allow swap if early complexity too high.

## 3. Data Model (Initial)
Logical Table: `option_chain_agg`
- ts (DateTime/DateTime64) partitioned hourly or daily
- underlying (String)
- dte_bucket (UInt16)
- moneyness_bucket (Int16)  # symmetrical bucket index
- contracts_active (UInt32)
- volume_24h (UInt64)
- open_interest (UInt64)
- iv_mean (Float32)
- spread_bps_mean (Float32)
- listings_new (UInt32)
- build_latency_ms (UInt32) optional (diagnostic)

Secondary Table (future): `ingest_audit`
- ts
- table
- batch_id
- rows
- bytes
- latency_ms
- status (enum: success|fail|retry)
- reason (nullable)

## 4. Ingestion Pipeline
Stages:
1. Collector Buffer (in-process ring or queue) accumulates row objects.
2. Batch Builder aggregates until (row_count >= N) OR (age >= target_latency_ms).
3. Serializer converts to columnar-friendly format (JSONEachRow or Parquet depending on client library chosen).
4. Transport executes HTTP/native insert to ClickHouse.
5. Commit & Metrics emission (success/failure, rows, bytes, latency, backlog update, backpressure flag).

Backpressure Strategy:
- If backlog rows > HIGH_WATERMARK -> set `g6_cs_ingest_backpressure_flag{table}`=1 and slow producers (sleep or drop low-priority rows).
- CLEAR when backlog < LOW_WATERMARK.

Batch Sizing Heuristics:
- Target rows per batch: 2k–10k (tune by measuring latency & server merge load).
- Max latency: 5s p95 (enforced by flush timer even if row target not met).

## 5. Metrics Mapping (Spec Family `column_store`)
| Operational Question | Metric | Query Pattern |
| -------------------- | ------ | ------------- |
| Are we ingesting rows? | g6_cs_ingest_rows_total | rate()/table |
| Data volume trend? | g6_cs_ingest_bytes_total | rate()/table |
| Ingest latency SLO? | g6_cs_ingest_latency_ms | histogram_quantile p95 |
| Failure causes? | g6_cs_ingest_failures_total{reason} | rate() grouped by reason |
| Backlog size & pressure? | g6_cs_ingest_backlog_rows / g6_cs_ingest_backpressure_flag | raw gauge / alert on sustained > threshold |
| Retry churn? | g6_cs_ingest_retries_total | rate() |

## 6. Proposed Alert Rules (Draft)
(Not yet added to `prometheus_rules.yml` – implement after ingestion code exists.)

1. CSIngestLatencyP95High
```
expr: histogram_quantile(0.95, sum by (le,table) (rate(g6_cs_ingest_latency_ms_bucket[5m]))) > 5000
for: 10m
labels: { severity="warning" }
annotations:
  summary: "Column store ingest latency p95 high"
  description: "p95 ingest latency >5s for 10m (table={{ $labels.table }})"
```
2. CSIngestFailureRateElevated
```
expr: sum by (table) (rate(g6_cs_ingest_failures_total[10m])) > 0.05 * sum by (table) (rate(g6_cs_ingest_rows_total[10m]))
for: 15m
```
3. CSBacklogGrowing
```
expr: g6_cs_ingest_backlog_rows > 50000
for: 15m
```
4. CSBackpressureActive
```
expr: sum by (table) (g6_cs_ingest_backpressure_flag == 1) > 0
for: 5m
```

## 7. Configuration (Planned Keys)
Environment / config JSON keys (no code yet):
- STORAGE_COLUMN_STORE_ENABLED (bool, default 0)
- STORAGE_COLUMN_STORE_DRIVER (clickhouse|timescale|duckdb)
- STORAGE_COLUMN_STORE_BATCH_ROWS (int, default 4000)
- STORAGE_COLUMN_STORE_MAX_LATENCY_MS (int, default 5000)
- STORAGE_COLUMN_STORE_HIGH_WATERMARK_ROWS (int, default 80000)
- STORAGE_COLUMN_STORE_LOW_WATERMARK_ROWS (int, default 40000)
- STORAGE_COLUMN_STORE_COMPRESSION_CODEC (lz4|zstd) (if driver supports)
- CLICKHOUSE_URL / CLICKHOUSE_USER / CLICKHOUSE_PASSWORD (driver-specific)

## 8. Phased Implementation Plan
Phase 4A (Instrumentation & Stubs)
- Implement ingestion buffer + metrics emission only (no external writes; simulate commit step).
- Add alert rules commented out until real writes enabled.

Phase 4B (ClickHouse MVP)
- Real writer with HTTP interface (insert JSONEachRow batches).
- Basic retry with exponential backoff (increment retries & failures metrics).
- Backpressure logic enabling slowdown.

Phase 4C (Query + Dashboard)
- Add Grafana dashboard panels (row rate, bytes rate, p95 latency, failures by reason, backlog, backpressure timeline).
- Add option chain historical heatmap using column store (if time).

Phase 4D (Backfill & Compaction Enhancements)
- Backfill script converting existing parity snapshots to batches.
- Optional materialized view for recent hour segmentation.
- Add compaction / TTL metrics (future metric family extension: compaction_seconds, parts_merged_total).

## 9. Risks & Mitigations
| Risk | Impact | Mitigation |
| ---- | ------ | ---------- |
| Batch flush contention | Increased latency | Single worker thread + queue depth guard |
| ClickHouse insert spikes | Merge pressure | Tune batch rows & use partitions/day |
| Backlog runaway | Memory pressure | High/low watermark backpressure + optional dropping low-priority rows |
| Query cardinality explosion | Grafana instability | Limit dimension set (table, minimal buckets) for CS metrics |
| Credential leakage in logs | Security | Never log full URL with credentials; redact password env vars |

## 10. Acceptance Criteria
- Metrics family `column_store` present with live increments under simulation.
- p95 ingest latency < 5s during sustained load test (10k rows/min per table).
- Backpressure flag toggles when synthetic backlog thresholds crossed.
- All new tests green (will add targeted ingestion simulation tests).
- Design doc linked from roadmap (`grafna.md`).

---
Follow-ups after MVP:
- Evaluate Parquet ingestion vs JSONEachRow once stability confirmed.
- Add compaction / part size monitoring.
- Integrate with retention policy for cold storage export.
