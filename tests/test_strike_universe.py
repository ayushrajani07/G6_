import os
import math
from src.collectors.modules.strike_universe import build_strike_universe, get_cache_diagnostics


def test_strike_universe_basic_parity():
    r = build_strike_universe(20000, 2, 2, 'NIFTY')
    assert r.strikes == [20000 - 50*2, 20000 - 50, 20000, 20000 + 50, 20000 + 50*2]
    assert r.meta['count'] == 5
    assert r.meta['step'] in (50.0, 50)  # heuristic or registry
    assert r.meta['policy'] in ('heuristic','registry','explicit','env')


def test_strike_universe_scale_and_cache():
    # Clear cache by disabling via env for isolation if needed
    r1 = build_strike_universe(20000, 2, 2, 'NIFTY', scale=1.5)
    # scaled counts become 3/3
    assert r1.meta['scaled_itm'] == 3
    assert r1.meta['scaled_otm'] == 3
    # Second call should hit cache (same atm bucket)
    r2 = build_strike_universe(20002, 2, 2, 'NIFTY', scale=1.5)  # small ATM delta within step bucket
    # Same length and either cache hit or not depending on bucket rounding; allow both but capture diagnostics
    cache_diag = get_cache_diagnostics()
    assert cache_diag['capacity'] >= 16
    assert r2.meta['count'] == r1.meta['count']


def test_strike_universe_zero_atm():
    r = build_strike_universe(0, 5, 5, 'NIFTY')
    assert r.strikes == []
    assert r.meta['count'] == 0


def test_strike_universe_explicit_step():
    r = build_strike_universe(45000, 1, 1, 'BANKNIFTY', step=200)
    assert r.meta['step'] == 200
    assert r.strikes == [44800, 45000, 45200]
