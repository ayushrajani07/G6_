"""Synthetic data builders for Kite provider (Phase 2 extraction).

Centralizes fabrication logic used when real API calls fail or when auth is
unavailable. Behavior preserved verbatim from pre-refactor implementation.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from typing import Any

# Base ATM anchors and strike steps (mirrors constants inline in legacy path)
_BASE_ATM = {
    'NIFTY': 24800,
    'BANKNIFTY': 54000,
    'FINNIFTY': 25950,
    'SENSEX': 81000,
}
_STEP = {
    'NIFTY': 50,
    'FINNIFTY': 50,
    'BANKNIFTY': 100,
    'SENSEX': 100,
}

_INDEX_WEEKDAY = {
    'NIFTY': 3,       # Thursday
    'BANKNIFTY': 3,
    'FINNIFTY': 1,    # Tuesday
    'SENSEX': 4,      # Friday (synthetic assumption)
}


def _next_weekday(start: _dt.date, target_weekday: int) -> _dt.date:
    d = start
    for _ in range(14):  # cap search horizon
        if d.weekday() == target_weekday:
            return d
        d += _dt.timedelta(days=1)
    return start + _dt.timedelta(days=7)


def generate_synthetic_instruments() -> list[dict[str, Any]]:
    """Reproduce legacy synthetic instrument lattice (two expiries, 3 strikes, CE/PE)."""
    today = _dt.date.today()
    this_map = {
        'NIFTY': _next_weekday(today, 3),
        'BANKNIFTY': _next_weekday(today, 3),
        'FINNIFTY': _next_weekday(today, 1),
        'SENSEX': _next_weekday(today, 4),
    }
    next_map = {k: v + _dt.timedelta(days=7) for k, v in this_map.items()}
    exp_map = {k: [this_map[k], next_map[k]] for k in this_map}
    out: list[dict[str, Any]] = []
    token_counter = 1
    for idx, expiries in exp_map.items():
        atm = _BASE_ATM[idx]
        step = _STEP[idx]
        strikes = [atm - step, atm, atm + step]
        for exp in expiries:
            y2 = str(exp.year)[2:]
            m3 = exp.strftime('%b').upper()
            for strike in strikes:
                for itype in ('CE','PE'):
                    ts = f"{idx}{y2}{m3}{int(strike)}{itype}"
                    out.append({
                        'instrument_token': token_counter,
                        'tradingsymbol': ts,
                        'name': idx,
                        'expiry': exp,
                        'strike': strike,
                        'segment': 'NFO-OPT',
                        'exchange': 'NFO',
                        'instrument_type': itype,
                        'lot_size': 50,
                        'tick_size': 0.05,
                    })
                    token_counter += 1
    return out


def synth_ltp_for_pairs(pairs: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Return synthetic LTP mapping for exchange:symbol pairs (same heuristics)."""
    data: dict[str, Any] = {}
    for exch, ts in pairs:
        if 'NIFTY 50' in ts:
            price = 24800
        elif 'NIFTY BANK' in ts:
            price = 54000
        elif 'NIFTY FIN SERVICE' in ts:
            price = 26000
        elif 'MIDCAP' in ts:
            price = 12000
        elif 'SENSEX' in ts:
            price = 81000
        else:
            price = 1000
        data[f"{exch}:{ts}"] = {'last_price': price}
    return data


def build_synthetic_quotes(ltp_map: dict[str, Any]) -> dict[str, Any]:
    """Given an LTP map (like synth_ltp_for_pairs), fabricate quote-like payloads.

    Adds deterministic OHLC + synthetic volume/oi/average_price fields (copied from legacy logic).
    """
    quotes: dict[str, Any] = {}
    for key, payload in ltp_map.items():
        lp = payload.get('last_price', 0)
        high = round(lp * 1.01, 2) if lp else 0
        low = round(lp * 0.99, 2) if lp else 0
        open_p = round((high + low) / 2, 2) if lp else 0
        close = lp
        base = int(lp // 10) if lp else 0
        volume = max(1, base * 3 + 100) if lp else 0
        oi = volume * 5 if volume else 0
        avg_price = round((high + low + 2 * close) / 4, 2) if lp else 0
        quotes[key] = {
            'last_price': lp,
            'volume': volume,
            'oi': oi,
            'average_price': avg_price,
            'ohlc': {
                'open': open_p,
                'high': high,
                'low': low,
                'close': close,
            },
            'synthetic': True,
        }
    return quotes

__all__ = [
    'generate_synthetic_instruments',
    'synth_ltp_for_pairs',
    'build_synthetic_quotes',
]
