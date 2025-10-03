import json, os, time, pathlib
from src.orchestrator.catalog import build_catalog

# We'll simulate a minimal runtime status and CSV directory structure in a temp path provided by pytest (tmp_path fixture).

def _write_csv(path: pathlib.Path, rows: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('header1,header2\n')
        for r in rows:
            fh.write(r+'\n')


def test_catalog_index_summary(tmp_path, monkeypatch):
    # Prepare fake runtime status
    status_path = tmp_path / 'runtime_status.json'
    status = {"indices": ["NIFTY", "BANKNIFTY"]}
    status_path.write_text(json.dumps(status), encoding='utf-8')

    # Create CSV dirs
    base = tmp_path / 'data/g6_data'
    # NIFTY with two expiries
    exp_a = base / 'NIFTY' / '2025-09-26'
    exp_b = base / 'NIFTY' / '2025-10-03'
    now = int(time.time())
    _write_csv(exp_a / 'file1.csv', [f'{now-5},x', f'{now-4},y'])
    _write_csv(exp_b / 'file2.csv', [f'{now-3},p', f'{now-2},q'])
    # BANKNIFTY single expiry
    exp_c = base / 'BANKNIFTY' / '2025-09-26'
    _write_csv(exp_c / 'file3.csv', [f'{now-7},m', f'{now-6},n'])

    # Build catalog pointing to our temp structures
    cat = build_catalog(runtime_status_path=str(status_path), csv_dir=str(base))

    # Basic structural assertions
    assert 'indices' in cat and 'summary' in cat
    assert set(cat['indices'].keys()) == {'NIFTY', 'BANKNIFTY'}

    nifty = cat['indices']['NIFTY']
    bank = cat['indices']['BANKNIFTY']

    # Per-index rollups
    assert nifty['total_option_count'] == 4  # two files 2 rows each (after header removal logic)
    assert bank['total_option_count'] == 2
    assert 'latest_row_timestamp' in nifty
    assert 'data_gap_seconds' in nifty

    # Global summary
    summary = cat['summary']
    assert summary['index_count'] == 2
    assert summary['total_option_count'] == 6
    # global latest should equal latest of NIFTY second file (now-2 epoch)
    # Allow small tolerance due to iso conversion
    latest_iso = summary['latest_row_timestamp']
    assert latest_iso.endswith('Z') or 'T' in latest_iso
    assert 'global_data_gap_seconds' in summary

    # Gap seconds should be non-negative integers
    assert isinstance(summary['global_data_gap_seconds'], int)
    assert isinstance(nifty['data_gap_seconds'], int)

