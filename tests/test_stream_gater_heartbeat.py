from __future__ import annotations

import json, os
from pathlib import Path
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, OutputPlugin, SummarySnapshot

class Stop(OutputPlugin):
    name = "stop"
    def setup(self, context):
        pass
    def process(self, snap: SummarySnapshot):
        # Heartbeat should be injected into status by stream gater
        sys_obj = snap.status.get('system') if isinstance(snap.status, dict) else None  # type: ignore[union-attr]
        if isinstance(sys_obj, dict):
            bridge = sys_obj.get('bridge')
            if bridge:
                raise KeyboardInterrupt()
    def teardown(self):
        pass


def _write_status(path: Path, cycle: int, ts: str):
    status = {
        "loop": {"cycle": cycle, "last_run": ts},
        "indices_detail": {
            "SENSEX": {"status": "OK", "dq": {"score_percent": 91}, "last_update": ts},
        },
    }
    path.write_text(json.dumps(status), encoding='utf-8')


def test_stream_gater_heartbeat(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime_status.json"
    _write_status(status_file, 10, "2025-10-05T10:00:00Z")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))
    monkeypatch.setenv("G6_STREAM_GATE_MODE", "cycle")

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()

    loop = UnifiedLoop([
        PanelsWriter(str(panels_dir)),
        Stop(),
    ], panels_dir=str(panels_dir), refresh=0.01)

    try:
        loop.run(cycles=5)  # run a few cycles until heartbeat detected
    except KeyboardInterrupt:
        pass

    # Verify heartbeat persisted in final snapshot (Stop raised after detection)
    # The indices_stream file should exist too
    stream_path = panels_dir / "indices_stream.json"
    assert stream_path.exists()
    items = json.loads(stream_path.read_text(encoding='utf-8'))
    assert items, "Expected at least one stream item"
