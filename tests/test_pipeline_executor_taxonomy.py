from __future__ import annotations

"""Tests for `execute_phases` taxonomy control flow.

Covers:
  - Abort: PhaseAbortError stops execution; later phases skipped.
  - Recoverable: PhaseRecoverableError stops execution; later phases skipped.
  - Fatal: PhaseFatalError stops execution; later phases skipped.
  - Unknown: Non-taxonomy exception classified as 'unknown' and stops.
  - OK path: All phases run when no exceptions raised.
"""

from typing import Any

from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.collectors.errors import (
    PhaseAbortError,
    PhaseRecoverableError,
    PhaseFatalError,
)


class DummyCtx:
    """Lightweight context stub; real executor only forwards it to phases."""
    providers: Any = None


def _mk_state() -> ExpiryState:
    return ExpiryState(index="NIFTY", rule="weekly", settings=object())


def test_executor_ok_sequence():
    ctx = DummyCtx()
    state = _mk_state()

    def phase_a(_ctx, st):
        st.meta['a'] = True
        return st

    def phase_b(_ctx, st):
        st.meta['b'] = True
        return st

    out = execute_phases(ctx, state, [phase_a, phase_b])
    assert out.meta.get('a') is True
    assert out.meta.get('b') is True
    assert out.errors == []


def test_executor_abort_stops():
    ctx = DummyCtx()
    state = _mk_state()

    def phase_ok(_ctx, st):
        st.meta['ok'] = True
        return st

    def phase_abort(_ctx, st):  # noqa: D401
        raise PhaseAbortError('early_abort')

    def phase_never(_ctx, st):  # should not execute
        st.meta['never'] = True
        return st

    out = execute_phases(ctx, state, [phase_ok, phase_abort, phase_never])
    assert out.meta.get('ok') is True
    assert 'never' not in out.meta
    # Error string prefix from executor: 'abort:phase_abort:'
    assert any(e.startswith('abort:phase_abort:') for e in out.errors), out.errors


def test_executor_recoverable_stops():
    ctx = DummyCtx()
    state = _mk_state()

    def phase_recoverable(_ctx, st):
        raise PhaseRecoverableError('transient')

    def phase_late(_ctx, st):  # should not run
        st.meta['late'] = True
        return st

    out = execute_phases(ctx, state, [phase_recoverable, phase_late])
    assert 'late' not in out.meta
    assert any(e.startswith('recoverable:phase_recoverable:') for e in out.errors), out.errors


def test_executor_fatal_stops():
    ctx = DummyCtx()
    state = _mk_state()

    def phase_fatal(_ctx, st):
        raise PhaseFatalError('boom')

    def phase_tail(_ctx, st):  # should not execute
        st.meta['tail'] = True
        return st

    out = execute_phases(ctx, state, [phase_fatal, phase_tail])
    assert 'tail' not in out.meta
    assert any(e.startswith('fatal:phase_fatal:') for e in out.errors), out.errors


def test_executor_unknown_exception():
    ctx = DummyCtx()
    state = _mk_state()

    def phase_unknown(_ctx, st):
        raise ValueError('some_unexpected')

    def phase_after(_ctx, st):  # should be skipped
        st.meta['after'] = True
        return st

    out = execute_phases(ctx, state, [phase_unknown, phase_after])
    # classified via classify_exception -> 'unknown'
    assert any(e.startswith('unknown:phase_unknown:') for e in out.errors), out.errors
    assert 'after' not in out.meta
