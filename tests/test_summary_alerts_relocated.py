import os, importlib, json, builtins, io
from pathlib import Path


def test_alerts_relocated_dedupe_and_persistence(monkeypatch, tmp_path):
    # Enable new aggregation path
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', '1')
    # Point data/panels to temp directory
    panels_dir = tmp_path / 'data' / 'panels'
    panels_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    # Prepare status with duplicate alerts + events
    status = {
        'alerts': [
            {'time': '2025-09-27T10:00:00Z', 'level': 'WARN', 'component': 'X', 'message': 'A'},
            {'time': '2025-09-27T10:00:00Z', 'level': 'WARN', 'component': 'X', 'message': 'A'},  # duplicate
        ],
        'events': [
            {'time': '2025-09-27T10:00:01Z', 'level': 'INFO', 'component': 'Y', 'message': 'B'},
        ],
        'indices_detail': {
            'NIFTY': {'dq': {'score_percent': 75.0}, 'status': 'OK'}  # triggers synthetic dq alert
        },
        'market': {'status': 'CLOSED'},  # triggers synthetic market alert
    }

    # Import builder fresh
    import scripts.summary.snapshot_builder as sb
    importlib.reload(sb)
    if hasattr(sb, '_reset_metrics_for_tests'):  # ensure clean metrics
        sb._reset_metrics_for_tests()
    # Build one snapshot (should write alerts_log.json once)
    snap = sb.build_frame_snapshot(status, panels_dir=str(panels_dir))
    assert snap.alerts.total >= 3  # dedup eliminated one duplicate but synthetic added

    log_path = panels_dir / 'alerts_log.json'
    assert log_path.exists(), 'alerts_log.json not written by builder'
    data = json.loads(log_path.read_text())
    assert 'alerts' in data and isinstance(data['alerts'], list)

    # Capture alert count for dedupe check
    alerts_logged = data['alerts']
    # Ensure no full duplicate set (component+message+level+time) appears twice
    seen = set()
    for a in alerts_logged:
        key = (a.get('time'), a.get('level'), a.get('component'), a.get('message'))
        assert key not in seen, 'Duplicate alert persisted'
        seen.add(key)


def test_alerts_panel_read_only_under_flag(monkeypatch, tmp_path):
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', '1')
    panels_dir = tmp_path / 'data' / 'panels'
    panels_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    # Pre-seed a log file to simulate builder having written it
    preseed = {
        'updated_at': '2025-09-27T10:00:00Z',
        'alerts': [
            {'time': '2025-09-27T10:00:00Z', 'level': 'INFO', 'component': 'Seed', 'message': 'Hello'}
        ]
    }
    (panels_dir / 'alerts_log.json').write_text(json.dumps(preseed))

    # Spy on open to ensure panel does not write when flag on (allow reads only)
    write_calls = []
    real_open = builtins.open

    def spy_open(path, mode='r', *a, **kw):
        if 'alerts_log.json' in str(path) and any(m in mode for m in ('w', 'a', '+')):
            write_calls.append(mode)
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, 'open', spy_open)

    import scripts.summary.panels.alerts as panel_mod
    importlib.reload(panel_mod)

    # Render panel
    panel_mod.alerts_panel({'loop': {'cycle': 1}}, compact=True)

    assert write_calls == [], 'Panel performed write under flag (should be read-only)'