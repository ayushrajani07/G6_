import json
import hashlib
from pathlib import Path

from src.panels.validate import verify_manifest_hashes


def test_manifest_hashes_integrity(tmp_path, monkeypatch):
    # Simulate a minimal panels directory with two panel files and a manifest including hashes
    panels_dir = tmp_path / 'panels'
    panels_dir.mkdir()

    panel_a = {"panel": "alpha", "updated_at": 1, "data": {"x": 1, "y": 2}}
    panel_b = {"panel": "beta", "updated_at": 1, "data": {"a": [1,2,3]}}

    def canon(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')

    a_hash = hashlib.sha256(canon(panel_a['data'])).hexdigest()
    b_hash = hashlib.sha256(canon(panel_b['data'])).hexdigest()

    (panels_dir / 'alpha_panel.json').write_text(json.dumps(panel_a), encoding='utf-8')
    (panels_dir / 'beta_panel.json').write_text(json.dumps(panel_b), encoding='utf-8')

    manifest = {
        "panels": ["alpha", "beta"],
        "hashes": {
            "alpha_panel.json": a_hash,
            "beta_panel.json": b_hash,
        }
    }
    (panels_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    issues = verify_manifest_hashes(panels_dir)
    assert issues == {}

    # Corrupt one panel file
    corrupted = panel_b.copy()
    corrupted['data'] = {"a": [1,2,3,4]}  # change data
    (panels_dir / 'beta_panel.json').write_text(json.dumps(corrupted), encoding='utf-8')

    issues_after = verify_manifest_hashes(panels_dir)
    assert issues_after == {"beta_panel.json": "mismatch"}


def test_manifest_hashes_missing_file(tmp_path):
    panels_dir = tmp_path / 'panels'
    panels_dir.mkdir()

    panel_a = {"panel": "alpha", "updated_at": 1, "data": {"x": 1}}

    def canon(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')

    a_hash = hashlib.sha256(canon(panel_a['data'])).hexdigest()

    (panels_dir / 'alpha_panel.json').write_text(json.dumps(panel_a), encoding='utf-8')

    manifest = {
        "panels": ["alpha", "beta"],  # beta missing
        "hashes": {
            "alpha_panel.json": a_hash,
            "beta_panel.json": a_hash,  # placeholder expecting mismatch due to missing file
        }
    }
    (panels_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    issues = verify_manifest_hashes(panels_dir)
    assert issues == {"beta_panel.json": "file_missing"}
