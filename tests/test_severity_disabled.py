import os
from src.adaptive import severity


def _reset_state():
    severity._RULES_CACHE = None  # type: ignore
    severity._STREAKS.clear()  # type: ignore


def test_severity_disabled_no_enrichment(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "0")
    _reset_state()
    a = {"type": "interpolation_high", "interpolated_fraction": 0.9}
    enriched = severity.enrich_alert(a)
    # Should be identical (no severity key) when disabled
    assert enriched == a


def test_severity_force_allows_replacement(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "1")
    _reset_state()
    a = {"type": "interpolation_high", "interpolated_fraction": 0.9, "severity": "info"}
    # Without FORCE env existing severity retained
    out = severity.enrich_alert(a)
    assert out["severity"] == "info"
    # With FORCE env classification should override
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY_FORCE", "1")
    out2 = severity.enrich_alert(a)
    assert out2["severity"] in ("critical", "warn")  # 0.9 -> critical by defaults
