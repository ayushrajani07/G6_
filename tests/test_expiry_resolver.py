"""Parity tests for ExpiryResolver (A16).

We simulate a small instrument universe and compare legacy extraction logic
(approximated) with new resolver.extract + fabricate behavior.
"""
from __future__ import annotations
import datetime as dt
from src.provider.expiries import ExpiryResolver


def sample_instruments(index: str, base_date: dt.date) -> list[dict]:
    # Create instruments with varying strikes and two expiries
    instruments = []
    for strike in (100, 150, 200, 250, 300):
        instruments.append({
            "segment": "NFO-OPT",
            "tradingsymbol": f"{index}{strike}",
            "strike": strike,
            "expiry": (base_date + dt.timedelta(days=7)).isoformat(),
        })
    instruments.append({
        "segment": "NFO-OPT",
        "tradingsymbol": f"{index}X",
        "strike": 200,
        "expiry": (base_date + dt.timedelta(days=14)).isoformat(),
    })
    return instruments


def test_extract_matches_expected():
    today = dt.date(2025, 10, 7)
    res = ExpiryResolver()
    insts = sample_instruments("NIFTY", today)
    extracted = res.extract("NIFTY", insts, atm_strike=200, strike_window=150, today=today)
    assert len(extracted) == 2
    assert all(isinstance(d, dt.date) for d in extracted)


def test_fabricate_when_no_extracted_but_instruments():
    today = dt.date(2025, 10, 7)
    res = ExpiryResolver()
    insts = []  # none -> fabricate should not occur in extract; occurs in resolve if instruments exist but no expiries
    fabricated = res.fabricate(today)
    assert len(fabricated) == 2 and fabricated[0] < fabricated[1]


def test_resolve_with_fabrication_path():
    today = dt.date(2025, 10, 7)
    res = ExpiryResolver()

    def fetch_instruments():
        # Instruments with no valid expiries (expiry missing)
        return [{"segment": "NFO-OPT", "tradingsymbol": "NIFTYTEST", "strike": 200}]

    def atm_provider(_):
        return 200

    out = res.resolve("NIFTY", fetch_instruments, atm_provider, ttl=10.0, now_func=lambda: 0.0)
    assert len(out) == 2  # fabricated


def test_resolve_cache_hit():
    today = dt.date(2025, 10, 7)
    res = ExpiryResolver()
    insts = sample_instruments("NIFTY", today)

    def fetch_instruments():
        return insts

    def atm_provider(_):
        return 200

    first = res.resolve("NIFTY", fetch_instruments, atm_provider, ttl=100.0, now_func=lambda: 0.0)
    second = res.resolve("NIFTY", lambda: [], atm_provider, ttl=100.0, now_func=lambda: 50.0)
    assert first == second and len(first) == 2
