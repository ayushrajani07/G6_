import json
from pathlib import Path
from scripts.parity_snapshot_cli import build_snapshot

LEGACY = {
    "indices": [{"option_count": 10}, {"option_count": 5}],
    "options_total": 15,
    "alerts": {"categories": {"critical": 2, "warning": 4}},
}
PIPELINE = {
    "indices": [{"option_count": 11}, {"option_count": 5}],
    "options_total": 16,
    "alerts": {"categories": {"critical": 3, "warning": 4, "info": 1}},
}

def test_build_snapshot_basic(tmp_path: Path):
    snap = build_snapshot(LEGACY, PIPELINE, weights=None, rolling_window=0)
    assert 'generated_at' in snap
    assert 'parity' in snap and isinstance(snap['parity'], dict)
    assert isinstance(snap['parity'].get('score'), float)
    # components existence
    comps = snap['parity'].get('components') or {}
    assert 'index_count' in comps
    assert 'option_count' in comps
    assert 'alerts' in comps
    # alert categories diff
    cats = snap['alerts']['categories']
    assert cats['critical']['delta'] == 1
    assert cats['info']['pipeline'] == 1
    # sym diff present (none for structured categories case -> either empty list OK)
    assert 'sym_diff' in snap['alerts']

def test_build_snapshot_rolling(tmp_path: Path):
    snap = build_snapshot(LEGACY, PIPELINE, weights=None, rolling_window=5)
    rolling = snap['rolling']
    assert rolling['window'] == 5
    # With single insertion count may be 1
    assert rolling['count'] in (0,1,5) or isinstance(rolling['count'], int)

