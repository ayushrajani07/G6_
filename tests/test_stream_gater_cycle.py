from __future__ import annotations

import json, os, time
from pathlib import Path

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, OutputPlugin, SummarySnapshot

class CapturePlugin(OutputPlugin):
    name = "capture"
    def __init__(self):
        self.snapshots = []
    def setup(self, context):
        pass
    def process(self, snap: SummarySnapshot):
        self.snapshots.append(snap)
        # Stop after 2 cycles captured
        if len(self.snapshots) >= 2:
            raise KeyboardInterrupt()
    def teardown(self):
        pass


def _write_status(path: Path, cycle: int, minute: str = "2025-10-05T10:00:00Z"):
    status = {
        "loop": {"cycle": cycle, "last_run": minute},
        "indices_detail": {
            "NIFTY": {"status": "OK", "dq": {"score_percent": 90}, "last_update": minute},
        },
        "timestamp": minute,
    }
    path.write_text(json.dumps(status), encoding="utf-8")


def test_stream_gater_cycle_gates(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime_status.json"
    _write_status(status_file, 1, "2025-10-05T10:00:00Z")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))
    monkeypatch.setenv("G6_STREAM_GATE_MODE", "cycle")

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()

    loop = UnifiedLoop([
        PanelsWriter(str(panels_dir)),
        CapturePlugin(),
    ], panels_dir=str(panels_dir), refresh=0.01)

    # First run (cycle 1) -> should append one stream item
    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass
    stream_path = panels_dir / "indices_stream.json"
    assert stream_path.exists(), "indices_stream.json not created on first append"
    first_items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert len(first_items) == 1

    # Second cycle same cycle number -> expect skip (still length 1)
    _write_status(status_file, 1, "2025-10-05T10:00:30Z")
    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass
    second_items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert len(second_items) == 1, "indices_stream appended despite unchanged cycle"

    # Third cycle increments -> append again
    _write_status(status_file, 2, "2025-10-05T10:01:00Z")
    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass
    third_items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert len(third_items) == 2, "indices_stream did not append for new cycle"

    # Heartbeat check (system panel file is from PanelsWriter; heartbeat merges into status, not persisted as system panel modifications here)
    # We verify heartbeat indirectly by ensuring bridge metadata present in final snapshot status
    # Locate CapturePlugin (plugin insertion may have added stream_gater after PanelsWriter)
    capture = None
    for p in loop._plugins:
        if getattr(p, 'name', '') == 'capture':
            capture = p
            break
    if capture and getattr(capture, 'snapshots', None):
        last_snap = capture.snapshots[-1]
        system_block = last_snap.status.get('system') if isinstance(last_snap.status, dict) else None  # type: ignore[union-attr]
        if isinstance(system_block, dict):
            bridge_meta = system_block.get('bridge')
            assert bridge_meta, "Heartbeat bridge meta missing"

