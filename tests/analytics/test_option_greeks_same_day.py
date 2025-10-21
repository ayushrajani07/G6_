from datetime import date, datetime, time as _time

from src.analytics.option_greeks import OptionGreeks


def test_dte_same_day_before_1530_positive():
    og = OptionGreeks()
    today = date.today()
    # Simulate current time at 10:00 AM local
    now_dt = datetime.combine(today, _time(10, 0, 0))
    T_years = og._calculate_dte(today, current_date=now_dt)
    assert T_years > 0.0


def test_dte_same_day_after_1530_zero():
    og = OptionGreeks()
    today = date.today()
    # Simulate current time at 16:00 (after market expiry time)
    now_dt = datetime.combine(today, _time(16, 0, 0))
    T_years = og._calculate_dte(today, current_date=now_dt)
    assert T_years == 0.0


def test_black_scholes_same_day_greeks_non_zero_before_1530():
    og = OptionGreeks()
    today = date.today()
    now_dt = datetime.combine(today, _time(10, 0, 0))
    # At-the-money with reasonable sigma
    S = 100.0
    K = 100.0
    sigma = 0.2

    call = og.black_scholes(True, S=S, K=K, T=today, sigma=sigma, current_date=now_dt)
    put = og.black_scholes(False, S=S, K=K, T=today, sigma=sigma, current_date=now_dt)

    # Delta should be near +/-0.5 at ATM, non-zero; gamma/vega should be > 0; theta typically negative
    for greeks in (call, put):
        assert greeks["gamma"] > 0.0
        assert greeks["vega"] > 0.0
        # Theta can be very small but should not collapse to exactly 0 pre-expiry
        assert greeks["theta"] != 0.0
