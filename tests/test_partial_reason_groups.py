import copy
from src.collectors.partial_reasons import group_reason_counts, STABLE_GROUP_ORDER


def test_group_reason_counts_basic():
    flat = {'low_strike':2,'low_field':1,'unknown':3,'prefilter_clamp':4}
    grouped = group_reason_counts(flat)
    # coverage_low group present with summed counts
    assert 'coverage_low' in grouped
    assert grouped['coverage_low']['total'] == 3
    assert grouped['coverage_low']['reasons'] == {'low_strike':2,'low_field':1,'low_both':0} or grouped['coverage_low']['reasons'] == {'low_strike':2,'low_field':1}
    # prefilter group
    assert grouped['prefilter']['total'] == 4
    # other group includes unknown
    assert grouped['other']['total'] == 3
    # group ordering reference stable
    assert STABLE_GROUP_ORDER[0] == 'coverage_low'


def test_pipeline_integration_partial_groups(monkeypatch):
    # Simulate pipeline return assembly using helper directly
    flat = {'low_strike':1,'low_both':1,'prefilter_clamp':2}
    grouped = group_reason_counts(flat)
    assert grouped['coverage_low']['total'] == 2
    cov_reasons = dict(grouped['coverage_low']['reasons'])  # type: ignore
    assert 'low_strike' in cov_reasons
    assert 'low_both' in cov_reasons
    assert grouped['prefilter']['total'] == 2
