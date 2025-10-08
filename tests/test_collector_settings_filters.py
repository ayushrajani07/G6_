import os
import importlib


def test_basic_filters_min_volume_and_oi(monkeypatch):
    # Set environment thresholds
    monkeypatch.setenv('G6_FILTER_MIN_VOLUME', '100')
    monkeypatch.setenv('G6_FILTER_MIN_OI', '50')
    # Ensure percentile off
    monkeypatch.delenv('G6_FILTER_VOLUME_PERCENTILE', raising=False)
    # Reload settings module to pick env
    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    CollectorSettings = settings_mod.CollectorSettings
    apply_basic_filters = settings_mod.apply_basic_filters

    s = CollectorSettings.load()
    enriched = {
        'A': {'volume': 120, 'oi': 60},   # keep
        'B': {'volume': 99,  'oi': 100},  # drop (volume)
        'C': {'volume': 500, 'oi': 40},   # drop (oi)
        'D': {'volume': 150, 'oi': 50},   # keep (boundary)
        'E': {'volume': 0,   'oi': 0},    # drop both
    }
    filtered = apply_basic_filters(enriched, s)
    assert set(filtered.keys()) == {'A','D'}


def test_basic_filters_zero_thresholds(monkeypatch):
    # No thresholds -> noop
    monkeypatch.delenv('G6_FILTER_MIN_VOLUME', raising=False)
    monkeypatch.delenv('G6_FILTER_MIN_OI', raising=False)
    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    CollectorSettings = settings_mod.CollectorSettings
    apply_basic_filters = settings_mod.apply_basic_filters
    s = CollectorSettings.load()
    enriched = {'X': {'volume': 1, 'oi': 1}, 'Y': {'volume': 0, 'oi': 0}}
    filtered = apply_basic_filters(enriched, s)
    assert filtered == enriched  # unchanged
