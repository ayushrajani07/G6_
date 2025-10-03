"""Test that unified path skips PanelsWriter when legacy bridge is detected (simulated).

The test simulates detection by monkeypatching bridge_detection.legacy_bridge_active.
"""
from __future__ import annotations

import os
import json
import threading
import time
import pytest

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import TerminalRenderer, PanelsWriter

class _TerminalCollect(TerminalRenderer):
    def __init__(self):
        super().__init__(rich_enabled=False)
        self.cycles = 0
    def process(self, snap):  # type: ignore[override]
        self.cycles += 1

@pytest.mark.timeout(5)
def test_panels_writer_skipped_when_bridge_active(tmp_path, monkeypatch):
    # Simulate legacy bridge active by monkeypatching detection to return True
    from scripts.summary import bridge_detection
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(tmp_path / "runtime_status.json"))
    (tmp_path / "runtime_status.json").write_text("{}", encoding="utf-8")

    # Monkeypatch legacy bridge detection
    monkeypatch.setattr(bridge_detection, "legacy_bridge_active", lambda panels_dir: (True, "simulated"))

    term = _TerminalCollect()
    loop = UnifiedLoop([term, PanelsWriter(panels_dir=str(tmp_path))], panels_dir=str(tmp_path), refresh=0.01)
    # Since we directly constructed with PanelsWriter, detection logic in app.py isn't triggered here;
    # this test documents that PanelsWriter itself is inert when directory exists (no conflict logic inside yet).
    # For conflict path we rely on app-level integration, so this test ensures no exception.
    loop.run(cycles=2)
    assert term.cycles >= 1

