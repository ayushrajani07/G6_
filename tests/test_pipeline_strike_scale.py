import os
from types import SimpleNamespace

def test_pipeline_build_strikes_with_scale(monkeypatch):
    # Simulate pipeline branch using build_strikes with scale factor 0.5
    from src.utils.strikes import build_strikes
    atm = 20000
    base_itm = 4
    base_otm = 4
    scaled = build_strikes(atm=atm, n_itm=base_itm, n_otm=base_otm, index_symbol='NIFTY', scale=0.5)
    # 4 * 0.5 => 2 each side
    assert scaled == [19900.0, 19950.0, 20000.0, 20050.0, 20100.0]
