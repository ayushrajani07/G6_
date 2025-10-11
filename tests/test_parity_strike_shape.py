import os, copy
from src.collectors.pipeline.parity import compute_parity_score

LEGACY_BASE = {
    'indices': [
        {'index': 'IDX1', 'option_count': 10},
        {'index': 'IDX2', 'option_count': 20},
        {'index': 'IDX3', 'option_count': 30},
    ],
    'alerts': {'categories': {}},
    'options_total': 60,
}
PIPELINE_SAME = copy.deepcopy(LEGACY_BASE)
PIPELINE_DIFF = {
    'indices': [
        {'index': 'IDX1', 'option_count': 5},
        {'index': 'IDX2', 'option_count': 55},  # shifted distribution
        {'index': 'IDX3', 'option_count': 0},
    ],
    'alerts': {'categories': {}},
    'options_total': 60,
}

def test_strike_shape_identical(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_SHAPE','1')
    # ensure base version unaffected by extended flag for clarity
    monkeypatch.delenv('G6_PARITY_EXTENDED', raising=False)
    score = compute_parity_score(LEGACY_BASE, PIPELINE_SAME)
    assert 'strike_shape' in score['components']
    assert score['components']['strike_shape'] == 1.0
    # Version should reflect shape bump: base v1 + shape => 2 (if extended off)
    assert score['version'] == 2

def test_strike_shape_degrades(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_SHAPE','1')
    monkeypatch.delenv('G6_PARITY_EXTENDED', raising=False)
    score = compute_parity_score(LEGACY_BASE, PIPELINE_DIFF)
    assert 'strike_shape' in score['components']
    comp = score['components']['strike_shape']
    assert 0 <= comp < 1.0
    # Details include distance
    dist = score['details']['strike_shape']['distance']
    assert dist > 0
    assert score['version'] == 2

def test_shape_and_extended_version(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_SHAPE','1')
    monkeypatch.setenv('G6_PARITY_EXTENDED','1')
    score = compute_parity_score(LEGACY_BASE, PIPELINE_SAME)
    # extended + shape => base 1 +1 +1 => 3
    assert score['version'] == 3
