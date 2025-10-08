import warnings
from src.broker.kite_provider import kite_provider_factory, DEPRECATION_MSG_IMPLICIT_ENV_HELPER, DEPRECATION_MSG_DIRECT_CREDENTIALS
from src.providers.factory import create_provider


def test_factory_emits_warning_with_implicit_env(monkeypatch):
    monkeypatch.setenv('KITE_API_KEY', 'k_env')
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 't_env')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        p = create_provider('kite', {})
        assert p is not None
        msgs = [str(x.message) for x in w if isinstance(x.message, DeprecationWarning)]
        assert any('Implicit env credential construction' in m or 'implicit env credential construction' in m.lower() for m in msgs)


def test_kite_provider_factory_no_warning_with_overrides(monkeypatch):
    monkeypatch.setenv('KITE_API_KEY', 'k_env2')
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 't_env2')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('error', DeprecationWarning)
        # Should not raise
        p = kite_provider_factory(api_key='override_key', access_token='override_token')
        assert p is not None
        # No deprecation warnings captured
        assert not any(isinstance(x.message, DeprecationWarning) for x in w)
