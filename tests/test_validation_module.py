import datetime
from src.validation import list_validators, run_validators


def test_validation_filters_zero_price_and_dummy_pattern():
    rows = [
        {'last_price': 0, 'oi': 10, 'volume': 5, 'strike': 100, 'instrument_type': 'CE'},  # zero price -> drop
        {'last_price': 10, 'oi': -5, 'volume': -2, 'strike': 100, 'instrument_type': 'PE'},  # neg clamp
        {'last_price': 1200, 'oi': 3, 'volume': 2, 'strike': 100, 'instrument_type': 'CE'},  # dummy heuristic (price<1500 small oi/vol)
        {'last_price': 2500, 'oi': 15, 'volume': 7, 'strike': 100, 'instrument_type': 'CE'},  # keep
    ]
    ctx = {'index': 'NIFTY', 'expiry': datetime.date.today(), 'stage': 'unit-test'}
    cleaned, reports = run_validators(ctx, rows)
    # zero price row dropped; dummy pattern row price=1200 volume 2 oi 3 dropped
    assert len(cleaned) == 2
    # second row should have oi/volume clamped to 0
    clamped = [r for r in cleaned if r['last_price'] == 10][0]
    assert clamped['oi'] == 0 and clamped['volume'] == 0
    # ensure validators are registered
    vnames = list_validators()
    assert 'drop_zero_price' in vnames
    assert 'dummy_pattern_filter' in vnames
