# Long Term TODO (G6 Platform)

## Observability / Alerts
- Burn rate SLO alerts for memory_pressure_level >=2 (multi-window, multi-burn)
- Alert inhibition rules (suppress critical if already paging high sustained)
- Metadata labelling for deployment (instance, env) via static labels
- Advanced anomaly detection: sudden drop in options_collected, spikes in api_response_latency_ms

## Metrics Hygiene
- Evaluate high-cardinality option metrics -> consider sampling or ATM+near wings only
- Histogram for option price distributions per index (low cardinality bucketed)
- Rolling quantiles for PCR (Prometheus recording: p50/p90/p99)

## Storage Layer Redesign
- Collapse per-offset directory layout into partitioned single daily file (parquet or feather) to reduce inode count
- Add compression (gzip / zstd) for historical CSV > N days old
- Introduce retention sweeper (delete raw per-strike beyond 30 days; keep overview) with metrics
- Potential migration path to columnar store (DuckDB or Parquet) with query helper

## InfluxDB Enhancements
- Switch to async write API with queue + backpressure
- Periodic health probe query measuring median latency, adjusting connection_status
- Shard retention policies and CQ for downsampling (5m/30m/hour windows)

## Adaptive System
- Extend memory pressure manager to consider CPU saturation for dual-threshold gating
- Add predictive model (simple linear forecast) for memory usage trajectory to pre-empt tier escalation

## Data Quality
- Option greeks validation thresholds (flag unrealistic values, e.g., |delta|>1.05)
- Add checksum or hash for per-cycle payload to detect duplicate ingest cycles

## Operational Tooling
- CLI to backfill aggregated overview from raw per-strike data
- Script to compact historical CSV structure into archival format

## Testing
- Property-based tests for timestamp rounding edge cases (DST boundaries if relevant)
- Integration test harness for CsvSink + InfluxSink dual write path with mocks

## Security / Hardening
- Add basic integrity checks before writing (validate index symbol against allowlist)
- Consider signing daily overview files (HMAC) if tamper detection required

