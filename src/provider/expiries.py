"""Expiry resolver placeholder (Phase 4 A7).

Future responsibilities:
- Extract expiries from instrument universe
- Fabricate synthetic expiries under defined conditions
- Rule resolution (delegating to existing expiries logic initially)

Current stub supplies empty lists to avoid implying completeness.
"""
from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Callable, Iterable
from typing import Any

from .logging_events import emit_event

logger = logging.getLogger(__name__)

class ExpiryResolver:
    def __init__(self) -> None:
        self._cache: dict[str, list[_dt.date]] = {}
        self._cache_meta: dict[str, float] = {}
        self._last_log_ts: float = 0.0

    def _allow_log(self, interval: float = 5.0) -> bool:
        import time
        now = time.time()
        if (now - self._last_log_ts) > interval:
            self._last_log_ts = now
            return True
        return False

    def list_expiries(self, index_symbol: str) -> list[_dt.date]:
        return list(self._cache.get(index_symbol, []))

    # --- core extraction logic (Phase 4 A16) ------------------------------
    def extract(
        self,
        index_symbol: str,
        instruments: Iterable[dict[str, Any]],
        atm_strike: int | float | None = None,
        strike_window: float = 500,
        today: _dt.date | None = None,
    ) -> list[_dt.date]:
        today = today or _dt.date.today()
        out: set[_dt.date] = set()
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            seg = str(inst.get("segment", ""))
            if not seg.endswith("-OPT"):
                continue
            tsym = str(inst.get("tradingsymbol", ""))
            if index_symbol not in tsym:
                continue
            if atm_strike is not None:
                try:
                    diff = abs(float(inst.get("strike", 0) or 0) - float(atm_strike))
                    if diff > strike_window:
                        continue
                except Exception:
                    continue
            exp = inst.get("expiry")
            if isinstance(exp, _dt.date):
                if exp >= today:
                    out.add(exp)
            elif isinstance(exp, str):
                try:
                    dtp = _dt.datetime.strptime(exp[:10], "%Y-%m-%d").date()
                    if dtp >= today:
                        out.add(dtp)
                except Exception:
                    pass
        return sorted(out)

    def fabricate(self, today: _dt.date | None = None) -> list[_dt.date]:
        today = today or _dt.date.today()
        days_until_thu = (3 - today.weekday()) % 7
        if days_until_thu == 0:
            days_until_thu = 7
        this_week = today + _dt.timedelta(days=days_until_thu)
        next_week = this_week + _dt.timedelta(days=7)
        return [this_week, next_week]

    def resolve(
        self,
        index_symbol: str,
        fetch_instruments: Callable[[], list[dict[str, Any]]],
        atm_provider: Callable[[str], int],
        ttl: float = 600.0,
        now_func: Callable[[], float] | None = None,
    ) -> list[_dt.date]:
        import time
        now = (now_func or time.time)()
        # Derive a deterministic 'today' from the provided clock when available
        try:
            today_dt = _dt.datetime.utcfromtimestamp(float(now)).date()
        except Exception:
            today_dt = _dt.date.today()
        cached = self._cache.get(index_symbol)
        meta = self._cache_meta.get(index_symbol, 0.0)
        if cached and (now - meta) < ttl:
            return list(cached)
        # fetch instruments
        instruments = fetch_instruments()
        atm = None
        try:
            atm = atm_provider(index_symbol)
        except Exception:
            atm = None
        extracted = self.extract(index_symbol, instruments, atm_strike=atm, today=today_dt)
        if not extracted:
            if instruments:
                fabricated = self.fabricate(today=today_dt)
                if self._allow_log():
                    logger.debug("expiry.fabricated index=%s this_week=%s next_week=%s", index_symbol, fabricated[0], fabricated[1])
                emit_event(logger, "provider.expiries.fabricated", index=index_symbol, count=len(fabricated))
                extracted = fabricated
            else:
                if self._allow_log():
                    logger.warning("expiry.no_instruments index=%s", index_symbol)
        self._cache[index_symbol] = extracted
        self._cache_meta[index_symbol] = now
        return list(extracted)

    def fabricate_if_needed(self, index_symbol: str) -> list[_dt.date]:
        # Later: replicate fabrication heuristic from legacy provider
        return self.list_expiries(index_symbol)

    def weekly(self, index_symbol: str) -> list[_dt.date]:
        expiries = self.list_expiries(index_symbol)
        return expiries[:2]

    def monthly(self, index_symbol: str) -> list[_dt.date]:
        expiries = self.list_expiries(index_symbol)
        by_month: dict[tuple[int,int], list[_dt.date]] = {}
        for d in expiries:
            by_month.setdefault((d.year, d.month), []).append(d)
        out: list[_dt.date] = []
        for _, vals in sorted(by_month.items()):
            out.append(max(vals))
        return out
