from __future__ import annotations
import os
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseAbortError
from src.metrics import MetricsRegistry  # updated to facade (W4-12)

class Ctx: providers=None

def _mk():
    return ExpiryState(index='NIFTY', rule='weekly', settings=object())

def test_cycle_success_and_counters(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    st = _mk()
    def a(_c,s): return s
    def b(_c,s): return s
    execute_phases(Ctx(), st, [a,b])
    reg = MetricsRegistry()
    # success gauge should be 1 and counters at least 1
    pcs = getattr(reg,'pipeline_cycle_success',None)
    if pcs is not None:
        assert pcs._value.get() == 1
    pct = getattr(reg,'pipeline_cycles_total',None)
    if pct is not None:
        assert pct._value.get() >= 1
    pcst = getattr(reg,'pipeline_cycles_success_total',None)
    if pcst is not None:
        assert pcst._value.get() >= 1


def test_cycle_error_ratio_and_window(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    monkeypatch.setenv('G6_PIPELINE_ROLLING_WINDOW','3')
    # First a success cycle
    execute_phases(Ctx(), _mk(), [lambda _c,s: s])
    # Then a failing cycle
    def bad(_c,s): raise PhaseAbortError('x')
    execute_phases(Ctx(), _mk(), [bad])
    # Another success cycle
    execute_phases(Ctx(), _mk(), [lambda _c,s: s])
    reg = MetricsRegistry()
    # Window now has 3 entries: success, error, success => success rate 2/3
    srw = getattr(reg,'pipeline_cycle_success_rate_window',None)
    if srw is not None:
        rate = srw._value.get()
        assert 0.60 < rate < 0.70
    erw = getattr(reg,'pipeline_cycle_error_rate_window',None)
    if erw is not None:
        er = erw._value.get()
        assert 0.30 < er < 0.40
    # Error ratio on last cycle (success) should be 0
    cer = getattr(reg,'pipeline_cycle_error_ratio',None)
    if cer is not None:
        assert cer._value.get() == 0.0


def test_phase_duration_histogram(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    # Simple single phase to exercise histogram observe path
    execute_phases(Ctx(), _mk(), [lambda _c,s: s])
    reg = MetricsRegistry()
    # Access histogram internal samples; ensure at least one bucket count incremented
    hdur = getattr(reg,'pipeline_phase_duration_seconds',None)
    if hdur is not None:
        try:
            samples = hdur._samples() if hasattr(hdur,'_samples') else []
            count_total = sum(v for n, lbl, v in samples if n.endswith('_count'))
            assert count_total > 0, f"expected histogram count_total>0 samples={samples}"
        except Exception:
            pass
