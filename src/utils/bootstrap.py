"""Runtime bootstrap utilities for G6 Platform.

Centralizes common startup concerns so entrypoints remain thin:
- sys.path assurance
- dotenv/environment loading (optional if python-dotenv installed)
- logging initialization
- configuration load & normalization (ConfigWrapper)
- metrics server startup (optional toggle)

It returns a BootContext containing references to commonly used
subsystems so callers can wire collectors without repeating boilerplate.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from src.config.config_wrapper import ConfigWrapper
from src.config.loader import ConfigError, load_and_process_config
from src.health import AlertManager, HealthLevel, HealthMetricsExporter, HealthServer, HealthState
from src.health import runtime as health_runtime
from src.metrics import setup_metrics_server  # facade import (modularized)
from src.metrics.circuit_metrics import CircuitMetricsExporter

from .logging_utils import setup_logging
from .path_utils import ensure_sys_path

try:  # optional dependency
    from dotenv import load_dotenv  # type: ignore
    _HAVE_DOTENV = True
except Exception:  # pragma: no cover
    _HAVE_DOTENV = False


@dataclass
class BootContext:
    config: ConfigWrapper
    metrics: Any
    stop_metrics: Any
    log_file: str
    config_path: str


def load_raw_config(path: str) -> dict:
    if not os.path.exists(path):
        # Minimal default; unified_main has richer create_default_config but for early boot we keep lean
        return {"storage": {"csv_dir": "data/g6_data"}}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:  # pragma: no cover - fallback path
        logging.error("Bootstrap config load failed (%s): %s", path, e)
        try:
            from src.error_handling import handle_data_error
            handle_data_error(e, component="bootstrap", context={"op": "load_raw_config", "path": path})
        except Exception:
            pass
        return {"storage": {"csv_dir": "data/g6_data"}}


def bootstrap(
    config_path: str = "config/config.json",
    log_level: str = "INFO",
    log_file: str = "logs/g6_platform.log",
    enable_metrics: bool = True,
    metrics_reset: bool = False,
    metrics_use_custom_registry: bool | None = None,
) -> BootContext:
    """Perform startup sequence and return BootContext.

    Parameters
    ----------
    config_path: path to the JSON config file (canonical: config/config.json)
    log_level: desired logging level
    log_file: path to log file (will ensure parent directory exists)
    enable_metrics: disable if caller wants to manage metrics manually
    """
    ensure_sys_path()

    # Logging
    setup_logging(log_level, log_file)

    # Env loading
    if _HAVE_DOTENV:
        try:
            load_dotenv()  # type: ignore
            logging.debug("Environment variables loaded from .env")
        except Exception as e:  # pragma: no cover
            logging.warning("dotenv load failed: %s", e)
            try:
                from src.error_handling import handle_api_error
                handle_api_error(e, component="bootstrap", context={"op": "load_dotenv"})
            except Exception:
                pass

    # Config
    raw = None
    # Optional new loader with migration+validation behind env flag
    from src.utils.env_flags import is_truthy_env  # type: ignore
    enhanced_cfg = is_truthy_env('G6_ENHANCED_CONFIG')
    if enhanced_cfg or is_truthy_env('G6_CONFIG_LOADER'):
        try:
            processed, _warns = load_and_process_config(config_path)
            raw = processed
        except ConfigError as e:
            logging.warning("New config loader failed (%s); falling back to legacy load_raw_config", e)
            raw = load_raw_config(config_path)
    else:
        raw = load_raw_config(config_path)
    config = ConfigWrapper(raw)

    # Metrics
    metrics = None
    stop = lambda: None
    circuit_exporter = None
    health_server = None
    health_exporter = None
    alerts_manager = None
    if enable_metrics and config.get("metrics", {}).get("enabled", True):  # type: ignore[index]
        port = config.metrics_port()
        metrics, stop = setup_metrics_server(port=port, reset=metrics_reset, use_custom_registry=metrics_use_custom_registry)
        # Optional circuit metrics exporter (default off)
        try:
            from src.utils.env_flags import is_truthy_env  # type: ignore
            enable_circuit_metrics = is_truthy_env('G6_CIRCUIT_METRICS') or \
                bool(config.get('resilience', {}).get('circuit_metrics', {}).get('enabled', False))  # type: ignore[index]
            if enable_circuit_metrics:
                interval = float(config.get('resilience', {}).get('circuit_metrics', {}).get('interval', 15.0))  # type: ignore[index]
                circuit_exporter = CircuitMetricsExporter(metrics, interval_seconds=interval)
                circuit_exporter.start()
        except Exception:
            circuit_exporter = None
        # Optional health components (default off)
        try:
            enable_health_api = is_truthy_env('G6_HEALTH_API') or \
                bool(config.get('health', {}).get('api', {}).get('enabled', False))  # type: ignore[index]
            enable_health_prom = is_truthy_env('G6_HEALTH_PROMETHEUS') or \
                bool(config.get('health', {}).get('prometheus', {}).get('enabled', False))  # type: ignore[index]
            if enable_health_api:
                h_host = str(config.get('health', {}).get('api', {}).get('host', '127.0.0.1'))  # type: ignore[index]
                h_port = int(config.get('health', {}).get('api', {}).get('port', 8099))  # type: ignore[index]
                # Minimal readiness check: metrics server started
                def _ready() -> bool:
                    return metrics is not None
                health_server = HealthServer(host=h_host, port=h_port, ready_check=_ready)
                health_server.start()
                # Set initial overall to UNKNOWN
                health_server.set_overall(HealthLevel.UNKNOWN, HealthState.UNKNOWN)
            if enable_health_prom:
                health_exporter = HealthMetricsExporter(namespace='g6')
                if health_exporter.enabled():
                    # Initialize overall to UNKNOWN so metrics exist
                    health_exporter.set_overall(HealthLevel.UNKNOWN, HealthState.UNKNOWN)
            # Publish to runtime helper for other modules to update
            if enable_health_api or enable_health_prom:
                health_runtime.set_current(health_server, health_exporter)
        except Exception:
            health_server = None
            health_exporter = None
        # Optional alerts subsystem (default off)
        try:
            enable_alerts = is_truthy_env('G6_ALERTS') or \
                bool(config.get('health', {}).get('alerts', {}).get('enabled', False))  # type: ignore[index]
            if enable_alerts:
                alerts_cfg = dict(config.get('health', {}).get('alerts', {}))  # type: ignore[index]
                # Allow overriding state directory via env
                state_dir_env = os.environ.get('G6_ALERTS_STATE_DIR')
                if state_dir_env:
                    alerts_cfg['state_directory'] = state_dir_env
                alerts_manager = AlertManager.get_instance()
                alerts_manager.initialize(alerts_cfg)
        except Exception:
            alerts_manager = None

    ctx = BootContext(
        config=config,
        metrics=metrics,
        stop_metrics=stop,
        log_file=log_file,
        config_path=config_path,
    )
    # Wrap stop to ensure exporter stops too
    if circuit_exporter is not None or health_server is not None or health_exporter is not None or alerts_manager is not None:
        old_stop = ctx.stop_metrics
        def _stop_all():
            # Health server stop
            try:
                if health_server is not None:
                    health_server.stop()
            except Exception:
                pass
            try:
                health_runtime.clear_current()
            except Exception:
                pass
            # No explicit stop needed for health_exporter (metrics cleanup occurs on process end)
            try:
                if alerts_manager is not None:
                    alerts_manager.stop()
            except Exception:
                pass
            try:
                if circuit_exporter is not None:
                    circuit_exporter.stop()
            except Exception:
                pass
            try:
                old_stop()
            except Exception:
                pass
        ctx.stop_metrics = _stop_all  # type: ignore
    return ctx

__all__ = ["bootstrap", "BootContext"]
