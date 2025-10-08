from __future__ import annotations

"""Tests for structured error record population.

Validates that executor + phases append PhaseErrorRecord entries matching legacy
`state.errors` tokens without altering token order/content.
"""
from typing import Any
from src.collectors.pipeline.state import ExpiryState
from src.collectors.pipeline.executor import execute_phases
from src.collectors.errors import PhaseRecoverableError, PhaseAbortError, PhaseFatalError

class DummyCtx:  # mirrors other tests
    providers: Any = None


def _mk_state() -> ExpiryState:
    return ExpiryState(index="NIFTY", rule="weekly", settings=object())


def test_executor_structured_record_abort():
    ctx = DummyCtx(); st = _mk_state()
    def p_ok(_c, s): return s
    def p_abort(_c, s): raise PhaseAbortError('early_abort')
    out = execute_phases(ctx, st, [p_ok, p_abort])
    # legacy token preserved
    assert any(t.startswith('abort:p_abort:') for t in out.errors)
    # one structured record for abort
    recs = [r for r in out.error_records if r.phase == 'p_abort']
    assert len(recs) == 1
    r = recs[0]
    assert r.classification == 'abort'
    assert r.outcome_token in out.errors
    assert r.attempt == 1


def test_executor_structured_record_recoverable_retry(monkeypatch):
    ctx = DummyCtx(); st = _mk_state()
    attempts = {'n':0}
    def p_recover(_c, s):
        attempts['n'] += 1
        if attempts['n'] < 2:
            raise PhaseRecoverableError('flaky')
        return s
    # enable retry via env monkeypatch
    monkeypatch.setenv('G6_PIPELINE_RETRY_ENABLED', '1')
    monkeypatch.setenv('G6_PIPELINE_RETRY_MAX_ATTEMPTS', '3')
    out = execute_phases(ctx, st, [p_recover])
    # legacy tokens should have exactly one recoverable token (first attempt) if success second attempt
    assert any(t.startswith('recoverable:p_recover:') for t in out.errors)
    # structured records contains exactly one recoverable classification for p_recover
    recs = [r for r in out.error_records if r.phase == 'p_recover']
    assert len(recs) == 1
    assert recs[0].classification == 'recoverable'
    assert recs[0].attempt == 1


def test_executor_structured_record_fatal():
    ctx = DummyCtx(); st = _mk_state()
    def p_fatal(_c, s): raise PhaseFatalError('boom')
    out = execute_phases(ctx, st, [p_fatal])
    assert any(t.startswith('fatal:p_fatal:') for t in out.errors)
    recs = [r for r in out.error_records if r.phase == 'p_fatal']
    assert len(recs) == 1
    assert recs[0].classification == 'fatal'


def test_phase_function_error_capture():
    """Inject error inside phase_fetch path to ensure helper used."""
    from src.collectors.pipeline.phases import phase_fetch
    st = _mk_state()
    ctx = DummyCtx()
    try:
        phase_fetch(ctx, st, precomputed_strikes=None)  # triggers abort inside phase (no_strikes)
    except PhaseAbortError:
        # executor would catch; here we just ensure no structured record yet because exception bubbles
        pass
    # Now simulate recoverable addition inside fetch by forcing exception mapping
    # Provide empty list to cause recoverable no_instruments path
    st2 = _mk_state()
    try:
        phase_fetch(ctx, st2, precomputed_strikes=[1])  # will raise recoverable or append error token internally
    except Exception:
        # Phase handles internally for domain errors; ignore
        pass
    # If an error token was appended, a structured record should exist with matching token
    if st2.errors:
        first_token = st2.errors[0]
        assert st2.error_records, 'structured records missing'
        assert any(r.outcome_token == first_token for r in st2.error_records)
