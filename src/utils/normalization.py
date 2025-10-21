#!/usr/bin/env python3
"""Shared normalization helpers for option records.

Functions here are intentionally dependency-light to allow usage from
providers, collectors, and sinks without circular imports.
"""
from __future__ import annotations

import datetime as _dt
import os as _os
from typing import Any

try:
    from src.collectors.env_adapter import get_bool as _env_get_bool
    from src.collectors.env_adapter import get_float as _env_get_float  # type: ignore
except Exception:  # pragma: no cover
    def _env_get_float(name: str, default: float) -> float:
        try:
            v = _os.environ.get(name)
            if v is None or str(v).strip() == "":
                return default
            return float(str(v).strip())
        except Exception:
            return default
    # Match signature of env_adapter.get_bool which provides a default value for 'default'
    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = _os.environ.get(name)
            if v is None:
                return default
            return str(v).strip().lower() not in ('0','false','no','off')
        except Exception:
            return default


def _env_flag(name: str, default: bool) -> bool:
    # Preserve legacy truthy semantics
    return _env_get_bool(name, default)


def normalize_price(
    raw: Any,
    *,
    strike: float | None = None,
    index_price: float | None = None,
    oi: float | None = None,
    paise_threshold: float = _env_get_float('G6_PRICE_PAISE_THRESHOLD', 10000.0),
    max_strike_frac: float = _env_get_float('G6_PRICE_MAX_STRIKE_FRAC', 0.35),
    max_index_frac: float = _env_get_float('G6_PRICE_MAX_INDEX_FRAC', 0.5),
    enabled: bool = _env_flag('G6_CSV_PRICE_SANITY', True),
) -> float:
    """Return a sanitized price value.

    - Drop <= 0
    - If equals OI within 2% and large, treat as wrong field -> 0.0
    - If paise-coded (very large), divide by 100 when plausible w.r.t strike/index
    - Clamp to configured fractions of strike/index
    """
    try:
        if not enabled:
            return round(float(raw or 0.0), 2)
        p = float(raw or 0.0)
        if p <= 0:
            return 0.0
        try:
            if oi is not None:
                _oi = float(oi)
                if _oi > 500 and abs(p - _oi) / max(_oi, 1.0) < 0.02:
                    return 0.0
        except Exception:
            pass
        # Paise-coded?
        try:
            if p >= paise_threshold:
                cand = p / 100.0
                s = float(strike or 0.0)
                ix = float(index_price or 0.0)
                if (s and cand <= max(max_strike_frac * s, 2000.0)) or (ix and cand <= max_index_frac * ix):
                    p = cand
        except Exception:
            pass
        try:
            s = float(strike or 0.0)
            if s and p > max_strike_frac * s:
                return 0.0
        except Exception:
            pass
        try:
            ix = float(index_price or 0.0)
            if ix and p > max_index_frac * ix:
                return 0.0
        except Exception:
            pass
        return round(p, 2)
    except Exception:
        return 0.0


def sanitize_option_fields(record: dict[str, Any], *, index_price: float | None = None) -> dict[str, Any]:
    """Return a copy of record with sanitized core fields.

    - Coerce numeric types (last_price, avg_price, volume, oi)
    - Apply normalize_price to last_price and avg_price
    """
    r = dict(record or {})
    strike = None
    try:
        strike = float(r.get('strike') or r.get('strike_price') or 0.0)
    except Exception:
        strike = None
    # Coerce OI/volume
    try:
        if 'oi' in r and r['oi'] is not None:
            r['oi'] = int(r['oi'])
    except Exception:
        pass
    try:
        if 'volume' in r and r['volume'] is not None:
            r['volume'] = int(r['volume'])
    except Exception:
        pass
    # Prices
    try:
        oi_val = r.get('oi')
        r['last_price'] = normalize_price(r.get('last_price'), strike=strike, index_price=index_price, oi=oi_val)
    except Exception:
        r['last_price'] = 0.0
    try:
        r['avg_price'] = normalize_price(r.get('avg_price'), strike=strike, index_price=index_price)
    except Exception:
        r['avg_price'] = 0.0
    return r


def coerce_expiry(val: Any) -> _dt.date:
    """Coerce value into a date.

    Accepts date, datetime, ISO string (YYYY-MM-DD), or DD-MM-YYYY.
    """
    if isinstance(val, _dt.date) and not isinstance(val, _dt.datetime):
        return val
    if isinstance(val, _dt.datetime):
        return val.date()
    s = str(val).strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except Exception:
            pass
    # Fallback: today to avoid crashes (caller should log)
    return _dt.date.today()


__all__ = [
    'normalize_price',
    'sanitize_option_fields',
    'coerce_expiry',
]
