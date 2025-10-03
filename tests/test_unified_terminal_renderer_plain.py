"""Test TerminalRenderer fallback plain mode (rich disabled)."""
from __future__ import annotations

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import TerminalRenderer


def test_terminal_renderer_plain_runs(tmp_path, monkeypatch):
    # Force status file
    status_path = tmp_path / "runtime_status.json"
    status_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_path))
    # rich_enabled=False triggers plain logging path (no Rich dependency)
    loop = UnifiedLoop([TerminalRenderer(rich_enabled=False)], panels_dir=str(tmp_path), refresh=0.01)
    loop.run(cycles=1)
