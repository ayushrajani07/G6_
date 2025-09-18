import json
import os
from pathlib import Path

from src.utils.output import OutputRouter, PanelFileSink


def test_panel_file_sink_writes_indices(tmp_path: Path):
    base = tmp_path / "panels"
    sink = PanelFileSink(str(base), include=["indices"], atomic=True)
    r = OutputRouter([sink], min_level="debug")
    payload = {"NIFTY": {"legs": 10, "fails": 0, "status": "OK"}}
    r.panel_update("indices", payload)
    p = base / "indices.json"
    assert p.exists(), "indices.json should be written"
    data = json.loads(p.read_text("utf-8"))
    assert data["panel"] == "indices"
    assert data["data"] == payload


def test_panel_file_sink_filters_panels(tmp_path: Path):
    base = tmp_path / "panels"
    sink = PanelFileSink(str(base), include=["market"], atomic=False)
    r = OutputRouter([sink], min_level="debug")
    r.panel_update("indices", {"X": 1})
    assert not (base / "indices.json").exists()
    r.panel_update("market", {"state": "OPEN"})
    assert (base / "market.json").exists()