from __future__ import annotations

import json, os
from pathlib import Path
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, OutputPlugin, SummarySnapshot

class CaptureStop(OutputPlugin):
    name = "capture_stop"
    def __init__(self):
        self.count = 0
    def setup(self, context):
        pass
    def process(self, snap: SummarySnapshot):
        self.count += 1
        if self.count >= 1:
            raise KeyboardInterrupt()
    def teardown(self):
        pass


def _write_status(path: Path, timestamp: str):
    status = {
        # No loop.cycle -> forces bucket gating path
        "timestamp": timestamp,
        "indices_detail": {
            "BANKNIFTY": {"status": "OK", "dq": {"score_percent": 88}, "timestamp": timestamp},
        },
    }
    path.write_text(json.dumps(status), encoding="utf-8")


def test_stream_gater_bucket_mode(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime_status.json"
    _write_status(status_file, "2025-10-05T10:00:05Z")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))
    monkeypatch.setenv("G6_STREAM_GATE_MODE", "minute")

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()

    loop = UnifiedLoop([
        PanelsWriter(str(panels_dir)),
        CaptureStop(),
    ], panels_dir=str(panels_dir), refresh=0.01)

    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass

    stream_path = panels_dir / "indices_stream.json"
    assert stream_path.exists(), "indices_stream.json not created in bucket mode"
    items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert len(items) == 1
    # time_hms decoration present
    assert 'time_hms' in items[0]
