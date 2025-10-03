import json, os, pathlib, time

from src.orchestrator.catalog import build_catalog
from src.events.event_log import dispatch, configure_from_env


def _write_csv(base: pathlib.Path, index: str, expiry: str, rows: list[str]):
    d = base / index / expiry
    d.mkdir(parents=True, exist_ok=True)
    p = d / 'chain.csv'
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write('ts,field1,field2\n')
        for r in rows:
            fh.write(r + '\n')
    return p


def test_catalog_enrichment_events_and_rows(tmp_path, monkeypatch):
    # Prepare runtime status file with one index
    status_path = tmp_path / 'runtime_status.json'
    status_path.write_text(json.dumps({'indices': ['NIFTY']}), encoding='utf-8')
    csv_root = tmp_path / 'data' / 'g6_data'
    _write_csv(csv_root, 'NIFTY', '2025-12-25', ['1700000000,1,2', '1700000300,3,4'])

    # Configure event log path & generate a few events
    events_path = tmp_path / 'events.log'
    monkeypatch.setenv('G6_EVENTS_LOG_PATH', str(events_path))
    # Ensure env-based configuration loaded (sampling etc.)
    configure_from_env()
    for i in range(3):
        dispatch('test_evt', context={'i': i})
        time.sleep(0.01)

    monkeypatch.setenv('G6_EMIT_CATALOG_EVENTS', '1')
    cat = build_catalog(runtime_status_path=str(status_path), csv_dir=str(csv_root))
    assert cat['events_included'] is True
    assert 'recent_events' in cat and len(cat['recent_events']) >= 1
    assert 'last_event_seq' in cat
    idx = cat['indices']['NIFTY']['expiries']['2025-12-25']
    assert idx['option_count'] == 2
    assert idx['last_row_raw'].startswith('1700000300')
    assert idx['last_row_timestamp'].endswith('Z')


def test_catalog_enrichment_without_events(tmp_path, monkeypatch):
    status_path = tmp_path / 'runtime_status.json'
    status_path.write_text(json.dumps({'indices': ['NIFTY']}), encoding='utf-8')
    csv_root = tmp_path / 'data' / 'g6_data'
    _write_csv(csv_root, 'NIFTY', '2025-12-25', ['1700000000,1,2'])
    # Ensure events not requested
    monkeypatch.delenv('G6_EMIT_CATALOG_EVENTS', raising=False)
    cat = build_catalog(runtime_status_path=str(status_path), csv_dir=str(csv_root))
    assert cat['events_included'] is False
    idx = cat['indices']['NIFTY']['expiries']['2025-12-25']
    assert idx['option_count'] == 1
    assert 'recent_events' not in cat
