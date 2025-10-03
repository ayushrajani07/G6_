import datetime as _dt

from src.collectors.providers_interface import Providers


class _FakeProviderNoResolve:
    """Fake provider exposing only get_expiry_dates for fallback testing."""

    def __init__(self, expiries):
        self._exp = expiries

    def get_expiry_dates(self, index_symbol):
        return list(self._exp)


def _make_synthetic_expiries(today: _dt.date):
    # Closest and 2nd closest
    d1 = today + _dt.timedelta(days=1)
    d2 = today + _dt.timedelta(days=8)
    # Last of this month (simulate multiple in same month and pick last)
    # Create a few dates within this month beyond today
    end_this_month = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    d3 = min(d2 + _dt.timedelta(days=2), end_this_month)
    d4 = end_this_month
    # Last of next month
    start_next = (today.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
    end_next_month = (start_next + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    d5 = start_next + _dt.timedelta(days=5)
    d6 = end_next_month
    return [d1, d2, d3, d4, d5, d6]


def test_providers_fallback_resolver_uses_list_selection():
    today = _dt.date.today()
    exp_list = _make_synthetic_expiries(today)
    fake = _FakeProviderNoResolve(exp_list)
    prov = Providers(primary_provider=fake)

    sorted_exp = sorted([d for d in exp_list if d >= today])

    this_week = prov.resolve_expiry('NIFTY', 'this_week')
    assert this_week == sorted_exp[0]

    next_week = prov.resolve_expiry('NIFTY', 'next_week')
    assert next_week == (sorted_exp[1] if len(sorted_exp) >= 2 else sorted_exp[0])

    this_month = prov.resolve_expiry('NIFTY', 'this_month')
    # last in today's month from available future expiries
    cands_this = [d for d in sorted_exp if d.year == today.year and d.month == today.month]
    if cands_this:
        assert this_month == max(cands_this)
    else:
        # fallback to closest if no same-month expiry exists
        assert this_month == sorted_exp[0]

    next_month = prov.resolve_expiry('NIFTY', 'next_month')
    # last in next month; else second closest
    nm_year = today.year + (1 if today.month == 12 else 0)
    nm_month = 1 if today.month == 12 else (today.month + 1)
    cands_next = [d for d in sorted_exp if d.year == nm_year and d.month == nm_month]
    if cands_next:
        assert next_month == max(cands_next)
    else:
        assert next_month == (sorted_exp[1] if len(sorted_exp) >= 2 else sorted_exp[0])
