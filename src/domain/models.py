"""Domain model dataclasses for structured option chain processing.

Env flag G6_DOMAIN_MODELS enables optional mapping from raw provider quote dicts
into strongly typed dataclasses that can later support validation and richer
analytics without mutating original collector logic.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

ISO8601_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
]

def _parse_ts(ts: str) -> dt.datetime | None:
    if not ts:
        return None
    for fmt in ISO8601_FORMATS:
        try:
            return dt.datetime.strptime(ts, fmt)
        except Exception:
            continue
    # Fallback: fromisoformat (Python 3.11+ tolerant)
    try:
        if ts.endswith("Z"):
            return dt.datetime.fromisoformat(ts[:-1] + "+00:00")
        return dt.datetime.fromisoformat(ts)
    except Exception:
        return None

@dataclass(slots=True)
class OptionQuote:
    symbol: str
    exchange: str
    last_price: float
    volume: int = 0
    oi: int = 0
    timestamp: dt.datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, key: str, data: dict[str, Any]) -> OptionQuote:
        # key form: EXCHANGE:TRADINGSYMBOL
        exchange, symbol = ("NSE", key)
        if ":" in key:
            parts = key.split(":", 1)
            exchange, symbol = parts[0] or "NSE", parts[1]
        ts = data.get("timestamp") or data.get("ts")
        return cls(
            symbol=symbol,
            exchange=exchange,
            last_price=float(data.get("last_price") or data.get("ltp") or 0.0),
            volume=int(data.get("volume", 0) or 0),
            oi=int(data.get("oi", 0) or 0),
            timestamp=_parse_ts(ts) if isinstance(ts, str) else None,
            raw=data,
        )

    def as_dict(self) -> dict[str, Any]:  # OptionQuoteDict at runtime
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "last_price": self.last_price,
            "volume": self.volume,
            "oi": self.oi,
            "timestamp": self.timestamp.isoformat() + "Z" if self.timestamp else None,
        }

@dataclass(slots=True)
class EnrichedOption(OptionQuote):
    iv: float | None = None  # percentage (e.g. 25.4)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    @classmethod
    def from_quote(cls, q: OptionQuote, enriched: dict[str, Any]) -> EnrichedOption:
        return cls(
            symbol=q.symbol,
            exchange=q.exchange,
            last_price=q.last_price,
            volume=q.volume,
            oi=q.oi,
            timestamp=q.timestamp,
            raw=q.raw,
            iv=enriched.get("iv"),
            delta=enriched.get("delta"),
            gamma=enriched.get("gamma"),
            theta=enriched.get("theta"),
            vega=enriched.get("vega"),
        )

@dataclass(slots=True)
class ExpirySnapshot:
    index: str
    expiry_rule: str
    expiry_date: dt.date
    atm_strike: float
    options: list[OptionQuote]
    generated_at: dt.datetime

    @property
    def option_count(self) -> int:
        return len(self.options)

    def as_dict(self) -> dict[str, Any]:  # ExpirySnapshotDict at runtime
        return {
            "index": self.index,
            "expiry_rule": self.expiry_rule,
            "expiry_date": self.expiry_date.isoformat(),
            "atm_strike": self.atm_strike,
            "option_count": self.option_count,
            "generated_at": self.generated_at.isoformat() + "Z",
            "options": [o.as_dict() for o in self.options],
        }

__all__ = [
    "OptionQuote",
    "EnrichedOption",
    "ExpirySnapshot",
]

@dataclass(slots=True)
class OverviewSnapshot:
    generated_at: dt.datetime
    total_indices: int
    total_expiries: int
    total_options: int
    put_call_ratio: float | None
    max_pain_strike: float | None

    @classmethod
    def from_expiry_snapshots(cls, snaps: Iterable[ExpirySnapshot]) -> OverviewSnapshot:  # type: ignore[name-defined]
        snaps_list = list(snaps)
        total_indices = len({s.index for s in snaps_list})
        total_expiries = len(snaps_list)
        total_options = sum(s.option_count for s in snaps_list)
        # crude PCR: count options whose symbol contains CE / PE by last char tokens
        calls = 0
        puts = 0
        for s in snaps_list:
            for o in s.options:
                sym = o.symbol.upper()
                if sym.endswith('CE') or 'CE' in sym:
                    calls += 1
                elif sym.endswith('PE') or 'PE' in sym:
                    puts += 1
        pcr = None
        if calls > 0:
            pcr = puts / calls if calls else None
        # placeholder max pain: choose ATM strike avg across snapshots (future real calc uses OI aggregation)
        strikes = [s.atm_strike for s in snaps_list if s.atm_strike]
        max_pain = sum(strikes) / len(strikes) if strikes else None
        return cls(
            generated_at=dt.datetime.now(dt.UTC),
            total_indices=total_indices,
            total_expiries=total_expiries,
            total_options=total_options,
            put_call_ratio=pcr,
            max_pain_strike=max_pain,
        )

    def as_dict(self) -> dict[str, Any]:  # OverviewSnapshotDict at runtime
        return {
            "generated_at": self.generated_at.isoformat().replace('+00:00','Z'),
            "total_indices": self.total_indices,
            "total_expiries": self.total_expiries,
            "total_options": self.total_options,
            "put_call_ratio": self.put_call_ratio,
            "max_pain_strike": self.max_pain_strike,
        }

__all__.append("OverviewSnapshot")
