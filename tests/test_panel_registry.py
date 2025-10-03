from scripts.summary.domain import build_domain_snapshot
from scripts.summary.panel_registry import build_all_panels, DEFAULT_PANEL_PROVIDERS


def test_build_all_panels_basic():
    raw = {
        "cycle": {"number": 10, "duration": 0.33, "success_rate": 95.0},
        "indices": ["A", "B", "C"],
        "alerts": {"total": 1, "severity_counts": {"warn": 1}},
        "resources": {"cpu_pct": 1.2, "memory_mb": 64.0},
    }
    snap = build_domain_snapshot(raw, ts_read=123.0)
    panels = build_all_panels(snap)
    keys = [p.key for p in panels]
    assert keys == [p.key for p in DEFAULT_PANEL_PROVIDERS]
    cycle_panel = panels[0]
    assert any("cycle:" in line for line in cycle_panel.lines)
    alerts_panel = [p for p in panels if p.key == "alerts"][0]
    assert any("total:" in line for line in alerts_panel.lines)


def test_build_all_panels_handles_error():
    class BadProvider:
        key = "bad"
        def build(self, snapshot):  # noqa: D401
            raise RuntimeError("boom")
    raw = {}
    snap = build_domain_snapshot(raw)
    panels = build_all_panels(snap, providers=(*DEFAULT_PANEL_PROVIDERS, BadProvider()))
    assert any(p.key == "bad" and p.title == "ERROR" for p in panels)
