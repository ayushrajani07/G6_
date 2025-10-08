import importlib

def test_basic_filters_volume_oi(monkeypatch):
    monkeypatch.setenv('G6_FILTER_MIN_VOLUME','50')
    monkeypatch.setenv('G6_FILTER_MIN_OI','25')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    enriched = {
        'A': {'volume': 10, 'oi': 100},   # filtered by volume
        'B': {'volume': 60, 'oi': 10},    # filtered by oi
        'C': {'volume': 60, 'oi': 30},    # passes
        'D': {'volume': 51, 'oi': 25},    # boundary passes
    }
    filtered = settings_mod.apply_basic_filters(enriched, settings)
    assert set(filtered.keys()) == {'C','D'}


def test_basic_filters_no_threshold(monkeypatch):
    # No thresholds set -> identity
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    enriched = {'X': {'volume': 1, 'oi': 1}, 'Y': {'volume': 0, 'oi': 0}}
    filtered = settings_mod.apply_basic_filters(enriched, settings)
    assert filtered == enriched


def test_min_oi_alias_property(monkeypatch):
    monkeypatch.setenv('G6_FILTER_MIN_OI','40')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    assert settings.min_oi == settings.min_open_interest == 40
