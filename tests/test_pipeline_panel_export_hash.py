from __future__ import annotations
import os, json, tempfile, shutil, time
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_panel_export_hash_stable(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HASH','1')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def a(_c,s): return s
    execute_phases(Ctx(), st, [a])
    path = os.path.join(tmp,'pipeline_errors_summary.json')
    data1 = json.load(open(path,'r',encoding='utf-8'))
    h1 = data1.get('content_hash')
    assert h1 and len(h1)==16
    # second identical run should yield same hash (content unchanged aside from exported_at which is excluded)
    time.sleep(0.05)
    execute_phases(Ctx(), st, [a])
    data2 = json.load(open(path,'r',encoding='utf-8'))
    h2 = data2.get('content_hash')
    assert h2 == h1
    shutil.rmtree(tmp)

def test_panel_history_index_hashes(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HASH','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','3')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def a(_c,s): return s
    for _ in range(2):
        execute_phases(Ctx(), st, [a])
        time.sleep(0.02)
    idx_path = os.path.join(tmp,'pipeline_errors_history_index.json')
    assert os.path.exists(idx_path)
    idx = json.load(open(idx_path,'r',encoding='utf-8'))
    files = idx['files']
    assert isinstance(files, list) and files
    # files list should now hold objects with hash & ts
    sample = files[0]
    assert 'file' in sample and 'hash' in sample
    assert sample.get('hash') and len(sample['hash'])==16
    shutil.rmtree(tmp)
