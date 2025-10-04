"""Metrics server bootstrap (extracted from metrics.py).

Single-responsibility module for starting the Prometheus HTTP endpoint and
constructing the process-wide `MetricsRegistry` instance while launching
resource sampling & watchdog background threads (delegated to resource_sampling).

Public API:
  setup_metrics_server(...): -> (metrics_registry, shutdown_callable)

Backward compatibility: `metrics.get_metrics()` will still auto-call this
when the singleton is absent; import order remains unchanged.
"""
from __future__ import annotations

import os
import logging
from typing import Callable, Tuple
from prometheus_client import start_http_server, CollectorRegistry, REGISTRY  # type: ignore

from .metrics import MetricsRegistry  # local import to avoid circular: class defined there
from . import _singleton  # central singleton anchor

logger = logging.getLogger(__name__)

# Local variables retained only for ancillary metadata; registry stored centrally.
_METRICS_SINGLETON = None  # type: ignore[var-annotated]
_METRICS_PORT = None       # type: ignore[var-annotated]
_METRICS_HOST = None       # type: ignore[var-annotated]
_METRICS_META = None       # populated with simple metadata for introspection


def _clear_default_registry() -> None:
    """Best-effort reset of default Prometheus registry (used when reset/force flags set)."""
    try:  # pragma: no cover - defensive path
        collectors = list(REGISTRY._names_to_collectors.values())  # type: ignore[attr-defined]
        for c in collectors:
            try:
                REGISTRY.unregister(c)  # type: ignore[arg-type]
            except Exception:
                pass
        logger.info("Prometheus default registry cleared via reset flag")
    except Exception:
        logger.warning("Registry reset attempt failed; proceeding")


def setup_metrics_server(port: int = 9108, host: str = "0.0.0.0", *,
                         enable_resource_sampler: bool = True,
                         sampler_interval: int = 10,
                         use_custom_registry: bool | None = None,
                         reset: bool = False) -> Tuple[MetricsRegistry, Callable[[], None]]:
    """Start metrics HTTP endpoint and initialize the MetricsRegistry singleton.

    Returns the registry and a no-op shutdown callable (reserved for future lifecycle hooks).
    Idempotent: subsequent calls reuse the existing singleton unless `reset` or G6_FORCE_NEW_REGISTRY is set.
    """
    global _METRICS_SINGLETON, _METRICS_PORT, _METRICS_HOST, _METRICS_META  # noqa: PLW0603
    force_new = os.environ.get('G6_FORCE_NEW_REGISTRY','').lower() in {'1','true','yes','on'}
    existing = _singleton.get_singleton()
    if existing is not None and not reset and not force_new:
        if (port != _METRICS_PORT) or (host != _METRICS_HOST):
            logger.warning(
                "setup_metrics_server called again with different host/port (%s:%s) != (%s:%s); reusing existing server",
                host, port, _METRICS_HOST, _METRICS_PORT,
            )
        else:
            logger.debug("setup_metrics_server called again; returning existing singleton")
        _METRICS_SINGLETON = existing
        return existing, (lambda: None)

    if reset or force_new:
        _clear_default_registry()
        _METRICS_SINGLETON = None
        _METRICS_PORT = None
        _METRICS_HOST = None

    if use_custom_registry is None:
        use_custom_registry = False

    if use_custom_registry:
        registry = CollectorRegistry()
        start_http_server(port, addr=host, registry=registry)
    else:
        start_http_server(port, addr=host)
    _METRICS_PORT = port
    _METRICS_HOST = host

    fancy = os.environ.get('G6_FANCY_CONSOLE','').lower() in {'1','true','yes','on'}
    log_fn = logger.debug if fancy else logger.info
    log_fn(f"Metrics server started on {host}:{port}")
    log_fn(f"Metrics available at http://{host}:{port}/metrics")

    # Atomically create registry if absent to prevent race between concurrent imports/tests.
    def _build():  # local factory
        return MetricsRegistry()
    metrics = _singleton.create_if_absent(_build)
    _METRICS_SINGLETON = metrics

    # Background threads
    if enable_resource_sampler:
        try:
            from .resource_sampling import start_resource_sampler as _srs  # type: ignore
            _srs(metrics, sampler_interval, fancy)
        except Exception:
            logger.debug("start_resource_sampler failed", exc_info=True)
    try:
        from .resource_sampling import start_watchdog as _sw  # type: ignore
        _sw(metrics, sampler_interval)
    except Exception:
        logger.debug("start_watchdog failed", exc_info=True)

    # Lightweight metadata snapshot (consumed by metrics.get_metrics_metadata)
    try:
        _METRICS_META = {
            'host': host,
            'port': port,
            'resource_sampler': bool(enable_resource_sampler),
            'watchdog': True,
            'custom_registry': bool(use_custom_registry),
            'reset': bool(reset or force_new),
        }
    except Exception:
        pass

    return metrics, (lambda: None)


def get_server_singleton():  # pragma: no cover - thin accessor
    return _singleton.get_singleton()


__all__ = ["setup_metrics_server", "get_server_singleton"]