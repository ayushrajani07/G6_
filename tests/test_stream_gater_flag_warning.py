from __future__ import annotations

import logging, os
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, OutputPlugin, SummarySnapshot
import json
import time

class StopAfter(OutputPlugin):
    name = "stop_after"
    def __init__(self, cycles: int = 2):
        self._cycles = cycles
        self._seen = 0
    def setup(self, context):  # pragma: no cover - no-op
        pass
    def process(self, snap: SummarySnapshot):  # pragma: no cover - simple control
        self._seen += 1
        if self._seen >= self._cycles:
            raise KeyboardInterrupt()
    def teardown(self):  # pragma: no cover - no-op
        pass


def _write_status(path, cycle=1, minute="2025-10-05T10:00:00Z"):
    status = {"loop": {"cycle": cycle, "last_run": minute}, "indices_detail": {}, "timestamp": minute}
    path.write_text(json.dumps(status), encoding="utf-8")


def test_retired_flag_warning_emitted_once(tmp_path, caplog, monkeypatch):
    # Set a retired flag
    monkeypatch.setenv("G6_UNIFIED_STREAM_GATER", "1")
    status_file = tmp_path / "runtime_status.json"
    _write_status(status_file, 1)
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))

    panels_dir = tmp_path / "panels"; panels_dir.mkdir()

    caplog.set_level(logging.WARNING)
    loop = UnifiedLoop([PanelsWriter(str(panels_dir)), StopAfter(cycles=3)], panels_dir=str(panels_dir), refresh=0.01)
    try:
        loop.run(cycles=3)
    except KeyboardInterrupt:
        pass

    warnings = [r for r in caplog.records if "Flags G6_UNIFIED_STREAM_GATER / G6_DISABLE_UNIFIED_GATER" in r.getMessage()]
    assert len(warnings) == 1, f"Expected single retired flag warning, got {len(warnings)}"

    # Subsequent run should not emit again
    try:
        loop.run(cycles=1)
    except KeyboardInterrupt:
        pass
    warnings2 = [r for r in caplog.records if "Flags G6_UNIFIED_STREAM_GATER / G6_DISABLE_UNIFIED_GATER" in r.getMessage()]
    assert len(warnings2) == 1, "Warning re-emitted on subsequent run"
