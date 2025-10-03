# Data Retention Policy

_Last updated: 2025-09-26_

## Summary
All persisted option data (per-option CSV rows, overview snapshots) and time-series points (InfluxDB) currently follow an **infinite retention policy**. No automatic deletion, truncation, or compaction job is shipped with the platform at this time.

## Rationale
- Historical depth is valuable for backtesting, anomaly analysis, and longitudinal volatility / OI studies.
- Storage footprint remains manageable relative to commodity disk costs for the expected scale.<sup>1</sup>
- Premature retention logic introduces operational complexity (partial data windows, integrity concerns) before a demonstrated storage pressure.

<sup>1</sup> If scale or cost projections change (e.g., multi-year continuous capture across expanded index universe), a staged retention or archival strategy will be revisited.

## Scope
| Data Class | Location | Mechanism | Current Retention |
|-----------|----------|-----------|-------------------|
| Per-option snapshots | `data/g6_data/` (CSV) | File append per cycle | Infinite |
| Overview snapshots | `data/g6_data/` (CSV) | One row per index/cycle | Infinite |
| Panels / derived JSON | `data/panels/` | Periodic overwrite | Latest only (implicit) |
| Catalog / status JSON | `data/catalog.json`, `data/runtime_status.json` | Overwrite each cycle | Latest only (implicit) |
| Influx measurements | `options_overview`, `option_data` | Influx line protocol writes | Infinite (no retention policy set) |
| Events log | `logs/events.log` | Append NDJSON | Infinite (bounded by manual log rotation policy if externally configured) |

## Explicit Non-Features
- No `retention.*` config keys (schema intentionally omits).
- No background pruning job / TTL worker.
- No built-in compression rotation (gzip) of prior day CSVs.

## Future Optional Enhancements (Not Scheduled)
| Enhancement | Trigger Criteria | Concept |
|-------------|------------------|---------|
| Gzip day rollover | Directory size threshold OR daily cron | Compress previous day CSVs to `*.csv.gz` and adjust readers. |
| Cold archive move | Age > N days | Move old CSV/Parquet files to archive path or object store. |
| Parquet columnar sink | High read amplification | Write columnar snapshots for faster analytical scans. |
| Influx retention policy config | Cluster size pressure | Create RP and continuous queries for downsampling high-frequency fields. |

## Operational Guidance
- External operators may implement OS-level logrotate or filesystem quotas; platform will not resist external pruning but integrity of derived analytics may degrade if partial windows introduced.
- When enabling manual compression or archival, ensure downstream tooling (parsers, dashboards) is updated to read both plain and compressed formats.
- For Influx, administrators can manually create retention policies / downsampling continuous queries outside the application scope without code changes.

## Integrity Considerations
The integrity checker (`scripts/check_integrity.py`) focuses on cycle gaps, not retention spans. If retention/archival is introduced later, an additional integrity dimension (age horizon completeness) may be required.

## Decision Log
- 2025-09-26: Confirmed infinite retention baseline; removed prior roadmap reference to retention worker. This doc added to make policy explicit and testable.

## Test Enforcement
A governance test (`tests/test_retention_policy.py`) asserts that no config keys containing `retention` exist and the schema has not reintroduced a retention subtree. Any future retention feature must be accompanied by an updated policy section & explicit deprecation window announcement.

---
_Keep this file synchronized with any schema or roadmap changes related to retention or archival._
