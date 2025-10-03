#!/usr/bin/env python3
import importlib, os, json, tempfile, sys


def fresh_metrics():
    # Force re-import & new singleton
    if 'src.metrics.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics.metrics'])
    if 'src.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics'])
    m = importlib.import_module('src.metrics')
    return m.get_metrics_singleton()


def test_cardinality_snapshot_and_compare(monkeypatch):
    snap_fd, snap_path = tempfile.mkstemp(prefix='card_snap_', suffix='.json')
    os.close(snap_fd)
    # 1. Generate snapshot
    monkeypatch.setenv('G6_CARDINALITY_SNAPSHOT', snap_path)
    monkeypatch.delenv('G6_CARDINALITY_BASELINE', raising=False)
    reg = fresh_metrics()
    assert reg is not None
    with open(snap_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['version'] == 1
    assert 'groups' in data and isinstance(data['groups'], dict)
    baseline_groups = data['groups']
    # Sanity: have at least one analytics group present
    assert any(g for g in baseline_groups if g.startswith('analytics_'))

    # 2. Modify snapshot to simulate baseline with smaller group (trigger growth)
    # Pick first group and truncate to 1 metric (or empty if already 1) to ensure growth detection
    for grp, attrs in baseline_groups.items():
        if isinstance(attrs, list) and len(attrs) > 1:
            baseline_groups[grp] = attrs[:1]
            break
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    # 3. Re-run with baseline compare (no snapshot) and tight threshold
    monkeypatch.delenv('G6_CARDINALITY_SNAPSHOT', raising=False)
    monkeypatch.setenv('G6_CARDINALITY_BASELINE', snap_path)
    monkeypatch.setenv('G6_CARDINALITY_ALLOW_GROWTH_PERCENT', '0')
    monkeypatch.setenv('G6_FORCE_NEW_REGISTRY', '1')
    reg2 = fresh_metrics()
    summary = getattr(reg2, '_cardinality_guard_summary', None)
    assert summary is not None
    offenders = summary.get('offenders', [])
    assert offenders, 'Expected at least one offender due to simulated growth'
    # Ensure offender growth percent > 0
    assert any(o.get('growth_percent', 0) > 0 for o in offenders)

def test_cardinality_guard_ok_path(monkeypatch):
    # Baseline = current (no offenders) scenario
    snap_fd, snap_path = tempfile.mkstemp(prefix='card_snap_', suffix='.json')
    os.close(snap_fd)
    # Create snapshot & baseline simultaneously
    monkeypatch.setenv('G6_CARDINALITY_SNAPSHOT', snap_path)
    reg = fresh_metrics()
    assert reg is not None
    # Use same file as baseline (identical mapping)
    monkeypatch.setenv('G6_CARDINALITY_BASELINE', snap_path)
    monkeypatch.delenv('G6_CARDINALITY_SNAPSHOT', raising=False)
    monkeypatch.setenv('G6_FORCE_NEW_REGISTRY', '1')
    reg2 = fresh_metrics()
    summary = getattr(reg2, '_cardinality_guard_summary', None)
    assert summary is not None
    assert not summary.get('offenders'), 'Should have zero offenders when baseline matches current'