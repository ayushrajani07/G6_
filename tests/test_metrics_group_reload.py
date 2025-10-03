import os
from src.metrics import setup_metrics_server  # facade import

def test_reload_group_filters_allows_new_group(monkeypatch):
    # Start with enable list excluding 'storage'
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff')
    m, _ = setup_metrics_server(reset=True, enable_resource_sampler=False)
    groups_initial = set(m.get_metric_groups().values())
    assert 'storage' not in groups_initial  # storage skipped
    # Now allow storage and reload filters; create a new metric in storage group via maybe_register
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff,storage')
    m.reload_group_filters()
    # Register a synthetic test metric under storage group
    m._maybe_register('storage', 'test_storage_metric', type(m.panel_diff_writes), 'g6_test_storage_metric_total', 'Test metric for storage group reload')
    assert any(v == 'storage' for v in m.get_metric_groups().values())
