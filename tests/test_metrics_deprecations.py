#!/usr/bin/env python3
import importlib, sys, warnings


def reload_module(mod_name):
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def test_legacy_register_emits_warning(monkeypatch):
    monkeypatch.delenv('G6_SUPPRESS_LEGACY_WARNINGS', raising=False)
    # Force a fresh import of registration_compat
    reload_module('src.metrics.registration_compat')
    from src.metrics.registration_compat import legacy_register
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        legacy_register(lambda *a, **k: None, 'dummy_metric', 'doc')
        assert any(isinstance(x.message, DeprecationWarning) for x in w)


def test_legacy_register_suppressed(monkeypatch):
    monkeypatch.setenv('G6_SUPPRESS_LEGACY_WARNINGS','1')
    reload_module('src.metrics.registration_compat')
    from src.metrics.registration_compat import legacy_register
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        legacy_register(lambda *a, **k: None, 'dummy_metric2', 'doc')
        assert not any(isinstance(x.message, DeprecationWarning) for x in w)


def test_direct_import_metrics_warns(monkeypatch):
    monkeypatch.delenv('G6_SUPPRESS_LEGACY_WARNINGS', raising=False)
    # Remove both facade and implementation modules to ensure import path triggers warning
    for m in list(sys.modules):
        if m.startswith('src.metrics'):
            del sys.modules[m]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        importlib.import_module('src.metrics.metrics')  # noqa: F401
        assert any('Importing \'src.metrics.metrics\'' in str(x.message) for x in w)


def test_direct_import_suppressed(monkeypatch):
    monkeypatch.setenv('G6_SUPPRESS_LEGACY_WARNINGS','true')
    for m in list(sys.modules):
        if m.startswith('src.metrics'):
            del sys.modules[m]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        importlib.import_module('src.metrics.metrics')  # noqa: F401
        assert not any('Importing \'src.metrics.metrics\'' in str(x.message) for x in w)
