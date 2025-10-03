import datetime as dt

from src.utils.expiry_service import ExpiryService, is_weekly_expiry, is_monthly_expiry, select_expiries


def _build_candidates(base: dt.date) -> list[dt.date]:
    # Produce a deterministic spread of dates across two months including past ones.
    # Start 5 days in the past, generate 40 sequential days.
    return [base + dt.timedelta(days=i - 5) for i in range(40)]


def test_selection_rules_basic():
    today = dt.date(2025, 1, 15)  # Wednesday
    svc = ExpiryService(today=today)
    cands = _build_candidates(today)
    this_week = svc.select("this_week", cands)
    next_week = svc.select("next_week", cands)
    assert this_week >= today
    assert next_week >= this_week
    # Month rules
    this_month = svc.select("this_month", cands)
    next_month = svc.select("next_month", cands)
    assert this_month.month == today.month
    assert next_month.month in {today.month, (today.month % 12) + 1}


def test_selection_rules_month_fallback_when_no_scope():
    # If there are no future dates in current month, fallback to first future.
    today = dt.date(2025, 1, 31)
    svc = ExpiryService(today=today)
    cands = [dt.date(2025, 1, 1), dt.date(2025, 2, 5), dt.date(2025, 2, 12)]
    this_month = svc.select("this_month", cands)
    # Reverted semantics: choose first monthly anchor (last expiry of next month) => 2025-02-12
    assert this_month == dt.date(2025, 2, 12)


def test_next_month_last_expiry_selection():
    today = dt.date(2025, 1, 10)
    svc = ExpiryService(today=today)
    cands = [
        dt.date(2025, 1, 11), dt.date(2025, 1, 18), dt.date(2025, 1, 25),
        dt.date(2025, 2, 5), dt.date(2025, 2, 12), dt.date(2025, 2, 19), dt.date(2025, 2, 26),
    ]
    next_month = svc.select("next_month", cands)
    assert next_month == dt.date(2025, 2, 26)


def test_weekly_and_monthly_classification_last_thursday():
    # Monthly expiry typically last Thursday; verify classification.
    # Choose April 2025 where last Thursday is 24th (hypothetical example; check calendar)
    # Actually April 24 2025 is a Thursday; next Thursday is May 1 (different month) so monthly.
    expiry = dt.date(2025, 4, 24)
    assert is_weekly_expiry(expiry, weekly_dow=3)
    assert is_monthly_expiry(expiry, monthly_dow=3)


def test_holiday_filtering_removes_dates():
    today = dt.date(2025, 3, 1)
    holidays = {dt.date(2025, 3, 6), dt.date(2025, 3, 13)}
    svc = ExpiryService(today=today, holiday_fn=lambda d: d in holidays)
    cands = [dt.date(2025, 3, d) for d in (6, 13, 20, 27)]
    # this_week picks first non-holiday future => 2025-03-20
    assert svc.select("this_week", cands) == dt.date(2025, 3, 20)
    # next_week should then be next available (2025-03-27)
    assert svc.select("next_week", cands) == dt.date(2025, 3, 27)


def test_batch_select_expiries_tolerant():
    today = dt.date(2025, 5, 10)
    svc = ExpiryService(today=today)
    cands = [dt.date(2025, 5, 15), dt.date(2025, 5, 22), dt.date(2025, 6, 26)]
    out = select_expiries(svc, ["this_week", "next_week", "this_month", "next_month", "bad_rule"], cands)
    assert "bad_rule" not in out
    assert set(out.keys()) == {"this_week", "next_week", "this_month", "next_month"}


def test_error_when_no_future():
    today = dt.date(2025, 7, 10)
    svc = ExpiryService(today=today)
    cands = [dt.date(2025, 7, 1), dt.date(2025, 7, 5)]
    try:
        svc.select("this_week", cands)
    except ValueError as e:
        assert "no future" in str(e)
    else:  # pragma: no cover
        assert False, "Expected ValueError for no future expiries"
