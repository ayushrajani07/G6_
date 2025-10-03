from src.utils.strikes import build_strikes


def test_build_strikes_basic_indices():
    strikes = build_strikes(atm=20000, n_itm=2, n_otm=2, index_symbol='NIFTY')
    # Step 50 expected
    assert strikes == [19900.0, 19950.0, 20000.0, 20050.0, 20100.0]


def test_build_strikes_banknifty_step():
    strikes = build_strikes(atm=45000, n_itm=1, n_otm=1, index_symbol='BANKNIFTY')
    assert strikes == [44900.0, 45000.0, 45100.0]


def test_build_strikes_zero_counts_includes_atm():
    strikes = build_strikes(atm=15000, n_itm=0, n_otm=0, index_symbol='NIFTY')
    assert strikes == [15000.0]


def test_build_strikes_scale_factor():
    # scale reduces 4 -> 2 when factor 0.5
    strikes = build_strikes(atm=20000, n_itm=4, n_otm=4, index_symbol='NIFTY', scale=0.5)
    # scaled counts 2/2
    assert strikes == [19900.0, 19950.0, 20000.0, 20050.0, 20100.0]


def test_build_strikes_invalid_atm():
    assert build_strikes(atm=0, n_itm=2, n_otm=2, index_symbol='NIFTY') == []


def test_build_strikes_env_override(monkeypatch):
    monkeypatch.setenv('G6_STRIKE_STEP_NIFTY', '25')
    strikes = build_strikes(atm=20000, n_itm=1, n_otm=1, index_symbol='NIFTY')
    assert strikes == [19975.0, 20000.0, 20025.0]
