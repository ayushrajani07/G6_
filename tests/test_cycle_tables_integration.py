from __future__ import annotations
import os, tempfile, shutil
from typing import Any
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.helpers.cycle_tables import get_pipeline_summary, emit_cycle_tables

class Ctx: providers: Any=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_cycle_tables_integration_enabled(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_CYCLE_TABLES_PIPELINE_INTEGRATION','1')
    monkeypatch.setenv('G6_PANELS_DIR', tmp)  # ensure panels dir if side effects
    st = _mk()
    def a(_c,s): return s
    execute_phases(Ctx(), st, [a])
    summ = get_pipeline_summary()
    assert summ is not None
    assert summ['phases_total']==1
    payload = {}
    emit_cycle_tables(payload)
    assert 'pipeline_summary' in payload
    shutil.rmtree(tmp)

def test_cycle_tables_integration_disabled(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv('G6_CYCLE_TABLES_PIPELINE_INTEGRATION','0')
    st = _mk()
    def a(_c,s): return s
    execute_phases(Ctx(), st, [a])
    payload = {}
    emit_cycle_tables(payload)
    assert 'pipeline_summary' not in payload
    shutil.rmtree(tmp)
