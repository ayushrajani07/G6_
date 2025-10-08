from __future__ import annotations
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseAbortError, PhaseRecoverableError
import os

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_cycle_summary_ok(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    st = _mk()
    def a(_c,s): s.meta['a']=1; return s
    def b(_c,s): s.meta['b']=1; return s
    out = execute_phases(Ctx(), st, [a,b])
    summ = out.meta.get('pipeline_summary')
    assert summ, 'summary missing'
    assert summ['phases_total']==2
    assert summ['phases_ok']==2
    assert summ['phases_error']==0
    assert summ['phases_with_retries']==0
    assert not summ['aborted_early']


def test_cycle_summary_abort(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    st = _mk()
    def a(_c,s): return s
    def bad(_c,s): raise PhaseAbortError('stop')
    def never(_c,s): s.meta['n']=1; return s
    out = execute_phases(Ctx(), st, [a,bad,never])
    summ = out.meta.get('pipeline_summary')
    assert summ
    assert summ['phases_total']==2  # a ran, bad ran
    assert summ['phases_ok']==1
    assert summ['phases_error']==1
    assert summ['aborted_early']


def test_cycle_summary_retry(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    monkeypatch.setenv('G6_PIPELINE_RETRY_ENABLED','1')
    attempts={'n':0}
    st = _mk()
    def flaky(_c,s):
        attempts['n']+=1
        if attempts['n']<2:
            raise PhaseRecoverableError('t')
        return s
    out = execute_phases(Ctx(), st, [flaky])
    summ = out.meta.get('pipeline_summary')
    assert summ
    assert summ['phases_total']==1
    assert summ['phases_with_retries']==1
    assert summ['phases_error']==0  # final outcome ok
