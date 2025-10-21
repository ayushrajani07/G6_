"""Resource sampling & watchdog helpers extracted from metrics.setup_metrics_server.

Behavior preserved; functions swallow exceptions to mirror original resilience.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


def start_resource_sampler(metrics, sampler_interval: int, fancy: bool) -> threading.Thread | None:
    try:
        import psutil  # type: ignore
    except ImportError:
        try:
            logger.warning("psutil not installed; resource sampler disabled")
        except Exception:
            pass
        return None

    def _sample():  # pragma: no cover - timing/background
        while True:
            try:
                p = psutil.Process()
                with p.oneshot():
                    mem_mb = p.memory_info().rss / (1024 * 1024)
                    cpu_percent = p.cpu_percent(interval=None)
                try:
                    metrics.memory_usage_mb.set(mem_mb)
                    metrics.cpu_usage_percent.set(cpu_percent)
                except Exception:
                    pass
                # Network delta
                try:
                    net = psutil.net_io_counters()
                    prev_net = getattr(metrics, '_prev_net_bytes', (0, 0))
                    d_sent = max(0, net.bytes_sent - prev_net[0])
                    d_recv = max(0, net.bytes_recv - prev_net[1])
                    try:
                        metrics.network_bytes_transferred.inc(d_sent + d_recv)
                    except Exception:
                        pass
                    metrics._prev_net_bytes = net.bytes_sent, net.bytes_recv
                except Exception:
                    pass
                # Disk ops delta
                try:
                    dio = psutil.disk_io_counters()
                    if dio is not None and hasattr(dio, 'read_count') and hasattr(dio, 'write_count'):
                        if hasattr(metrics, '_prev_disk_ops'):
                            d_ops = max(0, (dio.read_count + dio.write_count) - metrics._prev_disk_ops)
                            try:
                                metrics.disk_io_operations.inc(d_ops)
                            except Exception:
                                pass
                        metrics._prev_disk_ops = dio.read_count + dio.write_count
                except Exception:
                    pass
            except Exception:
                logger.debug("Resource sampling iteration failed", exc_info=True)
            time.sleep(sampler_interval)
    t = threading.Thread(target=_sample, name="g6-resource-sampler", daemon=True)
    t.start()
    try:
        if fancy:
            logger.debug("Resource sampler thread started (interval=%ss)" % sampler_interval)
        else:
            logger.info("Resource sampler thread started (interval=%ss)" % sampler_interval)
    except Exception:
        pass
    return t


def start_watchdog(metrics, sampler_interval: int) -> threading.Thread:
    check_interval = max(5, sampler_interval)
    def _watchdog():  # pragma: no cover - timing/background
        last_cycle = 0.0
        last_options = 0.0
        stale_intervals = 0
        while True:
            try:
                current_cycles = getattr(metrics, '_cycle_total', None)
                current_options = getattr(metrics, '_last_cycle_options', None)
                in_progress = 0
                try:
                    if hasattr(metrics, 'collection_cycle_in_progress'):
                        in_progress = 1 if getattr(metrics.collection_cycle_in_progress, '_value', None) else 0
                except Exception:
                    pass
                progressed = False
                if current_cycles is not None and current_cycles > last_cycle:
                    progressed = True
                if current_options is not None and current_options > last_options:
                    progressed = True
                if progressed or in_progress:
                    stale_intervals = 0
                    last_cycle = current_cycles if current_cycles is not None else last_cycle
                    last_options = current_options if current_options is not None else last_options
                else:
                    stale_intervals += 1
                    if stale_intervals >= 6:
                        try:
                            metrics.metric_stall_events.labels(metric='collection').inc()
                        except Exception:
                            pass
                        stale_intervals = 0
            except Exception:
                logger.debug("Watchdog iteration failed", exc_info=True)
            time.sleep(check_interval)
    t = threading.Thread(target=_watchdog, name="g6-watchdog", daemon=True)
    t.start()
    return t
