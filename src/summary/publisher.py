from __future__ import annotations

"""
G6 Platform Panel Publisher - Enhanced with High-Level Metrics Processing

This module publishes panel data using the new centralized metrics processor.
It now serves as a bridge between the high-level metrics processor and the
panel JSON files, providing clean, organized metrics with intuitive naming.

Architecture:
- Uses MetricsProcessor as the single source of truth
- Publishes structured metrics with intuitive names
- Eliminates metric duplication and inconsistencies
- Provides backward compatibility with existing panel consumers

Enable with environment:
  - G6_ENABLE_PANEL_PUBLISH=true     # turn on publishing
  - G6_PANELS_DIR=data/panels        # optional, where JSON files are written
  - G6_OUTPUT_SINKS includes 'panels' (auto-added if not present when enabled)

Consumers: scripts/summary/* panels read these JSONs when enabled (mode 'on' or 'auto').
"""
import os
from collections.abc import Iterable, Mapping
from typing import Any

from src.utils.metrics_adapter import get_metrics_adapter

from .resilience import safe_append, safe_update


def _truthy(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _ensure_panels_sink_active() -> Any | None:
    """Ensure the OutputRouter is configured with a panels sink.

    Returns the router instance, or None if OutputRouter unavailable.
    """
    try:
        from src.utils.output import get_output  # type: ignore
    except Exception:
        return None
    sinks_env = os.getenv("G6_OUTPUT_SINKS", "stdout,logging")
    tokens = [t.strip().lower() for t in sinks_env.split(",") if t.strip()]
    if "panels" not in tokens:
        tokens.append("panels")
        os.environ["G6_OUTPUT_SINKS"] = ",".join(tokens)
        # Set default panels dir if missing
        os.environ.setdefault("G6_PANELS_DIR", os.path.join("data", "panels"))
    # Always rebuild router to reflect current environment (ensures tests and
    # runtime pick up G6_OUTPUT_SINKS/G6_PANELS_DIR updates)
    return get_output(reset=True)


def publish_cycle_panels(
    *,
    indices: Iterable[str],
    cycle: int,
    elapsed_sec: float,
    interval_sec: float | None,
    success_rate_pct: float | None,
    metrics: Any | None = None,
    csv_sink: Any | None = None,
    influx_sink: Any | None = None,
    providers: Any | None = None,
) -> None:
    """Publish panel data using the high-level metrics processor.

    Enhanced to use the centralized MetricsProcessor for clean, organized metrics
    with intuitive naming. Maintains backward compatibility while eliminating
    metric duplication and inconsistencies.
    """
    if not _truthy("G6_ENABLE_PANEL_PUBLISH", default=False):
        return
    router = _ensure_panels_sink_active()
    if router is None:
        return

    # Get processed metrics from the centralized adapter/processor
    try:
        adapter = get_metrics_adapter()
        platform_metrics = adapter.get_platform_metrics()
    except Exception:
        # Fallback to legacy behavior if processor/adapter fails
        platform_metrics = None

    # Panels update block as a single transaction for atomicity
    with router.begin_panels_txn():
        # Loop panel with enhanced metrics
        if platform_metrics:
            loop_payload: dict[str, Any] = {
                "cycle": platform_metrics.collection_cycle,
                "last_start": None,  # Not available at this level
                "last_duration": platform_metrics.performance.collection_cycle_time,
                "success_rate": platform_metrics.performance.collection_success_rate,
                "avg": platform_metrics.performance.collection_cycle_time,
                "p95": None,  # Would need histogram metrics
                "uptime_hours": round(platform_metrics.performance.uptime_seconds / 3600, 1),
                "options_per_minute": platform_metrics.performance.options_per_minute,
            }
        else:
            # Fallback loop payload
            loop_payload = {
                "cycle": cycle,
                "last_start": None,
                "last_duration": round(float(elapsed_sec), 3),
            }
            if success_rate_pct is not None:
                loop_payload["success_rate"] = success_rate_pct
            if interval_sec is not None:
                loop_payload["avg"] = float(elapsed_sec)
                loop_payload["p95"] = None

        safe_update(router, "loop", loop_payload)

        # Provider panel using processed metrics
        if platform_metrics:
            provider_payload = {
                "name": "G6Provider",  # Can be enhanced with actual provider info
                "latency_ms": platform_metrics.performance.api_response_time,
                "success_rate": platform_metrics.performance.api_success_rate,
                "options_per_min": platform_metrics.performance.options_per_minute,
            }
            safe_update(router, "provider", provider_payload)
        else:
            # Fallback provider logic
            prov_name = None
            latency = None
            try:
                if providers and getattr(providers, "primary_provider", None) is not None:
                    prov_name = type(providers.primary_provider).__name__
            except Exception:
                pass
            try:
                if metrics and hasattr(metrics, "_api_latency_ema"):
                    latency = metrics._api_latency_ema
            except Exception:
                pass
            payload = {k: v for k, v in {"name": prov_name, "latency_ms": latency}.items() if v is not None}
            if payload:
                safe_update(router, "provider", payload)

        # Resources panel using processed performance metrics
        if platform_metrics:
            resources_payload = {
                "cpu": platform_metrics.performance.cpu_usage_percent,
                "rss": int(platform_metrics.performance.memory_usage_mb * 1024 * 1024),
                "memory_mb": platform_metrics.performance.memory_usage_mb,
                "disk_io": platform_metrics.performance.disk_io_operations,
                "network_mb": round(platform_metrics.performance.network_bytes_transferred / (1024 * 1024), 2),
            }
            safe_update(router, "resources", resources_payload)
        else:
            # Fallback resources logic
            rss = None
            cpu = None
            try:
                if metrics and hasattr(metrics, "memory_usage_mb") and hasattr(metrics.memory_usage_mb, "_value"):
                    mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore[attr-defined]
                    if isinstance(mem_mb, (int, float)):
                        rss = int(float(mem_mb) * 1024 * 1024)
            except Exception:
                pass
            try:
                if metrics and hasattr(metrics, "cpu_usage_percent") and hasattr(metrics.cpu_usage_percent, "_value"):
                    cpu = metrics.cpu_usage_percent._value.get()  # type: ignore[attr-defined]
            except Exception:
                pass
            payload = {k: v for k, v in {"cpu": cpu, "rss": rss}.items() if v is not None}
            if payload:
                safe_update(router, "resources", payload)

    # Sinks panel
    sinks_payload: dict[str, dict[str, Any]] = {}
    try:
        if csv_sink is not None:
            ts = getattr(csv_sink, "last_write_ts", None)
            val = None
            try:
                if ts is None:
                    val = None
                elif hasattr(ts, "isoformat"):
                    val = ts.isoformat()
                else:
                    val = str(ts)
            except Exception:
                val = None
            sinks_payload["csv_sink"] = {"last_write": val}
    except Exception:
        pass
    try:
        if influx_sink is not None:
            ts = getattr(influx_sink, "last_write_ts", None)
            val = None
            try:
                if ts is None:
                    val = None
                elif hasattr(ts, "isoformat"):
                    val = ts.isoformat()
                else:
                    val = str(ts)
            except Exception:
                val = None
            sinks_payload["influx_sink"] = {"last_write": val}
    except Exception:
        pass
        if sinks_payload:
            safe_update(router, "sinks", sinks_payload)

    # Enhanced indices panel using processed metrics
        if platform_metrics and platform_metrics.indices:
            # Use the processed index metrics directly
            index_metrics: dict[str, dict[str, Any]] = {}
            for idx_name, idx_data in platform_metrics.indices.items():
                if idx_name in indices:
                    # Format: current_legs (cumulative_avg) - use cycles completed as proxy for total_cycles
                    current_legs = idx_data.current_cycle_legs
                    cumulative_legs = idx_data.cumulative_legs
                    cycles_completed = platform_metrics.collection_cycle or 1
                    avg_legs = round(cumulative_legs / cycles_completed) if cycles_completed > 0 else 0

                    # Determine status based on success rate
                    status = "OK" if idx_data.success_rate >= 0.8 else "WARN"

                    row = {
                        "legs": f"{current_legs} ({avg_legs})",
                        "fails": idx_data.data_quality_issues,
                        "status": status,
                        "last_update": idx_data.last_collection_time,
                        "dq_score": idx_data.data_quality_score,
                        "success_rate": idx_data.success_rate,
                    }
                    index_metrics[str(idx_name)] = row

            if index_metrics:
                safe_update(router, "indices", index_metrics)
        else:
            # Fallback to legacy indices logic
            per_index_last: Mapping[str, Any] | None = None
            try:
                if metrics and hasattr(metrics, "_per_index_last_cycle_options"):
                    per_index_last = metrics._per_index_last_cycle_options
            except Exception:
                per_index_last = None

            index_metrics = {}
            for idx in indices:
                legs = None
                try:
                    if per_index_last is not None and idx in per_index_last:
                        legs = per_index_last.get(idx)
                except Exception:
                    legs = None
                fails = 0
                status = "OK" if (isinstance(legs, (int, float)) and legs is not None and legs >= 0) else "WARN"
                row = {"legs": legs, "fails": fails, "status": status}
                index_metrics[str(idx)] = row
            if index_metrics:
                safe_update(router, "indices", index_metrics)

    # Analytics panel using processed metrics
        if platform_metrics:
            analytics_payload = {
                "options_processed": platform_metrics.performance.options_processed_total,
                "options_per_minute": platform_metrics.performance.options_per_minute,
                "cache_hit_rate": platform_metrics.collection.cache_hit_rate,
                "batch_efficiency": platform_metrics.collection.batch_efficiency,
                "data_quality_score": platform_metrics.performance.data_quality_score,
                "api_success_rate": platform_metrics.performance.api_success_rate,
                "total_errors": platform_metrics.collection.total_errors,
                "error_rate": platform_metrics.collection.error_rate_per_hour,
            }
            safe_update(router, "analytics", analytics_payload)

    # Storage panel using processed storage metrics
        if platform_metrics:
            storage_payload = {
                "csv_files_created": platform_metrics.storage.csv_files_created,
                "csv_records_written": platform_metrics.storage.csv_records_written,
                "influx_points_written": platform_metrics.storage.influxdb_points_written,
                "csv_disk_usage_mb": platform_metrics.storage.csv_disk_usage_mb,
                "backup_files_created": platform_metrics.storage.backup_files_created,
                "backup_size_mb": platform_metrics.storage.backup_size_mb,
                "influx_success_rate": platform_metrics.storage.influxdb_write_success_rate,
                "last_backup": platform_metrics.storage.last_backup_time,
            }
            safe_update(router, "storage", storage_payload)

    # Stream panel: one item per index (disabled by default; prefer bridge + factory)
        # Keep OFF by default to avoid multiple writers (bridge handles indices_stream cadence)
        emit_stream = _truthy("G6_PUBLISHER_EMIT_INDICES_STREAM", default=False)
        sr_int = None
        try:
            if success_rate_pct is not None:
                sr_int = int(round(success_rate_pct))
        except Exception:
            sr_int = None

        # Get per-index data for streaming
        per_index_last: Mapping[str, Any] | None = None
        try:
            if metrics and hasattr(metrics, "_per_index_last_cycle_options"):
                per_index_last = metrics._per_index_last_cycle_options
        except Exception:
            per_index_last = None

        if emit_stream:
            for idx in indices:
                legs = None
                try:
                    if per_index_last is not None and idx in per_index_last:
                        legs = per_index_last.get(idx)
                except Exception:
                    legs = None
                # Compute status and reason via shared helper (panels style)
                # NOTE: Prefer keeping logic centralized in src/panels/helpers.py to avoid drift with UI/factory.
                try:
                    from src.panels.helpers import compute_status_and_reason
                    status, reason = compute_status_and_reason(success_pct=sr_int, legs=legs, style='panels')
                except Exception:
                    status = "OK" if sr_int is None or (isinstance(sr_int, int) and sr_int >= 95) else ("WARN" if isinstance(sr_int, int) and sr_int >= 80 else "ERROR")
                    reason = None
                item = {
                    "index": idx,
                    "legs": legs,
                    "avg": round(float(elapsed_sec), 3),
                    "success": sr_int,
                    "status": status,
                    "cycle": cycle,
                }
                if reason:
                    item["status_reason"] = reason
                safe_append(router, "indices_stream", item, cap=50, kind="stream")
