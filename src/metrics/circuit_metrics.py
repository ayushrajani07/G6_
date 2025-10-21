#!/usr/bin/env python3
"""
Circuit breaker metrics exporter (optional). Uses existing MetricsRegistry gauges/counters.
This keeps a minimal view: per-breaker state and current timeout.
"""
from __future__ import annotations

import threading
import time

from ..utils.adaptive_circuit_breaker import CircuitState
from ..utils.circuit_registry import _REGISTRY  # internal map; safe read-only


class CircuitMetricsExporter:
    def __init__(self, metrics, interval_seconds: float = 15.0):
        self.metrics = metrics
        self.interval = max(5.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="g6-circuit-metrics", daemon=True)
        # Lazy-create metrics if not present; use try/except to avoid duplicate registration
        try:
            self._state_g = self.metrics.index_dq_issues_total  # reuse existing object to ensure registry OK
        except Exception:
            pass
        # Create dedicated gauges (best-effort)
        try:
            from prometheus_client import Gauge
            # Legacy 'name' label (kept for compatibility)
            try:
                self.cb_state = Gauge('g6_circuit_state_simple', 'Circuit state (0=closed,1=half,2=open)', ['name'])
            except Exception:
                self.cb_state = None
            try:
                self.cb_timeout = Gauge('g6_circuit_current_timeout_seconds', 'Current reset timeout for circuit', ['name'])
            except Exception:
                self.cb_timeout = None
            # Standardized 'component' label mirrors the above values
            try:
                self.cb_state_component = Gauge('g6_circuit_state', 'Circuit state (0=closed,1=half,2=open)', ['component'])
            except Exception:
                self.cb_state_component = None
            try:
                self.cb_timeout_component = Gauge('g6_circuit_timeout_seconds', 'Current reset timeout for circuit', ['component'])
            except Exception:
                self.cb_timeout_component = None
        except Exception:
            self.cb_state = None
            self.cb_timeout = None
            self.cb_state_component = None
            self.cb_timeout_component = None

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            for _ in range(int(self.interval / 0.5)):
                if self._stop.is_set():
                    return
                time.sleep(0.5)

    def _tick(self):
        # Snapshot registry
        items = list(_REGISTRY.items())
        for name, br in items:
            try:
                st = br.state
                code = 0 if st == CircuitState.CLOSED else (1 if st == CircuitState.HALF_OPEN else 2)
                state_legacy = getattr(self, 'cb_state', None)
                if state_legacy is not None:
                    state_legacy.labels(name=name).set(code)
                state_component = getattr(self, 'cb_state_component', None)
                if state_component is not None:
                    state_component.labels(component=name).set(code)
                # Access protected fields guardedly
                timeout = getattr(br, '_current_timeout', None)
                if timeout is not None:
                    timeout_legacy = getattr(self, 'cb_timeout', None)
                    if timeout_legacy is not None:
                        timeout_legacy.labels(name=name).set(float(timeout))
                    timeout_component = getattr(self, 'cb_timeout_component', None)
                    if timeout_component is not None:
                        timeout_component.labels(component=name).set(float(timeout))
            except Exception:
                pass


__all__ = ["CircuitMetricsExporter"]
