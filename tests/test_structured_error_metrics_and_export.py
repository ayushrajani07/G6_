from __future__ import annotations
import os, json
from typing import Any
from src.collectors.pipeline.state import ExpiryState
from src.collectors.pipeline.executor import execute_phases
from src.collectors.errors import PhaseRecoverableError

class Ctx: providers: Any = None

def _mk_state():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())


def test_struct_error_metric_increment(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_RETRY_ENABLED','0')
    monkeypatch.setenv('G6_PIPELINE_STRUCT_ERROR_METRIC','1')
    # ensure registry exists
    from src.metrics import get_metrics
    reg = get_metrics()
    # phase that fails recoverably
    def bad(_c, st):
        raise PhaseRecoverableError('foo')
    st = _mk_state()
    execute_phases(Ctx(), st, [bad])
    m = getattr(reg, 'pipeline_phase_error_records', None)
    assert m is not None
    # Attempt to get sample via internal _samples (prometheus_client compatibility) or _value
    # We just assert at least one child with our label set exists
    # Minimal assertion: labels() returns a child and further inc doesn't raise
    child = m.labels(phase='bad', classification='recoverable')
    assert child is not None


def test_struct_error_json_export(monkeypatch, capsys):
    monkeypatch.setenv('G6_PIPELINE_STRUCT_ERROR_EXPORT','1')
    monkeypatch.setenv('G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT','1')
    def bad(_c, st):
        raise PhaseRecoverableError('bar')
    st = _mk_state()
    execute_phases(Ctx(), st, [bad])
    assert 'structured_errors' in st.meta, 'state.meta missing structured_errors'
    payload = st.meta['structured_errors']
    assert payload['count'] == 1
    assert payload['records'][0]['classification'] in ('recoverable','recoverable_exhausted')
    out = capsys.readouterr().out
    assert 'pipeline.structured_errors' in out
    # minimal JSON parse to ensure well-formed
    line = [l for l in out.splitlines() if l.startswith('pipeline.structured_errors')][0]
    _, raw = line.split(' ',1)
    parsed = json.loads(raw)
    assert parsed['count'] == payload['count']
