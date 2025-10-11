#!/usr/bin/env python3
import importlib, sys, warnings, pytest


def _purge_metrics_modules(*names: str) -> None:
    """Remove specific metrics modules from sys.modules to force a clean import.

    Targeted removal avoids nuking every 'src.metrics*' entry which is expensive
    and slows the deprecation tests. We delete only the modules whose re-exec
    is required to exercise the warning paths.
    """
    for n in names:
        if n in sys.modules:
            del sys.modules[n]
    # Also clear cached attribute on parent package if present and submodule removed
    pkg = sys.modules.get('src.metrics')
    if pkg is not None:
        for n in names:
            leaf = n.rsplit('.', 1)[-1]
            if hasattr(pkg, leaf):  # pragma: no branch - simple attr cleanup
                try:
                    delattr(pkg, leaf)
                except Exception:
                    pass


def reload_module(mod_name):
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def test_legacy_register_removed_import_error():
    """registration_compat module has been removed; importing it should fail."""
    with pytest.raises(ImportError):
        importlib.import_module('src.metrics.registration_compat')


def test_legacy_register_removed_import_error_suppressed_env_has_no_effect(monkeypatch):
    monkeypatch.setenv('G6_SUPPRESS_LEGACY_WARNINGS','1')
    with pytest.raises(ImportError):
        importlib.import_module('src.metrics.registration_compat')


def test_direct_import_metrics_warns(monkeypatch):
    monkeypatch.delenv('G6_SUPPRESS_LEGACY_WARNINGS', raising=False)
    # Targeted purge: only remove the core implementation module so import runs its body again
    _purge_metrics_modules('src.metrics.metrics')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        importlib.import_module('src.metrics.metrics')  # noqa: F401
        assert any('Importing \'src.metrics.metrics\'' in str(x.message) for x in w)


def test_direct_import_suppressed(monkeypatch):
    monkeypatch.setenv('G6_SUPPRESS_LEGACY_WARNINGS','true')
    _purge_metrics_modules('src.metrics.metrics')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        importlib.import_module('src.metrics.metrics')  # noqa: F401
        assert not any('Importing \'src.metrics.metrics\'' in str(x.message) for x in w)
