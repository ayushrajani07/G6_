import os
import importlib
from prometheus_client import REGISTRY

def _clear_followups_metrics():
    # Best-effort removal to avoid duplicate registration noise across tests
    to_remove = [name for name in ['g6_followups_interp_guard_total','g6_followups_risk_drift_total','g6_followups_bucket_coverage_total','g6_followups_last_state']]
    # Cannot directly remove from REGISTRY easily; rely on separate process namespace; tests run in same process so idempotent registration logic handles it.
    pass

def _metric_value(name, labels=None):
    for fam in REGISTRY.collect():
        if fam.name == name:
            for s in fam.samples:
                if labels:
                    if all(s.labels.get(k) == v for k,v in labels.items()):
                        return s.value
                else:
                    return s.value
    return 0

def _metric_samples(name):
    vals = []
    for fam in REGISTRY.collect():
        if fam.name == name:
            for s in fam.samples:
                vals.append(s)
    return vals

def test_followups_interpolation_guard(tmp_path):
    os.environ['G6_FOLLOWUPS_ENABLED'] = '1'
    os.environ['G6_FOLLOWUPS_INTERP_THRESHOLD'] = '0.5'
    os.environ['G6_FOLLOWUPS_INTERP_CONSEC'] = '2'
    import src.adaptive.followups as f
    importlib.reload(f)
    # Feed two high fractions to trigger
    f.feed('global', interpolated_fraction=0.6)
    f.feed('global', interpolated_fraction=0.65)
    # Family name is base metric name (counter sample internally suffixed _total)
    assert _metric_value('g6_followups_interp_guard', {'index':'global'}) >= 1
    # Gauge should reflect last fraction fed (0.65)
    assert any(abs(s.value - 0.65) < 1e-9 for s in _metric_samples('g6_followups_last_state') if s.labels.get('index')=='global' and s.labels.get('type')=='interp')


def test_followups_bucket_guard(tmp_path):
    os.environ['G6_FOLLOWUPS_ENABLED'] = '1'
    os.environ['G6_FOLLOWUPS_BUCKET_THRESHOLD'] = '0.8'
    os.environ['G6_FOLLOWUPS_BUCKET_CONSEC'] = '2'
    import src.adaptive.followups as f
    importlib.reload(f)
    # Provide explicit interpolated_fraction=0.0 so surface path is invoked deterministically
    f.feed('global', interpolated_fraction=0.0, bucket_utilization=0.75)
    f.feed('global', interpolated_fraction=0.0, bucket_utilization=0.70)
    assert _metric_value('g6_followups_bucket_coverage', {'index':'global'}) >= 1
    # Gauge reflects last bucket utilization (0.70)
    assert any(abs(s.value - 0.70) < 1e-9 for s in _metric_samples('g6_followups_last_state') if s.labels.get('index')=='global' and s.labels.get('type')=='bucket')


def test_followups_risk_drift(tmp_path):
    os.environ['G6_FOLLOWUPS_ENABLED'] = '1'
    os.environ['G6_FOLLOWUPS_RISK_WINDOW'] = '4'
    os.environ['G6_FOLLOWUPS_RISK_DRIFT_PCT'] = '0.20'
    os.environ['G6_FOLLOWUPS_RISK_MIN_OPTIONS'] = '1'
    import src.adaptive.followups as f
    importlib.reload(f)
    # Build window: first value small, last value large to exceed 20% change
    f.feed('global', notional_delta=100.0, option_count=10)
    f.feed('global', notional_delta=110.0, option_count=10)
    f.feed('global', notional_delta=115.0, option_count=10)
    f.feed('global', notional_delta=140.0, option_count=10)  # window full triggers drift
    up = _metric_value('g6_followups_risk_drift', {'index':'global','sign':'up'})
    assert up >= 1
    # Gauge risk drift type should have been set (non-zero drift)
    assert any(s.value > 0 for s in _metric_samples('g6_followups_last_state') if s.labels.get('index')=='global' and s.labels.get('type')=='risk')
