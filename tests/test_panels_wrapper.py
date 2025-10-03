from __future__ import annotations
import os, json, time

from src.panels.version import PANEL_SCHEMA_VERSION

def test_panels_schema_wrapper(monkeypatch, tmp_path):
    base = tmp_path / 'panels'
    monkeypatch.setenv('G6_OUTPUT_SINKS','panels')
    monkeypatch.setenv('G6_PANELS_DIR', str(base))
    monkeypatch.setenv('G6_PANELS_SCHEMA_WRAPPER','1')
    from src.utils.output import get_output
    router = get_output(reset=True)
    router.panel_update('wrapper_demo', {'value': 123})
    # allow file write
    deadline = time.time() + 1.0
    path = base / 'wrapper_demo.json'
    while time.time()<deadline and not path.exists():
        time.sleep(0.05)
    assert path.exists(), 'panel file not written'
    obj = json.loads(path.read_text('utf-8'))
    # Wrapper expectations
    assert 'version' in obj and obj['version'] == PANEL_SCHEMA_VERSION
    # New explicit schema_version field
    assert 'schema_version' in obj and obj['schema_version'] == PANEL_SCHEMA_VERSION
    assert 'emitted_at' in obj
    assert isinstance(obj.get('panel'), dict)
    inner = obj['panel']
    assert inner.get('panel') == 'wrapper_demo'
    assert 'updated_at' in inner and 'data' in inner
    assert inner['data'].get('value') == 123
