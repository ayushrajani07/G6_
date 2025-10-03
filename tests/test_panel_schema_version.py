import json
import os
from pathlib import Path

from src.utils.output import PanelFileSink, OutputEvent
from src.panels.version import PANEL_SCHEMA_VERSION


def test_panel_schema_version_wrapper(tmp_path: Path, monkeypatch):
    """When schema wrapper is enabled, emitted panel includes schema_version.

    Also keeps legacy 'version' field for backward compatibility.
    """
    monkeypatch.setenv("G6_PANELS_SCHEMA_WRAPPER", "1")
    sink = PanelFileSink(base_dir=str(tmp_path))
    evt = OutputEvent(
        timestamp=OutputEvent.now_iso(),
        level="info",
        message="panel update",
        data={"foo": 42},
        extra={"_panel": "demo", "_kind": "demo"},
    )
    sink.emit(evt)
    panel_path = tmp_path / "demo.json"
    assert panel_path.exists(), "panel file should be written"
    with panel_path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    # Wrapper fields
    assert obj.get("schema_version") == PANEL_SCHEMA_VERSION
    assert obj.get("version") == PANEL_SCHEMA_VERSION  # legacy compatibility
    assert "panel" in obj and isinstance(obj["panel"], dict)
    inner = obj["panel"]
    assert inner.get("data", {}).get("foo") == 42 or inner.get("data") == {"foo": 42}
