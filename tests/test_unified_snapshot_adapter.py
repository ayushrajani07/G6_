"""Basic test for the unified loop snapshot adapter.

Note: This adapter now relies on the model-based snapshot implementation;
legacy `assemble_unified_snapshot` path has been tombstoned. This test ensures
the high-level loop still functions with minimal status input without raising
exceptions.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import TerminalRenderer


def test_unified_loop_builds_snapshot(tmp_path, monkeypatch):
    # Write minimal status file
    status_path = tmp_path / "runtime_status.json"
    status_path.write_text(json.dumps({
        "loop": {"cycle": 42, "last_duration": 0.01},
        "interval": 1.0,
        "indices_detail": {
            "NIFTY": {"status": "OK", "dq": {"score_percent": 95}},
        },
        "alerts": [
            {"time": "2025-09-30T12:00:00Z", "level": "INFO", "component": "Test", "message": "hello"}
        ],
        "memory": {"rss_mb": 123.4}
    }), encoding="utf-8")

    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_path))
    loop = UnifiedLoop([TerminalRenderer(rich_enabled=False)], panels_dir=str(tmp_path), refresh=0.01)
    # Run a single cycle
    loop.run(cycles=1)
    # No explicit assertions beyond absence of exceptions; future expansion will
    # expose snapshot hooks or plugin capture for validation.
