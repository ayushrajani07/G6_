"""Storage & persistence related metric registrations (extracted).

Lifecycle hygiene metrics have been extracted to `lifecycle_category` (lifecycle group)
to keep taxonomy clean.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge

if TYPE_CHECKING:  # only for type checkers; avoids runtime import cycles
    from .metrics import MetricsRegistry  # noqa: F401

def init_storage_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('csv_files_created', Counter, 'g6_csv_files_created_total', 'CSV files created')
    core('csv_records_written', Counter, 'g6_csv_records_written_total', 'CSV records written')
    core('csv_write_errors', Counter, 'g6_csv_write_errors_total', 'CSV write errors')
    core('csv_disk_usage_mb', Gauge, 'g6_csv_disk_usage_mb', 'Disk usage attributed to CSV outputs (MB)')
    core('csv_cardinality_unique_strikes', Gauge, 'g6_csv_cardinality_unique_strikes', 'Unique strikes encountered in last write cycle', ['index','expiry'])
    core('csv_cardinality_suppressed', Gauge, 'g6_csv_cardinality_suppressed', 'Flag: 1 if cardinality suppression active for index/expiry, else 0', ['index','expiry'])
    core('csv_cardinality_events', Counter, 'g6_csv_cardinality_events_total', 'Cardinality suppression events', ['index','expiry','event'])
    core('csv_overview_writes', Counter, 'g6_csv_overview_writes_total', 'Overview snapshot rows written', ['index'])
    core('csv_overview_aggregate_writes', Counter, 'g6_csv_overview_aggregate_writes_total', 'Aggregated overview snapshot writes', ['index'])
    core('influxdb_points_written', Counter, 'g6_influxdb_points_written_total', 'InfluxDB points written')
    core('influxdb_write_success_rate', Gauge, 'g6_influxdb_write_success_rate_percent', 'InfluxDB write success rate percent')
    core('influxdb_connection_status', Gauge, 'g6_influxdb_connection_status', 'InfluxDB connection status (1=healthy,0=down)')
    core('influxdb_query_performance', Gauge, 'g6_influxdb_query_time_ms', 'InfluxDB representative query latency (ms)')
    core('backup_files_created', Counter, 'g6_backup_files_created_total', 'Backup files created')
    core('last_backup_unixtime', Gauge, 'g6_last_backup_unixtime', 'Timestamp of last backup (unix seconds)')
    core('backup_size_mb', Gauge, 'g6_backup_size_mb', 'Total size of last backup (MB)')

    # Data quality and CSV-pipeline counters used by CsvSink and error routing
    core('data_errors_labeled', Counter, 'g6_data_errors_labeled_total', 'Classifier-labeled data errors', ['index','component','error_type'])
    core('zero_option_rows_total', Counter, 'g6_zero_option_rows_total', 'Zero option rows detected', ['index','expiry'])
    core('csv_junk_rows_skipped', Counter, 'g6_csv_junk_rows_skipped_total', 'CSV junk rows skipped', ['index','expiry'])
    core('csv_junk_rows_threshold', Counter, 'g6_csv_junk_rows_threshold_skipped_total', 'CSV junk rows skipped due to threshold', ['index','expiry'])
    core('csv_junk_rows_stale', Counter, 'g6_csv_junk_rows_stale_skipped_total', 'CSV junk rows skipped due to staleness', ['index','expiry'])
    core('csv_mixed_expiry_dropped', Counter, 'g6_csv_mixed_expiry_dropped_total', 'Rows dropped due to mixed expiry in batch', ['index','expiry'])

    # CSV sink health & diagnostics gauges (populated by CsvSink.health_check)
    core('csv_sink_health_status', Gauge, 'g6_csv_sink_health_status', 'CSV sink health status (1=healthy,0=unhealthy)')
    core('csv_sink_write_latency_ms', Gauge, 'g6_csv_sink_write_latency_ms', 'CSV sink write latency (ms)')
    core('csv_sink_disk_free_mb', Gauge, 'g6_csv_sink_disk_free_mb', 'CSV sink disk free space (MB)')
    core('csv_sink_backlog_rows', Gauge, 'g6_csv_sink_backlog_rows', 'Queued rows in CSV batch backlog')
    core('csv_sink_backlog_files', Gauge, 'g6_csv_sink_backlog_files', 'Buffered files in CSV batch backlog')
    core('csv_sink_health_score', Gauge, 'g6_csv_sink_health_score', 'Composite CSV sink health score (0-100)')
