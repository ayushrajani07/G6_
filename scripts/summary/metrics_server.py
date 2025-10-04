"""Lightweight Prometheus metrics HTTP server bootstrap (Phase 6)."""
from __future__ import annotations
import threading, logging, os
from scripts.summary.env_config import load_summary_env

logger = logging.getLogger(__name__)

_started = False


def start_metrics_server() -> None:
    global _started
    if _started:
        return
    try:
        from prometheus_client import start_http_server  # type: ignore
    except Exception:
        logger.debug("prometheus_client not available; metrics server not started")
        return
    try:
        port = load_summary_env().metrics_http_port
    except Exception:
        port = int(os.getenv('G6_METRICS_HTTP_PORT', '9325') or 9325)
    start_http_server(port)
    _started = True
    logger.debug("Metrics HTTP server listening on :%s", port)

__all__ = ["start_metrics_server"]
