# Column Store Config Stub

Phase: PLANNING (See `COLUMN_STORE_INTEGRATION.md`)

| Key | Default | Description |
| --- | ------- | ----------- |
| STORAGE_COLUMN_STORE_ENABLED | 0 | Master enable switch for column store ingestion pipeline |
| STORAGE_COLUMN_STORE_DRIVER | clickhouse | Backend driver: clickhouse|timescale|duckdb |
| STORAGE_COLUMN_STORE_BATCH_ROWS | 4000 | Target rows per batch before flush |
| STORAGE_COLUMN_STORE_MAX_LATENCY_MS | 5000 | Max ms before force flush even if batch not full |
| STORAGE_COLUMN_STORE_HIGH_WATERMARK_ROWS | 80000 | Backpressure engage backlog threshold |
| STORAGE_COLUMN_STORE_LOW_WATERMARK_ROWS | 40000 | Backpressure clear threshold |
| STORAGE_COLUMN_STORE_COMPRESSION_CODEC | lz4 | Insert compression codec (driver-dependent) |
| CLICKHOUSE_URL | (unset) | Base HTTP(s) URL for ClickHouse server |
| CLICKHOUSE_USER | (unset) | Username for ClickHouse auth |
| CLICKHOUSE_PASSWORD | (unset) | Password (never log this) |

Notes:
- Implementation code will read these later; no runtime hooks added yet.
- Backpressure logic will gate producers by sleeping or dropping low-priority rows when active.
- Additional future keys: STORAGE_COLUMN_STORE_PARTITION_DAYS, STORAGE_COLUMN_STORE_TLS_VERIFY.
