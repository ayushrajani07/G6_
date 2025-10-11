import copy, os
from src.collectors.pipeline.parity import compute_parity_score

BASE_LEGACY = {
    'indices': [
        {'index': 'A', 'strike_coverage_avg': 0.10},
        {'index': 'B', 'strike_coverage_avg': 0.30},
        {'index': 'C', 'strike_coverage_avg': 0.50},
    ],
    'alerts': {'categories': {}},
}
BASE_PIPELINE_IDENT = copy.deepcopy(BASE_LEGACY)
BASE_PIPELINE_SHIFT = {
    'indices': [
        {'index': 'A', 'strike_coverage_avg': 0.10},
        {'index': 'B', 'strike_coverage_avg': 0.10},  # variance reduced
        {'index': 'C', 'strike_coverage_avg': 0.10},
    ],
    'alerts': {'categories': {}},
}

def test_cov_variance_identical(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_COV_VAR','1')
    monkeypatch.delenv('G6_PARITY_STRIKE_SHAPE', raising=False)
    monkeypatch.delenv('G6_PARITY_EXTENDED', raising=False)
    score = compute_parity_score(BASE_LEGACY, BASE_PIPELINE_IDENT)
    # base v1 + cov_var => version 2
    assert score['version'] == 2
    assert 'strike_cov_variance' in score['components']
    assert score['components']['strike_cov_variance'] == 1.0
    assert score['details']['strike_cov_variance']['diff_norm'] == 0

def test_cov_variance_degrades(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_COV_VAR','1')
    score = compute_parity_score(BASE_LEGACY, BASE_PIPELINE_SHIFT)
    comp = score['components']['strike_cov_variance']
    assert 0 <= comp < 1
    assert score['details']['strike_cov_variance']['diff_norm'] > 0

def test_cov_variance_with_other_features(monkeypatch):
    monkeypatch.setenv('G6_PARITY_STRIKE_COV_VAR','1')
    monkeypatch.setenv('G6_PARITY_STRIKE_SHAPE','1')
    monkeypatch.setenv('G6_PARITY_EXTENDED','1')
    score = compute_parity_score(BASE_LEGACY, BASE_PIPELINE_IDENT)
    # base 1 + extended + shape + cov_var => 4
    assert score['version'] == 4
