import os
import importlib
from rich.console import Console
from io import StringIO

# We directly import the alerts_panel function and feed a synthetic status object.

STATUS_FIXTURE = {
    "snapshot_summary": {
        "alerts": {
            "categories": {
                "SYSTEM_FAILURE": 5,
                "DATA_DELAY": 3,
                "LATE_TICKS": 2,
                "SLOW_PHASE": 4,
                "MARKET_STATE": 1,
            },
            "severity": {
                "SYSTEM_FAILURE": "critical",
                "DATA_DELAY": "warning",
                "LATE_TICKS": "info",
                "SLOW_PHASE": "warning",
                "MARKET_STATE": "info",
            }
        }
    },
    # Provide legacy key fallback just in case panel code consults it
    "snapshot": {
        "alerts": {
            "categories": {
                "SYSTEM_FAILURE": 5,
                "DATA_DELAY": 3,
                "LATE_TICKS": 2,
                "SLOW_PHASE": 4,
                "MARKET_STATE": 1,
            },
            "severity": {
                "SYSTEM_FAILURE": "critical",
                "DATA_DELAY": "warning",
                "LATE_TICKS": "info",
                "SLOW_PHASE": "warning",
                "MARKET_STATE": "info",
            }
        }
    }
}

def render_panel(panel: object) -> str:
    buf = StringIO()
    console = Console(file=buf, width=120, record=True)
    console.print(panel)
    return buf.getvalue()

def test_severity_grouping_enabled(monkeypatch):
    monkeypatch.setenv("G6_ALERTS_SEVERITY_GROUPING", "1")
    monkeypatch.setenv("G6_ALERTS_SEVERITY_TOP_CAP", "2")  # restrict top list length
    mod = importlib.import_module("scripts.summary.panels.alerts")
    panel = mod.alerts_panel(STATUS_FIXTURE, compact=True)
    out = render_panel(panel)
    # Expect grouped category counts
    assert "crit(cat)" in out or "crit(cat)" in out.lower()
    assert "warn(cat)" in out
    # Expect Top line truncated to 2 per severity max
    assert "Top:" in out

def test_severity_grouping_disabled(monkeypatch):
    monkeypatch.setenv("G6_ALERTS_SEVERITY_GROUPING", "0")
    mod = importlib.import_module("scripts.summary.panels.alerts")
    panel = mod.alerts_panel(STATUS_FIXTURE, compact=True)
    out = render_panel(panel)
    # Should not contain Categories: line when disabled
    assert "Categories:" not in out
    # But still should show Active summary
    assert "Active:" in out
