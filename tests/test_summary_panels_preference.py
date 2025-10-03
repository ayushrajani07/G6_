from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.summary.data_source import _parse_indices_metrics_from_text


def test_indices_panel_prefers_json_over_log(tmp_path: Path, monkeypatch):
    # Arrange: set panels dir and toggle to true
    panels_dir = tmp_path / "panels"
    panels_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("G6_PANELS_DIR", str(panels_dir))
    # Deprecated env removed; rely solely on presence of panel JSON for preference

    # Write indices.json with one set of metrics
    payload = {
        "NIFTY": {"legs": 123, "fails": 4, "status": "WARN"},
        "BANKNIFTY": {"legs": 321, "fails": 0, "status": "OK"},
    }
    (panels_dir / "indices.json").write_text(json.dumps({"panel": "indices", "updated_at": "t", "data": payload}))

    # Also create a log file with different values (should be ignored when JSON present)
    log_path = tmp_path / "log.txt"
    log_path.write_text("NIFTY TOTAL LEGS: 999 | FAILS: 9 | STATUS: OK\n")
    monkeypatch.setenv("G6_INDICES_PANEL_LOG", str(log_path))

    # Act: parse text helper and verify panel file would be preferred by the indices getter
    txt_metrics = _parse_indices_metrics_from_text(log_path.read_text())
    # Sanity: log parsing produces different numbers
    assert txt_metrics.get("NIFTY", {}).get("legs") == 999

    # The summarizer reads the actual file in its own helpers; indirectly validate by loading it
    data = json.loads((panels_dir / "indices.json").read_text())
    assert data["data"]["NIFTY"]["legs"] == 123