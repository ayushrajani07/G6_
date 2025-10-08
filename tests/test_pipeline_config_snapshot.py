from __future__ import annotations
import os, json, tempfile, shutil
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='BANKNIFTY', rule='weekly', settings=object())

def test_config_snapshot_basic(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_CONFIG_SNAPSHOT','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','0')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def a(_c,s): return s
    execute_phases(Ctx(), st, [a])
    path = os.path.join(tmp,'pipeline_config_snapshot.json')
    assert os.path.exists(path)
    data = json.load(open(path,'r',encoding='utf-8'))
    assert data['version']==1
    assert 'flags' in data
    assert data['flags']['G6_PIPELINE_RETRY_MAX_ATTEMPTS'] >= 1
    assert len(data.get('content_hash',''))==16
    # second run with no flag changes yields identical hash
    execute_phases(Ctx(), st, [a])
    data2 = json.load(open(path,'r',encoding='utf-8'))
    assert data2['content_hash']==data['content_hash']
    shutil.rmtree(tmp)
