from __future__ import annotations
import os, json, tempfile, shutil
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseRecoverableError

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='FINNIFTY', rule='weekly', settings=object())

def test_redaction_single_pattern(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_REDACT_PATTERNS','secret')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def bad(_c,s): raise PhaseRecoverableError('secret token leaked')
    try:
        execute_phases(Ctx(), st, [bad])
    except Exception:
        pass
    # legacy token should still include raw message
    assert any('secret token leaked' in t for t in st.errors)
    data = json.load(open(os.path.join(tmp,'pipeline_errors_summary.json'),'r',encoding='utf-8'))
    # redacted message should replace pattern
    msgs = [e['message'] for e in data['errors']]
    assert any('*** token leaked' in m for m in msgs)
    shutil.rmtree(tmp)

def test_redaction_multiple_and_invalid(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_REDACT_PATTERNS','secret,((broken_regex,token')
    monkeypatch.setenv('G6_PIPELINE_REDACT_REPLACEMENT','[REDACT]')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def bad(_c,s): raise PhaseRecoverableError('secret token again')
    try:
        execute_phases(Ctx(), st, [bad])
    except Exception:
        pass
    data = json.load(open(os.path.join(tmp,'pipeline_errors_summary.json'),'r',encoding='utf-8'))
    msgs = [e['message'] for e in data['errors']]
    # Allow either single pattern redaction or both patterns redacted
    assert any(m.startswith('[REDACT]') and m.endswith('again') for m in msgs)
    shutil.rmtree(tmp)
