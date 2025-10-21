#!/usr/bin/env python3
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Instrument:
    tradingsymbol: str
    instrument_token: int
    segment: str
    expiry: str | None          # YYYY-MM-DD
    strike: float | None
    instrument_type: str | None # CE/PE/FUT/etc.

@dataclass
class QuoteSnapshot:
    timestamp: datetime            # aligned to :00/:30 IST (stored tz-aware)
    symbol_display: str
    instrument_token: int
    last_price: float
    volume: int | None
    oi: int | None
    oi_open: int | None
    iv: float | None
    net_change: float | None
    day_change: float | None
    average_price: float | None
