"""Typed protocol & structural helper types for Kite provider (Wave 1 Type Safety).

These types are intentionally minimal; we prefer narrow optional total=False
TypedDicts so adding fields later is non-breaking.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from typing import NotRequired, Protocol, TypedDict


class InstrumentTD(TypedDict, total=False):
    tradingsymbol: str
    exchange: str
    instrument_type: str
    segment: NotRequired[str]
    strike: NotRequired[float]
    expiry: NotRequired[_dt.date | str]
    name: NotRequired[str]
    underlying: NotRequired[str]

class QuoteOhlcTD(TypedDict, total=False):
    open: NotRequired[float]
    high: NotRequired[float]
    low: NotRequired[float]
    close: NotRequired[float]

class QuoteTD(TypedDict, total=False):
    last_price: float
    volume: NotRequired[int]
    oi: NotRequired[int]
    average_price: NotRequired[float]
    ohlc: NotRequired[QuoteOhlcTD]

class OptionInstrumentTD(TypedDict, total=False):
    tradingsymbol: NotRequired[str]
    instrument_type: NotRequired[str]  # 'CE' or 'PE'
    name: NotRequired[str]
    underlying: NotRequired[str]
    expiry: NotRequired[_dt.date | str]
    strike: NotRequired[float]
    lot_size: NotRequired[int]
    exchange: NotRequired[str]
    tick_size: NotRequired[float]
    segment: NotRequired[str]
    exchange_token: NotRequired[str]
    last_price: NotRequired[float]

class OptionMatchResultProto(Protocol):  # minimal protocol from options.match_options
    instruments: Sequence[InstrumentTD]
    reject_counts: Mapping[str, int]
    contamination_list: Sequence[str]
    match_mode: str

__all__ = [
    "InstrumentTD",
    "QuoteTD",
    "QuoteOhlcTD",
    "OptionInstrumentTD",
    "OptionMatchResultProto",
]
