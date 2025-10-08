import os
from src.provider.config import get_provider_config, update_provider_credentials

def test_snapshot_and_alias_resolution(monkeypatch):
    monkeypatch.setenv('KITE_APIKEY', 'A1')
    monkeypatch.delenv('KITE_API_KEY', raising=False)
    monkeypatch.setenv('KITE_ACCESSTOKEN', 'T1')
    monkeypatch.delenv('KITE_ACCESS_TOKEN', raising=False)
    cfg = get_provider_config(refresh=True)
    assert cfg.api_key == 'A1'
    assert cfg.access_token == 'T1'
    assert cfg.is_complete()


def test_update_credentials_produces_new_snapshot(monkeypatch):
    monkeypatch.setenv('KITE_API_KEY', 'X1')
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 'Y1')
    base = get_provider_config(refresh=True)
    assert base.api_key == 'X1'
    new_cfg = update_provider_credentials(api_key='X2')
    assert new_cfg.api_key == 'X2'
    assert new_cfg.access_token == 'Y1'
    # Ensure base reference not mutated (dataclass frozen)
    assert base.api_key == 'X1'


def test_incomplete_then_late_complete(monkeypatch):
    monkeypatch.delenv('KITE_API_KEY', raising=False)
    monkeypatch.delenv('KITE_APIKEY', raising=False)
    monkeypatch.delenv('KITE_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('KITE_ACCESSTOKEN', raising=False)
    cfg_empty = get_provider_config(refresh=True)
    assert not cfg_empty.is_complete()
    monkeypatch.setenv('KITE_API_KEY', 'LATE1')
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 'LATE2')
    cfg_late = get_provider_config(refresh=True)
    assert cfg_late.is_complete()
    assert cfg_late.api_key == 'LATE1'
    assert cfg_late.access_token == 'LATE2'
