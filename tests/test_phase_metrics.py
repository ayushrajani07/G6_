import types
import time
import logging
from src.collectors.cycle_context import CycleContext

class DummyMetrics:
    def __init__(self):
        # store observations in simple dicts/lists for assertions
        self.phase_duration_seconds = types.SimpleNamespace(
            labels=lambda phase: types.SimpleNamespace(observe=lambda v: self._record_duration(phase, v))
        )
        self.phase_failures_total = types.SimpleNamespace(
            labels=lambda phase: types.SimpleNamespace(inc=lambda: self._record_failure(phase))
        )
        self.collection_cycle_in_progress = types.SimpleNamespace(set=lambda v: None)
        self._durations = {}
        self._failures = {}
    def _record_duration(self, phase, v):
        self._durations.setdefault(phase, []).append(v)
    def _record_failure(self, phase):
        self._failures[phase] = self._failures.get(phase, 0) + 1


def test_phase_duration_and_failure_tracking():
    metrics = DummyMetrics()
    ctx = CycleContext(index_params={}, providers=None, csv_sink=None, influx_sink=None, metrics=metrics, start_wall=time.time())

    # Successful phase
    with ctx.time_phase('alpha'):
        time.sleep(0.01)  # small sleep to guarantee measurable duration

    # Failing phase
    try:
        with ctx.time_phase('beta'):
            raise ValueError('boom')
    except ValueError:
        pass

    # Another successful phase
    with ctx.time_phase('gamma'):
        pass

    # Emit metrics
    ctx.emit_phase_metrics()

    # Assertions: durations recorded for all three phases
    assert 'alpha' in metrics._durations, 'alpha phase missing duration'
    assert 'beta' in metrics._durations, 'beta phase missing duration despite failure'
    assert 'gamma' in metrics._durations, 'gamma phase missing duration'
    # Ensure at least some positive timing
    assert metrics._durations['alpha'][0] > 0
    assert metrics._durations['beta'][0] >= 0  # failure still records timing

    # Failure counter incremented exactly once for beta
    assert metrics._failures.get('beta', 0) == 1, f"Expected 1 failure for beta, got {metrics._failures.get('beta')}"
    assert metrics._failures.get('alpha', 0) == 0
    assert metrics._failures.get('gamma', 0) == 0


def test_consolidated_log_emission(caplog):
    metrics = DummyMetrics()
    ctx = CycleContext(index_params={}, providers=None, csv_sink=None, influx_sink=None, metrics=metrics, start_wall=time.time())

    with ctx.time_phase('one'):
        time.sleep(0.005)
    with ctx.time_phase('two'):
        time.sleep(0.003)

    with caplog.at_level(logging.INFO):
        ctx.emit_consolidated_log()
    # Find consolidated log line
    found = any('PHASE_TIMING' in rec.message for rec in caplog.records)
    assert found, 'Consolidated phase timing log line not emitted (expected PHASE_TIMING prefix)'
