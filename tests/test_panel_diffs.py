import json
from src.orchestrator.panel_diffs import emit_panel_artifacts


def test_panel_diff_emission(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_PANEL_DIFFS', '1')
    monkeypatch.setenv('G6_PANEL_DIFF_FULL_INTERVAL', '2')
    status_path = tmp_path / 'runtime_status.json'
    # Simulate first write (initial full only)
    s1 = {'a': 1}
    emit_panel_artifacts(s1, status_path=str(status_path))
    # Second snapshot (diff 1)
    s2 = {'a': 2, 'b': 5}
    emit_panel_artifacts(s2, status_path=str(status_path))
    # Third snapshot (diff 2 + periodic full at counter=2)
    s3 = {'a': 3, 'b': 5}
    emit_panel_artifacts(s3, status_path=str(status_path))
    # Fourth snapshot (diff 3, no full because counter=3 not divisible by 2)
    s4 = {'a': 4, 'b': 6}
    emit_panel_artifacts(s4, status_path=str(status_path))

    files = {f.name for f in tmp_path.iterdir()}
    assert 'runtime_status.full.json' in files  # initial
    assert 'runtime_status.1.diff.json' in files
    assert 'runtime_status.2.diff.json' in files
    assert 'runtime_status.2.full.json' in files  # periodic full at interval 2
    # third diff produced (counter=3 after fourth snapshot)
    assert 'runtime_status.3.diff.json' in files

    with open(tmp_path / 'runtime_status.1.diff.json', 'r', encoding='utf-8') as f:
        d1 = json.load(f)
    # First diff: a changed 1->2, b added
    assert 'a' in d1['changed'] and d1['changed']['a']['old'] == 1 and d1['changed']['a']['new'] == 2
    assert 'b' in d1['added'] and d1['added']['b'] == 5

    with open(tmp_path / 'runtime_status.2.diff.json', 'r', encoding='utf-8') as f:
        d2 = json.load(f)
    assert 'a' in d2['changed'] and d2['changed']['a']['old'] == 2 and d2['changed']['a']['new'] == 3

    with open(tmp_path / 'runtime_status.3.diff.json', 'r', encoding='utf-8') as f:
        d3 = json.load(f)
    assert 'a' in d3['changed'] and d3['changed']['a']['old'] == 3 and d3['changed']['a']['new'] == 4
    assert 'b' in d3['changed'] and d3['changed']['b']['old'] == 5 and d3['changed']['b']['new'] == 6
