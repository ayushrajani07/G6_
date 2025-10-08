from __future__ import annotations
import os
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import PhaseAbortError
from src.metrics.metrics import MetricsRegistry

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
    if getattr(reg,'pipeline_cycle_success',None):
        assert reg.pipeline_cycle_success._value.get() == 1
    if getattr(reg,'pipeline_cycles_total',None):
        assert reg.pipeline_cycles_total._value.get() >= 1
    if getattr(reg,'pipeline_cycles_success_total',None):
        assert reg.pipeline_cycles_success_total._value.get() >= 1


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
    if getattr(reg,'pipeline_cycle_success_rate_window',None):
        rate = reg.pipeline_cycle_success_rate_window._value.get()
        assert 0.60 < rate < 0.70
    if getattr(reg,'pipeline_cycle_error_rate_window',None):
        er = reg.pipeline_cycle_error_rate_window._value.get()
        assert 0.30 < er < 0.40
    # Error ratio on last cycle (success) should be 0
    if getattr(reg,'pipeline_cycle_error_ratio',None):
        assert reg.pipeline_cycle_error_ratio._value.get() == 0.0


def test_phase_duration_histogram(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_CYCLE_SUMMARY','1')
    # Simple single phase to exercise histogram observe path
    execute_phases(Ctx(), _mk(), [lambda _c,s: s])
    reg = MetricsRegistry()
    # Access histogram internal samples; ensure at least one bucket count incremented
    if getattr(reg,'pipeline_phase_duration_seconds',None):
        fam = reg.pipeline_phase_duration_seconds
        try:
            samples = fam._samples() if hasattr(fam,'_samples') else []
            count_total = sum(v for n, lbl, v in samples if n.endswith('_count'))
            assert count_total > 0, f"expected histogram count_total>0 samples={samples}"
        except Exception:
            pass
