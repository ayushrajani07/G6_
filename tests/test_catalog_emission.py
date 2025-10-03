import json, os, tempfile, time, pathlib

from src.orchestrator.catalog import build_catalog


def _make_csv_tree(tmpdir, index, expiry, files):
    base = pathlib.Path(tmpdir) / index / expiry
    base.mkdir(parents=True, exist_ok=True)
    last_path = None
    for name in files:
        p = base / name
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('header1,header2\n1,2\n')
        last_path = p
        time.sleep(0.01)  # ensure mtime ordering on some filesystems
    return last_path


def test_build_catalog_basic(tmp_path):
    # Create a fake runtime status file
    status_path = tmp_path / 'runtime_status.json'
    with open(status_path, 'w', encoding='utf-8') as fh:
        json.dump({"indices": ["NIFTY"]}, fh)
    csv_root = tmp_path / 'data' / 'g6_data'
    last_file = _make_csv_tree(csv_root, 'NIFTY', '2025-12-25', ['a.csv', 'b.csv'])

    cat = build_catalog(runtime_status_path=str(status_path), csv_dir=str(csv_root))
    assert 'generated_at' in cat
    assert 'indices' in cat and 'NIFTY' in cat['indices']
    exp = cat['indices']['NIFTY']['expiries']
    assert '2025-12-25' in exp
    entry = exp['2025-12-25']
    assert entry['last_file'].endswith('b.csv')
    assert entry['last_file_mtime'].endswith('Z')


def test_build_catalog_missing_status(tmp_path):
    # No status file; should produce empty indices structure
    cat = build_catalog(runtime_status_path=str(tmp_path / 'nope.json'), csv_dir=str(tmp_path / 'csv'))
    assert cat['indices'] == {}
