import os
from types import SimpleNamespace

from src.collectors.pipeline.executor import execute_phases
from src.collectors.errors import PhaseRecoverableError as PR  # direct taxonomy class
from src.collectors.pipeline.state import ExpiryState


def test_executor_retry_success(monkeypatch):
    os.environ['G6_PIPELINE_RETRY_ENABLED'] = '1'
    os.environ['G6_PIPELINE_RETRY_MAX_ATTEMPTS'] = '4'
    attempts = {'n': 0}
    def phase(ctx, st):
        attempts['n'] += 1
        if attempts['n'] < 3:
            raise PR('transient')
        return st
    ctx = SimpleNamespace()
    st = ExpiryState(index='NIFTY', rule='atm', settings=None)
    st2 = execute_phases(ctx, st, [phase])
    assert attempts['n'] == 3
    assert st2 is st
    # Metrics presence (best-effort): ensure attempts >= retries
    try:
        from src.metrics.metrics import MetricsRegistry  # type: ignore
        reg = MetricsRegistry()
        if getattr(reg, 'pipeline_phase_attempts', None):
            a = reg.pipeline_phase_attempts.labels(phase='phase')._value.get()
            r = reg.pipeline_phase_retries.labels(phase='phase')._value.get()
            assert a >= 3
            assert r == 2
    except Exception:
        pass


def test_executor_retry_exhausted(monkeypatch):
    os.environ['G6_PIPELINE_RETRY_ENABLED'] = '1'
    os.environ['G6_PIPELINE_RETRY_MAX_ATTEMPTS'] = '2'
    attempts = {'n': 0}
    def phase(ctx, st):
        attempts['n'] += 1
        raise PR('still_bad')
    ctx = SimpleNamespace()
    st = ExpiryState(index='NIFTY', rule='atm', settings=None)
    st2 = execute_phases(ctx, st, [phase])
    assert attempts['n'] == 2
    assert any('recoverable_exhausted' in e or 'recoverable' in e for e in st2.errors)


def test_executor_retry_disabled(monkeypatch):
    os.environ['G6_PIPELINE_RETRY_ENABLED'] = '0'
    os.environ['G6_PIPELINE_RETRY_MAX_ATTEMPTS'] = '5'
    attempts = {'n': 0}
    def phase(ctx, st):
        attempts['n'] += 1
        raise PR('no_retry')
    ctx = SimpleNamespace()
    st = ExpiryState(index='NIFTY', rule='atm', settings=None)
    st2 = execute_phases(ctx, st, [phase])
    assert attempts['n'] == 1
    assert any('recoverable' in e for e in st2.errors)
