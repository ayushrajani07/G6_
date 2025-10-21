#!/usr/bin/env python3
"""
Runtime health integration helpers.

Stores optional references to HealthServer and HealthMetricsExporter when enabled
by bootstrap. Provides safe no-op functions that callers can use without needing
to check flags.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import HealthLevel, HealthState

if TYPE_CHECKING:  # pragma: no cover - for type checking only
    from .api_server import HealthServer
    from .prom_exporter import HealthMetricsExporter

_SERVER: HealthServer | None = None
_EXPORTER: HealthMetricsExporter | None = None


def set_current(server: HealthServer | None, exporter: HealthMetricsExporter | None) -> None:
    global _SERVER, _EXPORTER
    _SERVER = server
    _EXPORTER = exporter


def clear_current() -> None:
    global _SERVER, _EXPORTER
    _SERVER = None
    _EXPORTER = None


def set_overall(level: HealthLevel, state: HealthState | str) -> None:
    try:
        if _SERVER is not None:
            _SERVER.set_overall(level, state)
        if _EXPORTER is not None and _EXPORTER.enabled():
            _EXPORTER.set_overall(level, state)
        # Optional alert forwarding
        try:
            from .alerts.alert_manager import AlertManager  # lazy import to avoid cycles
            am = AlertManager.get_instance()
            if getattr(am, 'enabled', False):
                am.process_health_update("overall", int(level), state, None)
        except Exception:
            pass
    except Exception:
        pass


def set_component(name: str, level: HealthLevel, state: HealthState | str) -> None:
    try:
        if _SERVER is not None:
            _SERVER.set_component(name, level, state)
        if _EXPORTER is not None and _EXPORTER.enabled():
            _EXPORTER.set_component(name, level, state)
        # Optional alert forwarding
        try:
            from .alerts.alert_manager import AlertManager  # lazy import to avoid cycles
            am = AlertManager.get_instance()
            if getattr(am, 'enabled', False):
                am.process_health_update(name, int(level), state, None)
        except Exception:
            pass
    except Exception:
        pass
