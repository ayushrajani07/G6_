import json, time, os
import pytest

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter, TerminalRenderer, MetricsEmitter
from scripts.summary import summary_metrics as sm


def _write_status(path: str, indices_val: int = 1, alerts: int = 0, dq_offset: int = 0):
    # Allow dq_offset to shift scores so hash changes deterministically when desired
    idx_detail = {f"IDX{i}": {"status": "OK", "dq": {"score_percent": 90 + i + dq_offset}, "age": 1.0} for i in range(indices_val)}
    alert_list = [{"time": "2025-10-04T00:00:00Z", "level": "INFO", "component": "Test", "message": "a"}] if alerts else []
    payload = {
        "loop": {"cycle": 0, "last_duration": 0.0, "target_interval": 0.01},
        "interval": 0.01,
        "indices_detail": idx_detail,
        "alerts": alert_list,
        "memory": {"rss_mb": 10.0},
        "performance": {"options_per_min": 1},
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def test_panels_writer_file_update_metrics(tmp_path, monkeypatch):
    sm.reset_for_tests()
    status_file = tmp_path / 'runtime_status.json'
    _write_status(str(status_file), indices_val=2, alerts=1, dq_offset=0)
    monkeypatch.setenv('G6_PANELS_DIR', str(tmp_path))
    monkeypatch.setenv('G6_SUMMARY_STATUS_FILE', str(status_file))

    loop = UnifiedLoop([
        PanelsWriter(panels_dir=str(tmp_path)),
    ], panels_dir=str(tmp_path), refresh=0.001)

    # First cycle: establish baseline, no file update increments expected
    loop.run(cycles=1)
    m = sm.snapshot()
    file_update_counters = [k for k in m['counter'].keys() if k[0] == 'g6_summary_panel_file_updates_total']
    assert file_update_counters == []

    # Modify status (change dq score -> should change indices_panel hash) and add alert
    _write_status(str(status_file), indices_val=2, alerts=2, dq_offset=5)  # shift scores to force hash change
    # Run two more cycles in one invocation to ensure loop internal cycle counter advances
    loop.run(cycles=2)
    m2 = sm.snapshot()
    file_update_counters2 = [k for k in m2['counter'].keys() if k[0] == 'g6_summary_panel_file_updates_total']
    # Expect at least one panel update (indices_panel or alerts)
    assert len(file_update_counters2) >= 1
    # Gauge should reflect number of updated panels last cycle
    assert 'g6_summary_panel_file_updates_last' in m2['gauge']
    assert m2['gauge']['g6_summary_panel_file_updates_last'] >= 1

    # Third cycle with no change -> no additional increments
    loop.run(cycles=1)
    m3 = sm.snapshot()
    file_update_counters3 = [k for k in m3['counter'].keys() if k[0] == 'g6_summary_panel_file_updates_total']
    # Counter set should be same (no new label keys); values unchanged
    assert file_update_counters3 == file_update_counters2

