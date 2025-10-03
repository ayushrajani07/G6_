import time, types
from src.collectors.cycle_context import CycleContext

def test_phase_durations_emitted_positive():
    class Metrics:
        def __init__(self):
            self._observed = {}
            self.phase_duration_seconds = types.SimpleNamespace(
                labels=lambda phase: types.SimpleNamespace(observe=lambda v: self._record(phase, v))
            )
            self.phase_failures_total = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(inc=lambda: None))
            self.collection_cycle_in_progress = types.SimpleNamespace(set=lambda v: None)
        def _record(self, phase, v):
            self._observed.setdefault(phase, []).append(v)
    m = Metrics()
    ctx = CycleContext(index_params={}, providers=None, csv_sink=None, influx_sink=None, metrics=m, start_wall=time.time())
    with ctx.time_phase('fetch'):
        time.sleep(0.002)
    with ctx.time_phase('enrich'):
        time.sleep(0.001)
    ctx.emit_phase_metrics()
    assert any(v > 0 for v in m._observed.get('fetch', [])), 'Fetch phase duration not recorded as >0'
    assert any(v >= 0 for v in m._observed.get('enrich', [])), 'Enrich phase duration missing'
