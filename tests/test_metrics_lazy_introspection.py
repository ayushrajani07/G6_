#!/usr/bin/env python3
import importlib, sys

def fresh_metrics(monkeypatch, **env):
    for k,v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    # Force reload of implementation module
    if 'src.metrics.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics.metrics'])
    if 'src.metrics' in sys.modules:
        importlib.reload(sys.modules['src.metrics'])
    return importlib.import_module('src.metrics')


def test_lazy_default_builds_on_access(monkeypatch):
    m = fresh_metrics(monkeypatch, G6_METRICS_EAGER_INTROSPECTION=None, G6_METRICS_INTROSPECTION_DUMP=None)
    reg = m.get_metrics_singleton()
    # Should be sentinel None prior to accessor
    assert getattr(reg, '_metrics_introspection', None) is None
    data = reg.get_metrics_introspection()  # triggers lazy build via introspection module
    assert isinstance(data, list)
    assert getattr(reg, '_metrics_introspection', None) is not None


def test_eager_flag_builds_immediately(monkeypatch):
    m = fresh_metrics(monkeypatch, G6_METRICS_EAGER_INTROSPECTION='1')
    reg = m.get_metrics_singleton()
    inv = getattr(reg, '_metrics_introspection', None)
    assert inv is not None  # built eagerly


def test_dump_flag_forces_eager(monkeypatch):
    m = fresh_metrics(monkeypatch, G6_METRICS_INTROSPECTION_DUMP='stdout')
    reg = m.get_metrics_singleton()
    assert getattr(reg, '_metrics_introspection', None) is not None
