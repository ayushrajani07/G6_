import os, json, pytest
from src.metrics import MetricsRegistry, get_metrics, get_metrics_singleton  # facade import

@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen')
def test_dump_metrics_metadata_structure():
    # Use a fresh singleton to avoid prior test pollution
    os.environ.pop('G6_ENABLE_METRIC_GROUPS', None)
    os.environ.pop('G6_DISABLE_METRIC_GROUPS', None)
    # Force creation
    m = get_metrics()
    assert m is not None
    # Access via facade helper if present, else direct (backward compatible)
    try:
        from src.metrics import get_metrics_metadata  # type: ignore
        meta = get_metrics_metadata(m)  # type: ignore[misc]
    except Exception:
        meta = m.dump_metrics_metadata()  # legacy path
    assert isinstance(meta, dict)
    assert 'groups' in meta and isinstance(meta['groups'], dict)
    assert 'total_metrics' in meta and isinstance(meta['total_metrics'], int)
    # Must include state gauge flag
    assert meta.get('g6_metric_group_state') is True
    # Spot check a few known metrics are assigned to groups (non-empty mapping)
    sample_expect = ['panel_diff_writes', 'vol_surface_rows', 'risk_agg_rows', 'provider_failover', 'cycle_sla_breach']
    found = 0
    for attr, grp in meta['groups'].items():
        if attr in sample_expect:
            found += 1
    assert found >= 3  # tolerate gating/env differences but require majority


@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen')
def test_dump_metrics_metadata_respects_filters(monkeypatch):
    # Enable only a narrow subset of groups, verify others absent
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff,provider_failover')
    # Clear singleton so new env takes effect
    from src.metrics import setup_metrics_server  # facade import
    setup_metrics_server(reset=True)
    m = get_metrics_singleton()
    assert m is not None
    from src.metrics import get_metrics_metadata  # type: ignore
    meta2 = get_metrics_metadata()
    assert isinstance(meta2, dict)
    groups = meta2['groups']  # type: ignore[index]
    # Expected groups present
    assert 'panel_diff_writes' in groups
    assert 'provider_failover' in groups
    # A metric from an unenabled group should be absent
    assert 'risk_agg_rows' not in groups


@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen')
def test_dump_metrics_metadata_disable_filter(monkeypatch):
    # Disable a specific group
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS', 'panel_diff')
    from src.metrics import setup_metrics_server  # facade import
    setup_metrics_server(reset=True)
    m = get_metrics_singleton()
    from src.metrics import get_metrics_metadata  # type: ignore
    groups = get_metrics_metadata()['groups']  # type: ignore[index]
    assert 'panel_diff_writes' not in groups
    # Another group should still appear
    assert 'provider_failover' in groups or 'expiry_rewritten_total' in groups
