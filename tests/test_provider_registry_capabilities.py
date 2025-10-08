import importlib

def test_capabilities_baseline():
    reg = importlib.import_module('src.broker.provider_registry')
    # Kite auto-registered
    caps = reg.get_capabilities('kite')
    assert caps.get('quotes') is True
    assert reg.provider_supports('options', 'kite') is True
    assert reg.provider_supports('nonexistent_cap', 'kite') is False


def test_capabilities_custom_provider():
    reg = importlib.import_module('src.broker.provider_registry')
    class AltProv: ...
    reg.register_provider('altcaps', AltProv, capabilities={'quotes': False, 'instruments': True})
    caps = reg.get_capabilities('altcaps')
    assert caps.get('instruments') is True
    assert caps.get('quotes') is False
    assert reg.provider_supports('quotes', 'altcaps') is False
    inst = reg.get_provider('altcaps')
    assert isinstance(inst, AltProv)
