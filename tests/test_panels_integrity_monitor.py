import os, json, tempfile, shutil, time
from pathlib import Path
import pytest

from src.panels.validate import verify_manifest_hashes
from src.panels.integrity_monitor import run_integrity_check_once


def _write_panel(dir_path: Path, name: str, data: dict):
    # panels/<name>.json { metadata:..., data: <payload> }
    panel_file = dir_path / f"{name}.json"
    panel_file.write_text(json.dumps({"name": name, "data": data}, separators=(',',':')))
    return panel_file


def _build_manifest(dir_path: Path):
    # Construct manifest with correct hashes
    import hashlib, json as _json
    manifest = {"panels": [], "hashes": {}}
    for p in sorted(dir_path.glob('*.json')):
        if p.name == 'manifest.json':
            continue
        raw = _json.loads(p.read_text())
        payload = raw.get('data')
        canonical = _json.dumps(payload, sort_keys=True, separators=(',',':')).encode('utf-8')
        h = hashlib.sha256(canonical).hexdigest()
        manifest['panels'].append({"name": raw.get('name')})
        manifest['hashes'][p.name] = h
    (dir_path / 'manifest.json').write_text(json.dumps(manifest, separators=(',',':')))


@pytest.fixture()
def panels_dir(tmp_path):
    d = tmp_path / 'panels'
    d.mkdir()
    _write_panel(d, 'alpha', {"v":1})
    _write_panel(d, 'beta', {"v":2})
    _build_manifest(d)
    return d


def test_integrity_monitor_ok(panels_dir, monkeypatch):
    monkeypatch.setenv('G6_PANELS_DIR', str(panels_dir))
    result = run_integrity_check_once()
    assert result['_ok'] == 1
    assert result['_total_mismatches'] == 0


def test_integrity_monitor_detects_mismatch(panels_dir, monkeypatch):
    monkeypatch.setenv('G6_PANELS_DIR', str(panels_dir))
    # Corrupt one panel payload without updating manifest
    target = panels_dir / 'alpha.json'
    data = json.loads(target.read_text())
    data['data']['v'] = 42
    target.write_text(json.dumps(data, separators=(',',':')))
    result = run_integrity_check_once()
    assert result['_ok'] == 0
    assert result['_total_mismatches'] == 1


def test_integrity_monitor_strict_mode_logs_warning(panels_dir, monkeypatch, caplog):
    monkeypatch.setenv('G6_PANELS_DIR', str(panels_dir))
    monkeypatch.setenv('G6_PANELS_INTEGRITY_STRICT', '1')
    # Introduce mismatch
    target = panels_dir / 'beta.json'
    data = json.loads(target.read_text())
    data['data']['v'] = 999
    target.write_text(json.dumps(data, separators=(',',':')))
    with caplog.at_level('WARNING'):
        result = run_integrity_check_once()
    assert result['_ok'] == 0
    assert result['_total_mismatches'] == 1
    # Ensure a warning log entry referencing 'mismatches' appears
    assert any('mismatch' in rec.message.lower() or 'mismatches' in rec.message.lower() for rec in caplog.records)
