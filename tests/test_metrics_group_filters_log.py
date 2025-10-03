#!/usr/bin/env python3
import importlib, sys

def reload_metrics(monkeypatch, **env):
    for k,v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    if 'src.metrics.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics.metrics'])
    if 'src.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics'])
    return importlib.import_module('src.metrics')

def test_group_filters_structured_log_enable(monkeypatch, caplog):
    caplog.set_level('INFO')
    m = reload_metrics(monkeypatch, G6_ENABLE_METRIC_GROUPS='cache,analytics_risk_agg', G6_DISABLE_METRIC_GROUPS='sla_health')
    reg = m.get_metrics_singleton()
    assert reg is not None
    logs = "\n".join(r.message for r in caplog.records)
    # event name should appear as message per logging usage
    assert 'metrics.group_filters.loaded' in logs

def test_group_filters_structured_log_no_enable(monkeypatch, caplog):
    caplog.set_level('INFO')
    m = reload_metrics(monkeypatch, G6_ENABLE_METRIC_GROUPS=None, G6_DISABLE_METRIC_GROUPS='cache')
    reg = m.get_metrics_singleton()
    assert reg is not None
    logs = "\n".join(r.message for r in caplog.records)
    assert 'metrics.group_filters.loaded' in logs
