import datetime as _dt
from src.filters.option_filter import OptionFilterContext, accept_option


def _make_inst(ts, expiry, strike, itype='CE', name=None, underlying=None):
    return {
        'tradingsymbol': ts,
        'expiry': expiry,
        'strike': strike,
        'instrument_type': itype,
        'name': name,
        'underlying': underlying,
    }


def test_accept_basic_strict():
    expiry = _dt.date(2025, 1, 30)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0, 20050.0},
        match_mode='strict',
        underlying_strict=True,
        safe_mode=True,
    )
    inst = _make_inst('NIFTY30JAN25C200000', expiry, 20000, 'CE', name='NIFTY')
    ok, reason = accept_option(inst, ctx, {})
    assert ok, reason


def test_reject_expiry_mismatch():
    expiry = _dt.date(2025, 1, 30)
    wrong_expiry = _dt.date(2025, 2, 6)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0},
        match_mode='strict',
        underlying_strict=True,
        safe_mode=True,
    )
    inst = _make_inst('NIFTY06FEB25C200000', wrong_expiry, 20000, 'CE', name='NIFTY')
    ok, reason = accept_option(inst, ctx, {})
    assert not ok and reason == 'expiry_mismatch'


def test_reject_strike_mismatch():
    expiry = _dt.date(2025, 1, 30)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0},
        match_mode='strict',
        underlying_strict=True,
        safe_mode=True,
    )
    inst = _make_inst('NIFTY30JAN25C201000', expiry, 20100, 'CE', name='NIFTY')
    ok, reason = accept_option(inst, ctx, {})
    assert not ok and reason == 'strike_mismatch'


def test_reject_underlying_mismatch_strict():
    expiry = _dt.date(2025, 1, 30)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0},
        match_mode='strict',
        underlying_strict=True,
        safe_mode=True,
    )
    inst = _make_inst('NIFTY30JAN25C200000', expiry, 20000, 'CE', name='BANKNIFTY')
    ok, reason = accept_option(inst, ctx, {})
    assert not ok and reason == 'underlying_mismatch'


def test_lenient_mode_allows_symbol_variation():
    # In lenient mode we rely less on exact symbol parsing; use variant symbol
    expiry = _dt.date(2025, 1, 30)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0},
        match_mode='lenient',
        underlying_strict=False,
        safe_mode=False,
    )
    inst = _make_inst('NIFTY30JAN25C200000', expiry, 20000, 'CE', name='OTHER')
    ok, reason = accept_option(inst, ctx, {})
    assert ok, reason


def test_contamination_sample_collection():
    expiry = _dt.date(2025, 1, 30)
    ctx = OptionFilterContext(
        index_symbol='NIFTY',
        expiry_target=expiry,
        strike_key_set={20000.0},
        match_mode='strict',
        underlying_strict=True,
        safe_mode=True,
    )
    inst = _make_inst('BANKNIFTY30JAN25C200000', expiry, 20000, 'CE', name='BANKNIFTY')
    samples = []
    ok, reason = accept_option(inst, ctx, {}, contamination_samples=samples)
    assert not ok and reason in ('root_mismatch','underlying_mismatch')
    assert samples  # collected
