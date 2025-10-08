import os, json, pytest
from src.orchestrator.panel_diffs import emit_panel_artifacts
from src.metrics import get_metrics  # facade import

@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen')
def test_panel_diff_truncation_and_counters(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_PANEL_DIFFS', '1')
    monkeypatch.setenv('G6_PANEL_DIFF_FULL_INTERVAL', '100')  # avoid periodic full interfering
    monkeypatch.setenv('G6_PANEL_DIFF_MAX_KEYS', '1')  # force truncation quickly
    status_path = tmp_path / 'runtime_status.json'
    # initial full
    emit_panel_artifacts({'a': 1, 'b': 2}, status_path=str(status_path))
    # next snapshot with multiple changes so only first captured
    emit_panel_artifacts({'a': 2, 'b': 3, 'c': 4}, status_path=str(status_path))
    # find diff file
    diff_file = next(p for p in tmp_path.iterdir() if p.name.endswith('.1.diff.json'))
    diff = json.loads(diff_file.read_text())
    assert diff.get('_truncated') is True
    assert 'max_keys' in diff.get('truncated_reasons', [])
    # Only one unit captured (either changed or added) due to cap
    units = 0
    units += len(diff.get('added', {}))
    units += len(diff.get('changed', {}))
    units += len(diff.get('removed', []))
    units += len(diff.get('nested', {})) if 'nested' in diff else 0
    assert units == 1
    m = get_metrics()
    # counters exist (best-effort presence check)
    assert hasattr(m, 'panel_diff_truncated')
    # can't easily read counter value portably without exposing registry scraping util; presence is enough here.
    assert hasattr(m, 'panel_diff_bytes_last')
    assert hasattr(m, 'panel_diff_bytes_total')
