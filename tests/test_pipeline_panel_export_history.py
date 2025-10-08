from __future__ import annotations
import os, json, tempfile, shutil, time
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseRecoverableError

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_panel_history_export_creates_multiple(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','5')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def a(_c,s): return s
    # run several cycles to produce history
    for _ in range(3):
        execute_phases(Ctx(), st, [a])
        time.sleep(0.02)  # nudge timestamp changes; still allow collision gracefully
    # base file exists
    base = os.path.join(tmp,'pipeline_errors_summary.json')
    assert os.path.exists(base)
    # history files
    hist_files = [f for f in os.listdir(tmp) if f.startswith('pipeline_errors_summary_') and f.endswith('.json')]
    # Allow >=2 in case two cycles share same epoch second
    assert len(hist_files) >= 2
    # index file
    idx_path = os.path.join(tmp,'pipeline_errors_history_index.json')
    assert os.path.exists(idx_path)
    idx = json.load(open(idx_path,'r',encoding='utf-8'))
    assert 2 <= idx['count'] <= 3
    assert idx['limit'] == 5
    assert len(idx['files']) == idx['count']
    shutil.rmtree(tmp)

def test_panel_history_prunes(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY','1')
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','2')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)
    st = _mk()
    def bad(_c,s): raise PhaseRecoverableError('boom')
    for _ in range(4):
        try:
            execute_phases(Ctx(), st, [bad])
        except Exception:
            pass
        time.sleep(0.02)
    hist_files = [f for f in os.listdir(tmp) if f.startswith('pipeline_errors_summary_') and f.endswith('.json')]
    # limit should enforce 2 most recent
    assert len(hist_files) <= 2
    idx_path = os.path.join(tmp,'pipeline_errors_history_index.json')
    idx = json.load(open(idx_path,'r',encoding='utf-8'))
    assert idx['count'] <= 2
    assert idx['limit'] == 2
    # Ensure ordering newest first by exported_at timestamp embedded in filename
    def extract_ts(fn: str) -> int:
        core = fn[len('pipeline_errors_summary_'):-5]
        return int(core.split('_')[0])
    # idx['files'] may be list of filenames (no hash) or list of objects with 'file'
    raw_files = [ (f if isinstance(f,str) else f.get('file')) for f in idx['files'] ]
    extracted = [extract_ts(f) for f in raw_files if f]
    assert extracted == sorted(extracted, reverse=True)
    shutil.rmtree(tmp)
