import os
import importlib


def test_followups_multi_index_isolation(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.5')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','2')
    import src.adaptive.followups as f
    importlib.reload(f)
    # Feed index A two high events to trigger
    f.feed('IDX_A', interpolated_fraction=0.6)
    f.feed('IDX_A', interpolated_fraction=0.7)
    # Feed index B only one high event (should not trigger yet)
    f.feed('IDX_B', interpolated_fraction=0.65)
    # Drain alerts
    alerts = f.get_and_clear_alerts()
    kinds_by_index = {}
    for a in alerts:
        kinds_by_index.setdefault(a.get('index'), []).append(a.get('type'))
    assert 'IDX_A' in kinds_by_index, 'IDX_A missing alert'
    assert 'interpolation_high' in kinds_by_index['IDX_A']
    assert 'IDX_B' not in kinds_by_index, 'IDX_B incorrectly triggered guard'
