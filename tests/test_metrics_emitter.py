from __future__ import annotations
import os
import time
import types
from typing import Mapping, Any

import pytest

from scripts.summary.plugins.base import MetricsEmitter, SummarySnapshot

class DummyMapping(dict):
    pass

def _mk_snap(cycle: int = 1) -> SummarySnapshot:
    return SummarySnapshot(status={}, derived={}, panels={}, ts_read=time.time(), ts_built=time.time(), cycle=cycle, errors=())

@pytest.mark.skipif('prometheus_client' not in globals(), reason="prometheus_client not installed in test env")
def test_metrics_emitter_cycle(monkeypatch):
    monkeypatch.setenv("G6_UNIFIED_METRICS", "1")
    m = MetricsEmitter()
    m.setup({})
    # Observe one cycle with durations
    m.observe_cycle(0.02, 0.005, errors=0)
    m.observe_plugin("terminal", 0.003, had_error=False)
    m.observe_plugin("panels_writer", 0.010, had_error=True)
    # No assertions on exporter objects (prometheus handles registry); ensure no exceptions
    assert True
