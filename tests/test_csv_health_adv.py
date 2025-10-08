import os
import datetime
from src.storage.csv_sink import CsvSink


def test_health_basic_no_advanced(tmp_path, monkeypatch):
    sink = CsvSink(base_dir=str(tmp_path))
    # Ensure advanced disabled
    monkeypatch.delenv('G6_HEALTH_ADVANCED', raising=False)
    h = sink.check_health()
    assert 'health_score' in h  # default present
    # When no writes have happened, idle detection isn't triggered w/o advanced
    assert not any(isinstance(c, dict) and c.get('component')=='idle_state' for c in h['components'])


def test_health_with_advanced_backlog_idle(tmp_path, monkeypatch):
    sink = CsvSink(base_dir=str(tmp_path))
    monkeypatch.setenv('G6_HEALTH_ADVANCED','1')
    # Simulate batching backlog
    sink._batch_flush_threshold = 10
    # Need > 5x threshold (i.e., >50 rows) to trigger backlog_excess heuristic
    rows = [[i] for i in range(60)]
    sink._batch_buffers = {('NIFTY','this_week','2024-01-01'):{'/dev/null':{'header':[], 'rows': rows}}}
    sink._batch_counts = {('NIFTY','this_week','2024-01-01'):len(rows)}
    # Simulate last write long ago for idle detection
    # Use timezone-aware UTC now (avoid deprecated utcnow in tests enforcement)
    old_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=3600)
    sink._agg_last_write = {'NIFTY': old_ts}
    monkeypatch.setenv('G6_HEALTH_IDLE_MAX_SEC','30')
    h = sink.check_health()
    # Expect advanced components appended
    comp_names = {c.get('component') for c in h['components'] if isinstance(c, dict)}
    assert 'batch_backlog' in comp_names
    assert 'idle_state' in comp_names
    # Issues should include backlog_excess and idle_stale
    issue_codes = {i.get('code') for i in h.get('issues', []) if isinstance(i, dict)}
    assert 'backlog_excess' in issue_codes
    assert 'idle_stale' in issue_codes
    hs = h.get('health_score')
    if isinstance(hs, (int, float)):
        assert hs < 100


def test_health_config_validation(tmp_path, monkeypatch):
    # Create fake config dir structure
    project_root = tmp_path / 'proj'
    (project_root / 'config').mkdir(parents=True)
    cfg_path = project_root / 'config' / 'g6_config.json'
    cfg_path.write_text('{"indices":{"NIFTY":{"expiries":["this_week"]}}}')
    # Base dir inside project root so relative resolution works (two levels up from src/storage)
    # Create fake src/storage path chain for relative resolution logic
    # We'll monkeypatch __file__ resolution by adjusting module attribute if needed; easier is to chdir
    os.chdir(project_root)
    sink = CsvSink(base_dir=str(tmp_path / 'data'))
    monkeypatch.setenv('G6_HEALTH_ADVANCED','1')
    h = sink.check_health()
    comp = [c for c in h['components'] if isinstance(c, dict) and c.get('component')=='config_validation']
    assert comp and comp[0].get('valid') is True


def test_health_disk_threshold_violation(tmp_path, monkeypatch):
    sink = CsvSink(base_dir=str(tmp_path))
    # Set extremely high min free MB to force failure
    monkeypatch.setenv('G6_HEALTH_MIN_FREE_MB', '999999999')
    h = sink.check_health()
    comp = [c for c in h['components'] if isinstance(c, dict) and c.get('component')=='disk_space']
    assert comp and comp[0].get('status')=='error'
    assert h['status']=='unhealthy'


def test_health_stale_locks_detection(tmp_path, monkeypatch):
    sink = CsvSink(base_dir=str(tmp_path))
    monkeypatch.setenv('G6_HEALTH_ADVANCED','1')
    monkeypatch.setenv('G6_HEALTH_LOCK_STALE_SEC','1')
    # Create stale lock file
    lock_dir = tmp_path / 'NIFTY'
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / 'test.lock'
    lock_file.write_text('pid')
    # Set mtime to 5 seconds ago
    import time as _t, os as _os
    old = _t.time() - 5
    _os.utime(str(lock_file), (old, old))
    h = sink.check_health()
    stale_comp = [c for c in h['components'] if isinstance(c, dict) and c.get('component')=='stale_locks']
    assert stale_comp and stale_comp[0].get('stale_count',0) >= 1


def test_health_invalid_config(monkeypatch, tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    monkeypatch.setenv('G6_HEALTH_ADVANCED','1')
    # Force config missing by monkeypatching os.path.exists for that specific path
    import os as _os, inspect
    from src.storage import csv_sink as _csv_mod
    cfg_path = _os.path.join(_os.path.abspath(_os.path.join(_os.path.dirname(_csv_mod.__file__), '../..')), 'config', 'g6_config.json')
    real_exists = _os.path.exists
    def fake_exists(p):
        if p == cfg_path:
            return False
        return real_exists(p)
    monkeypatch.setattr(_os, 'path', _os.path)
    monkeypatch.setattr(_os.path, 'exists', fake_exists)
    h = sink.check_health()
    cv = [c for c in h['components'] if isinstance(c, dict) and c.get('component')=='config_validation']
    # Config component may appear only when advanced enabled; ensure invalid result
    assert cv and cv[0].get('valid') is False
