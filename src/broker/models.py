#!/usr/bin/env python3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Instrument:
    tradingsymbol: str
    instrument_token: int
    segment: str
    expiry: Optional[str]          # YYYY-MM-DD
    strike: Optional[float]
    instrument_type: Optional[str] # CE/PE/FUT/etc.

@dataclass
class QuoteSnapshot:
    timestamp: datetime            # aligned to :00/:30 IST (stored tz-aware)
    symbol_display: str
    instrument_token: int
    last_price: float
    volume: Optional[int]
    oi: Optional[int]
    oi_open: Optional[int]
    iv: Optional[float]
    net_change: Optional[float]
    day_change: Optional[float]
    average_price: Optional[float]