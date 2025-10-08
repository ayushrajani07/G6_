from __future__ import annotations
import os, json, tempfile, shutil, time
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseRecoverableError

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='SENSEX', rule='weekly', settings=object())

def test_trends_accumulate_and_prune(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_TRENDS_ENABLED','1')
    monkeypatch.setenv('G6_PIPELINE_TRENDS_LIMIT','3')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)

    st = _mk()
    def ok(_c,s): return s
    def bad(_c,s): raise PhaseRecoverableError('E')

    # run 4 cycles with varying outcomes (3rd repeats)
    execute_phases(Ctx(), st, [ok])
    time.sleep(0.02)
    try:
        execute_phases(Ctx(), st, [bad])
    except Exception:
        pass
    time.sleep(0.02)
    execute_phases(Ctx(), st, [ok])
    time.sleep(0.02)
    execute_phases(Ctx(), st, [ok])

    trend_path = os.path.join(tmp,'pipeline_errors_trends.json')
    assert os.path.exists(trend_path)
    data = json.load(open(trend_path,'r',encoding='utf-8'))
    assert data['version']==1
    # pruned to limit 3
    assert len(data['records']) == 3
    agg = data['aggregate']
    assert agg['cycles'] == 3
    assert 0 <= agg['success_rate'] <= 1
    # ensure last record reflects last run
    last = data['records'][-1]
    assert last['phases_error'] == 0
    shutil.rmtree(tmp)
