import os
from src.metrics import setup_metrics_server  # facade import

def test_metric_group_state_gauge_presence(monkeypatch):
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff')  # restrict
    # Use reset to clear default registry and avoid duplicate time series
    m, _ = setup_metrics_server(reset=True, enable_resource_sampler=False)
    # metric_group_state gauge should exist
    g = getattr(m, 'metric_group_state', None)
    assert g is not None
    meta = m.dump_metrics_metadata()
    assert 'g6_metric_group_state' in meta
    # panel_diff should be 1, storage likely 0 (if referenced via filters)
    # We can't assert exact absent groups; ensure at least one label sample recorded
    # Prometheus client doesn't expose samples directly; rely on internal groups mapping
    assert any(v == 'panel_diff' for v in m.get_metric_groups().values())
