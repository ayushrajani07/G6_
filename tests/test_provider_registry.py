import os
import importlib


def test_registry_basic(monkeypatch):
    # Fresh import to ensure auto-registration executes
    mod = importlib.import_module('src.broker.provider_registry')
    # Kite should be registered
    providers = mod.list_providers()
    assert 'kite' in providers
    inst1 = mod.get_provider()
    inst2 = mod.get_provider()
    # Default path returns singleton
    assert inst1 is inst2
    # fresh instance different
    inst3 = mod.get_provider(fresh=True)
    assert inst3 is not inst1


def test_registry_env_selection(monkeypatch):
    mod = importlib.import_module('src.broker.provider_registry')
    # Register a dummy alt provider
    class Alt:
        def __init__(self):
            self.tag = 'alt'
    mod.register_provider('Alt', Alt, default=False)
    # Without env still default (kite)
    assert mod.get_active_name() in (None, 'kite')
    k = mod.get_provider()
    assert not hasattr(k, 'tag') or getattr(k, 'tag', None) != 'alt'
    # With env override
    monkeypatch.setenv('G6_PROVIDER','ALT')
    alt = mod.get_provider(name=None, fresh=True)
    assert getattr(alt, 'tag', None) == 'alt'
    assert mod.get_active_name() == 'alt'


def test_registry_unknown(monkeypatch):
    mod = importlib.import_module('src.broker.provider_registry')
    missing = mod.get_provider('nope__provider')
    assert missing is None
