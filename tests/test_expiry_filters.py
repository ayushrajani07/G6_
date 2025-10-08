import os
import pytest
from types import SimpleNamespace
from src.collector.settings import CollectorSettings
from src.collectors.modules.expiry_processor import apply_basic_filters

@pytest.fixture
def sample_quotes():
    # Generate deterministic quote dict
    data = {}
    for i, vol in enumerate([0,5,10,20,40,80,160,320,640,1280,2560,5120]):
        data[f"OPT{i}"] = {"volume": vol, "oi": vol//2 + 1}
    return data

def test_basic_filters_min_volume_and_oi(sample_quotes):
    settings = CollectorSettings(min_volume=100, min_oi=20)
    filtered, meta = apply_basic_filters(sample_quotes, settings, 'INDEX', 'W1', logger=__import__('logging').getLogger(__name__))
    # Expect only entries with volume>=100 AND oi>=20 (oi ~ vol//2 +1)
    assert all(int(v.get('volume',0)) >= 100 and int(v.get('oi',0)) >= 20 for v in filtered.values())
    assert meta['before'] == len(sample_quotes)
    assert meta['after'] == len(filtered)
    assert meta['applied'] is True

def test_basic_filters_percentile(sample_quotes):
    # Set percentile 0.5 -> keep top 50% by volume (sorted ascending)
    settings = CollectorSettings(volume_percentile=0.5)
    filtered, meta = apply_basic_filters(sample_quotes, settings, 'INDEX', 'W1', logger=__import__('logging').getLogger(__name__))
    vols = sorted([q['volume'] for q in sample_quotes.values()])
    cutoff = vols[int(len(vols)*0.5)]
    assert all(v['volume'] >= cutoff for v in filtered.values())
    assert meta['pct_cutoff'] == cutoff
    assert meta['after'] <= meta['before']

def test_basic_filters_combined(sample_quotes):
    settings = CollectorSettings(min_volume=50, min_oi=10, volume_percentile=0.25)
    filtered, meta = apply_basic_filters(sample_quotes, settings, 'IDX', 'M1', logger=__import__('logging').getLogger(__name__))
    assert meta['applied'] is True
    assert meta['after'] <= meta['before']
    # ensure all rows satisfy base thresholds
    for v in filtered.values():
        assert v['volume'] >= 50 and v['oi'] >= 10

def test_basic_filters_no_settings_returns_original(sample_quotes):
    filtered, meta = apply_basic_filters(sample_quotes, None, 'IDX', 'M1', logger=__import__('logging').getLogger(__name__))
    assert filtered == sample_quotes
    assert meta['applied'] is False

def test_basic_filters_small_set_percentile_no_effect():
    sample = {"A": {"volume": 10, "oi": 5}, "B": {"volume": 20, "oi": 9}}
    settings = CollectorSettings(volume_percentile=0.9)
    filtered, meta = apply_basic_filters(sample, settings, 'IDX', 'M1', logger=__import__('logging').getLogger(__name__))
    # percentile logic requires >10 entries; should be untouched
    assert filtered == sample
    assert meta['applied'] is False
