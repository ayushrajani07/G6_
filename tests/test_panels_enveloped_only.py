import os, json, tempfile, shutil
from pathlib import Path

# This test exercises the panel plugin envelope emission path indirectly by constructing
# a minimal status dict and invoking the panel extraction helper via the base plugin.

from scripts.summary.plugins.base import PanelsWriter  # using concrete writer to access _extract_panels

class _DummyPlugin(PanelsWriter):
    """Lightweight harness exposing internal _extract_panels for test purposes.

    In production the writer is invoked via process(); here we call the extraction
    logic directly to assert envelope emission structure without touching filesystem.
    """
    def __init__(self):
        # panels_dir required by PanelsWriter ctor but unused for direct extraction path
        super().__init__(panels_dir=str(Path(tempfile.gettempdir())))

    def extract(self, status):  # convenience wrapper
        return self._extract_panels(status)  # type: ignore[attr-defined]

def _sample_status():
    return {
        "indices_detail": {"NIFTY": {"status": "OK", "dq": {"score_percent": 97}, "age": 5}},
        "alerts": [{"id": 1, "severity": "warn"}],
        "memory": {"rss_mb": 123},
        "loop": {"cycle": 10, "last_duration": 0.12, "target_interval": 1.0},
        "performance": {"p50": 0.01},
        "analytics": {"calc": 42},
        "app": {"version": "1.2.3"},
    }


def test_enveloped_only_default(monkeypatch):
    monkeypatch.delenv('G6_PANELS_LEGACY_COMPAT', raising=False)
    plugin = _DummyPlugin()
    panels = plugin.extract(_sample_status())
    # Expect only *_enveloped.json keys
    assert any(k.endswith('_enveloped.json') for k in panels.keys())
    assert all(not k.endswith('.json') or k.endswith('_enveloped.json') for k in panels.keys()), panels.keys()
    # Spot check envelope structure
    idx_env = panels.get('indices_panel_enveloped.json')
    assert idx_env and idx_env.get('panel') == 'indices_panel'
    assert 'data' in idx_env and 'meta' in idx_env
    assert isinstance(idx_env['meta'].get('hash'), str)


def test_enveloped_with_legacy(monkeypatch):
    monkeypatch.setenv('G6_PANELS_LEGACY_COMPAT','1')
    plugin = _DummyPlugin()
    panels = plugin.extract(_sample_status())
    # Both enveloped and legacy forms should exist for a representative panel
    assert 'performance_enveloped.json' in panels
    assert 'performance.json' in panels
    assert panels['performance_enveloped.json']['data'] == panels['performance.json']
