from __future__ import annotations
import os, json, tempfile, shutil
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseRecoverableError

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_panel_export_ok(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def a(_c,s): return s
    execute_phases(Ctx(), st, [a])
    path = os.path.join(tmp,'pipeline_errors_summary.json')
    assert os.path.exists(path)
    data = json.load(open(path,'r',encoding='utf-8'))
    assert data['summary']['phases_total']==1
    assert data['error_count']==0
    shutil.rmtree(tmp)


def test_panel_export_with_error(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def bad(_c,s): raise PhaseRecoverableError('x')
    execute_phases(Ctx(), st, [bad])
    path = os.path.join(tmp,'pipeline_errors_summary.json')
    assert os.path.exists(path)
    data = json.load(open(path,'r',encoding='utf-8'))
    assert data['error_count']==1
    assert data['errors'][0]['classification'] in ('recoverable','recoverable_exhausted')
    shutil.rmtree(tmp)
