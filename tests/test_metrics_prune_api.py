import os
from src.metrics import setup_metrics_server, prune_metrics_groups, get_metrics_singleton
from src.metrics import preview_prune_metrics_groups


def test_prune_removes_newly_disabled_group(monkeypatch):
    # Start with panel_diff + provider_failover enabled explicitly
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff,provider_failover')
    m, _ = setup_metrics_server(reset=True)
    groups_before = set(m.get_metric_groups().values())
    assert 'panel_diff' in groups_before
    assert 'provider_failover' in groups_before
    # Now disable panel_diff (was previously enabled) and prune
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS', 'panel_diff')
    summary = prune_metrics_groups(reload_filters=True)
    assert isinstance(summary, dict)
    # After pruning panel_diff grouped metrics should be gone while provider_failover remains
    groups_after = set(m.get_metric_groups().values())
    assert 'provider_failover' in groups_after
    assert 'panel_diff' not in groups_after
    # Summary should reflect at least one removal
    assert summary.get('removed', 0) >= 1


def test_prune_no_reload_uses_cached_filters(monkeypatch):
    # Enable only panel_diff
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff')
    setup_metrics_server(reset=True)
    m = get_metrics_singleton()
    assert m is not None
    assert 'panel_diff' in set(m.get_metric_groups().values())
    # Change env to disable without reload
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS', 'panel_diff')
    summary = prune_metrics_groups(reload_filters=False)
    # Without reload, cached filters still allow panel_diff, so no removal
    assert summary.get('removed', 0) == 0
    assert 'panel_diff' in set(m.get_metric_groups().values())
    # Now reload and prune again -> should remove
    summary2 = prune_metrics_groups(reload_filters=True)
    assert summary2.get('removed', 0) >= 1
    assert 'panel_diff' not in set(m.get_metric_groups().values())


def test_prune_dry_run_preview(monkeypatch):
    # Enable two groups; then plan to disable one but run dry-run first
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff,provider_failover')
    setup_metrics_server(reset=True)
    m = get_metrics_singleton()
    assert m is not None
    assert 'panel_diff' in set(m.get_metric_groups().values())
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS', 'panel_diff')
    preview = prune_metrics_groups(reload_filters=True, dry_run=True)  # type: ignore[arg-type]
    # Preview should indicate at least one removal but not actually remove
    assert preview.get('dry_run') is True
    assert preview.get('removed', 0) >= 1
    assert 'panel_diff' in set(m.get_metric_groups().values())  # still present
    # Actual prune now
    applied = prune_metrics_groups(reload_filters=False)
    assert applied.get('dry_run') is False
    assert 'panel_diff' not in set(m.get_metric_groups().values())


def test_preview_wrapper_equivalence(monkeypatch):
    # Enable two groups; then plan to disable one
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS', 'panel_diff,provider_failover')
    setup_metrics_server(reset=True)
    m = get_metrics_singleton()
    assert m is not None
    assert 'panel_diff' in set(m.get_metric_groups().values())
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS', 'panel_diff')
    # Preview via helper
    p1 = preview_prune_metrics_groups(reload_filters=True)
    # Preview via explicit call
    p2 = prune_metrics_groups(reload_filters=True, dry_run=True)  # type: ignore[arg-type]
    # Key fields should align
    for k in ['dry_run','before_count','removed','enabled_spec','disabled_count']:
        assert p1.get(k) == p2.get(k)
    # Both should indicate removal without mutation
    assert p1.get('dry_run') is True and p2.get('dry_run') is True
    assert 'panel_diff' in set(m.get_metric_groups().values())
