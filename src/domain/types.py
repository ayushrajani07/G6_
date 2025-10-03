from __future__ import annotations
from typing import TypedDict, Optional, List

class OptionQuoteDict(TypedDict, total=False):
    symbol: str
    exchange: str
    last_price: float
    volume: int
    oi: int
    timestamp: Optional[str]

class ExpirySnapshotDict(TypedDict):
    index: str
    expiry_rule: str
    expiry_date: str
    atm_strike: float
    option_count: int
    generated_at: str
    options: List[OptionQuoteDict]

class OverviewSnapshotDict(TypedDict, total=False):
    generated_at: str
    total_indices: int
    total_expiries: int
    total_options: int
    put_call_ratio: Optional[float]
    max_pain_strike: Optional[float]

class SerializedSnapshotsDict(TypedDict, total=False):
    generated_at: str
    count: int
    snapshots: List[ExpirySnapshotDict]
    overview: OverviewSnapshotDict | None

__all__ = [
    'OptionQuoteDict',
    'ExpirySnapshotDict',
    'OverviewSnapshotDict',
    'SerializedSnapshotsDict',
]
