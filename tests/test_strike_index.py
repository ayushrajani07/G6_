from src.utils.strike_index import build_strike_index

def test_strike_index_basic_membership():
    si = build_strike_index([24800, 24850, 24900])
    assert si.contains(24800)
    assert si.contains(24850)
    assert not si.contains(24700)


def test_strike_index_diff_and_coverage():
    si = build_strike_index([100, 110, 120, 130])
    realized = [100, 130, 125]  # 110/120 missing
    diff = si.diff(realized)
    assert 110 in diff['missing'] and 120 in diff['missing']
    cov = si.realized_coverage(realized)
    assert 0 < cov < 1


def test_strike_index_describe():
    si = build_strike_index([100, 120, 140, 160, 180, 200, 220])
    d = si.describe()
    assert d['count'] == 7
    assert d['min'] == 100
    assert d['max'] == 220
