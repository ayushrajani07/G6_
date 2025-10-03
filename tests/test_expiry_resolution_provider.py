import datetime as _dt

import warnings
from src.broker.kite_provider import KiteProvider


def _make_list(today: _dt.date):
    # Make an ordered list including two in this month and two in next month
    d1 = today + _dt.timedelta(days=1)
    d2 = today + _dt.timedelta(days=8)
    end_this_month = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    d3 = end_this_month
    start_next = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
    end_next = (start_next + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    d4 = start_next + _dt.timedelta(days=5)
    d5 = end_next
    return [d1, d2, d3, d4, d5]


def test_kite_provider_resolve_from_list(monkeypatch):
    today = _dt.date.today()
    exp = _make_list(today)
    # Localize deprecation warning from KiteProvider construction so it does not leak to global summary
    with warnings.catch_warnings(record=True):
        warnings.simplefilter('ignore', DeprecationWarning)
        kp = KiteProvider(api_key="dummy", access_token="dummy")

    # Patch get_expiry_dates to return our synthetic list
    monkeypatch.setattr(kp, 'get_expiry_dates', lambda idx: list(exp))

    sorted_exp = sorted([d for d in exp if d >= today])

    assert kp.resolve_expiry('NIFTY', 'this_week') == sorted_exp[0]
    assert kp.resolve_expiry('NIFTY', 'next_week') == (sorted_exp[1] if len(sorted_exp) >= 2 else sorted_exp[0])

    # this_month -> last of current month (fallback to closest if none)
    cands_this = [d for d in sorted_exp if d.year == today.year and d.month == today.month]
    if cands_this:
        assert kp.resolve_expiry('NIFTY', 'this_month') == max(cands_this)
    else:
        assert kp.resolve_expiry('NIFTY', 'this_month') == sorted_exp[0]

    # next_month -> last of next month (fallback to second closest or closest)
    nm_year = today.year + (1 if today.month == 12 else 0)
    nm_month = 1 if today.month == 12 else (today.month + 1)
    cands_next = [d for d in sorted_exp if d.year == nm_year and d.month == nm_month]
    if cands_next:
        assert kp.resolve_expiry('NIFTY', 'next_month') == max(cands_next)
    else:
        assert kp.resolve_expiry('NIFTY', 'next_month') == (sorted_exp[1] if len(sorted_exp) >= 2 else sorted_exp[0])
