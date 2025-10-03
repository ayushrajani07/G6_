import os
import importlib
from typing import Dict, Any

from src.panels import factory as panels_factory


class DummyReader:  # minimal object satisfying build_panels interface usage
    def get_provider_data(self):  # pragma: no cover - minimal stub
        return {}

    def get_resources_data(self):  # pragma: no cover
        return {}

    def get_cycle_data(self):  # pragma: no cover
        return {}

    def get_health_data(self):  # pragma: no cover
        return {}

    def get_indices_data(self):  # pragma: no cover
        return {}


def _build_status(alerts):
    return {"adaptive_alerts": alerts}


def test_adaptive_alerts_severity_meta_present(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "1")
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES", "3")
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK", "2")
    # Construct minimal enriched alerts manually (simulate prior enrichment)
    alerts = [
        {"type": "interpolation_high", "message": "f=0.8", "severity": "critical"},
        {"type": "risk_delta_drift", "message": "d=0.07", "severity": "warn"},
    ]
    status: Dict[str, Any] = _build_status(alerts)
    panels = panels_factory.build_panels(DummyReader(), status)  # type: ignore[arg-type]
    adaptive = panels.get("adaptive_alerts")
    assert adaptive, "adaptive_alerts panel missing"
    meta = adaptive.get("severity_meta")
    assert meta, "severity_meta missing"
    # Basic shape assertions
    assert meta.get("decay_cycles") == 3
    assert meta.get("min_streak") == 2
    rules = meta.get("rules")
    assert isinstance(rules, dict) and rules, "rules absent or not dict"
    # Ensure at least one known rule present
    assert "interpolation_high" in rules or "risk_delta_drift" in rules
