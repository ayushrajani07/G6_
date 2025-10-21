"""Market status widget placeholder.
Provides simplified open/close state plus next session countdown.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from src.utils.market_hours import get_next_market_open, is_market_open

from .color import FG_GREEN, FG_RED, FG_YELLOW, colorize


@dataclass
class MarketStatus:
    is_open: bool
    next_open_utc: datetime.datetime | None
    seconds_to_open: int | None

    def render_line(self) -> str:
        if self.is_open:
            return colorize("MARKET: OPEN", FG_GREEN, bold=True)
        if not self.next_open_utc:
            return colorize("MARKET: CLOSED", FG_RED, bold=True)
        mins = int((self.seconds_to_open or 0) / 60)
        return colorize(f"MARKET: CLOSED ({mins}m to open)", FG_YELLOW, bold=True)

def snapshot() -> MarketStatus:
    open_now = is_market_open()
    nxt = None
    secs = None
    if not open_now:
        try:
            nxt = get_next_market_open()
            secs = int((nxt - datetime.datetime.now(datetime.UTC)).total_seconds())
        except Exception:
            nxt = None
            secs = None
    return MarketStatus(is_open=open_now, next_open_utc=nxt, seconds_to_open=secs)

__all__ = ["snapshot", "MarketStatus"]
