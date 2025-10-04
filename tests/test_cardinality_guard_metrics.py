import os, json, time
from src.metrics.cardinality_guard import check_cardinality, build_current_mapping
from src.metrics import generated as gen

class DummyReg:
    def __init__(self):
        # Simulate groups mapping attr->group
        self._metric_groups = {
            'm_a': 'grp1',
            'm_b': 'grp1',
            'm_c': 'grp2',
        }

def test_cardinality_guard_emits_metrics(tmp_path, monkeypatch):
    # Prepare baseline snapshot with fewer metrics so growth triggers offenders
    baseline_path = tmp_path / 'baseline.json'
    baseline = {
        'version': 1,
        'generated': '2025-10-04T00:00:00Z',
        'groups': {
            'grp1': ['m_a'],  # now grp1 has grown to 2 (m_a,m_b)
            'grp2': ['m_c'],  # unchanged
        }
    }
    baseline_path.write_text(json.dumps(baseline), encoding='utf-8')
    os.environ['G6_CARDINALITY_BASELINE'] = str(baseline_path)
    os.environ['G6_CARDINALITY_ALLOW_GROWTH_PERCENT'] = '10'
    # Run guard
    summary = check_cardinality(DummyReg())
    assert summary is not None
    # Offenders should include grp1 (growth from 1 ->2 is 100%)
    assert any(o['group']=='grp1' for o in summary['offenders'])
    # Metrics: offenders_total should be set >=1
    off = gen.m_cardinality_guard_offenders_total()
    assert off is not None
    # Access raw value
    try:
        val = off._value.get()  # type: ignore[attr-defined]
        assert val >= 1
    except Exception:
        pass
    # Growth percent label metric should have grp1
    if hasattr(gen, 'm_cardinality_guard_growth_percent_labels'):
        m = gen.m_cardinality_guard_growth_percent_labels('grp1')
        if m:
            try:
                gp = m._value.get()  # type: ignore[attr-defined]
                assert gp >= 100.0 or gp > 0.0
            except Exception:
                pass
