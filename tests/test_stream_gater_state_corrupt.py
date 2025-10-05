from __future__ import annotations

import json, os
from pathlib import Path
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, OutputPlugin, SummarySnapshot

class StopAfter(OutputPlugin):
    name = "stop_after"
    def __init__(self):
        self.called = 0
    def setup(self, context):
        pass
    def process(self, snap: SummarySnapshot):
        self.called += 1
        raise KeyboardInterrupt()
    def teardown(self):
        pass


def _write_status(path: Path, cycle: int, ts: str):
    status = {
        "loop": {"cycle": cycle, "last_run": ts},
        "indices_detail": {
            "FINNIFTY": {"status": "OK", "dq": {"score_percent": 77}, "last_update": ts},
        },
    }
    path.write_text(json.dumps(status), encoding="utf-8")


def test_stream_gater_state_corrupt_recovers(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime_status.json"
    _write_status(status_file, 5, "2025-10-05T10:00:00Z")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))
    monkeypatch.setenv("G6_STREAM_GATE_MODE", "cycle")

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()
    # Write corrupt state file
    corrupt_path = panels_dir / ".indices_stream_state.json"
    corrupt_path.write_text("{not-json", encoding='utf-8')

    loop = UnifiedLoop([
        PanelsWriter(str(panels_dir)),
        StopAfter(),
    ], panels_dir=str(panels_dir), refresh=0.01)

    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass

    # Should still have appended first item despite corrupt state
    stream_path = panels_dir / "indices_stream.json"
    assert stream_path.exists()
    items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert len(items) == 1
