from __future__ import annotations
import os
from src.metrics.testing import force_new_metrics_registry

# We simulate the stale tracking mutation by manually incrementing the registry attribute
# to emulate what the collection loop would do across cycles.

def test_stale_counter_isolated_between_registries():
    os.environ['G6_STALE_WRITE_MODE'] = 'mark'
    r1 = force_new_metrics_registry(enable_resource_sampler=False)
    # Simulate 3 stale cycles
    for _ in range(3):
        cur = getattr(r1, '_consec_stale_cycles', 0)
        setattr(r1, '_consec_stale_cycles', cur + 1)
    assert getattr(r1, '_consec_stale_cycles', None) == 3
    # New registry should start fresh (autouse fixture would normally create this per test)
    r2 = force_new_metrics_registry(enable_resource_sampler=False)
    assert getattr(r2, '_consec_stale_cycles', 0) == 0, "Stale counter leaked across registries"
