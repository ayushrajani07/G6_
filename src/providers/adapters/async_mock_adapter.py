from __future__ import annotations

import asyncio
import math
import time
from datetime import date, timedelta
from typing import Any


class AsyncMockProvider:
    """Lightweight async mock provider for offline/demo mode."""

    def __init__(self):
        self._start = time.time()
        self._bases = {
            'NIFTY': 20000.0,
            'BANKNIFTY': 45000.0,
            'FINNIFTY': 21000.0,
            'SENSEX': 66000.0,
        }

    async def close(self) -> None:  # pragma: no cover - trivial
        return None

    def _ltp_value(self, symbol: str) -> float:
        base = self._bases.get(symbol, 10000.0)
        t = time.time() - self._start
        wave = math.sin(t / 30.0) * base * 0.0015
        return round(base + wave, 2)

    async def get_ltp(self, instruments: list[tuple[str, str]]):
        await asyncio.sleep(0)
        out: dict[str, Any] = {}
        for exch, sym in instruments:
            out[f"{exch}:{sym}"] = {"last_price": self._ltp_value(sym)}
        return out

    async def get_quote(self, instruments: list[tuple[str, str]]):
        await asyncio.sleep(0)
        out: dict[str, Any] = {}
        for exch, sym in instruments:
            # Derive a realistic option premium instead of using index LTP directly.
            # Determine index root (e.g., NIFTY, BANKNIFTY) and use that as base for LTP.
            root = None
            for k in self._bases.keys():
                if sym.startswith(k):
                    root = k
                    break
            base_ltp = self._ltp_value(root or 'NIFTY')
            is_ce = sym.endswith('CE')
            is_pe = sym.endswith('PE')
            # Extract strike as the number immediately preceding CE/PE
            strike_val = None
            try:
                import re
                m = re.search(r"(\d+)(?=(CE|PE)$)", sym)
                if m:
                    strike_val = float(m.group(1))
            except Exception:
                strike_val = None
            # Simple premium model: abs(moneyness) * factor + time value floor
            if strike_val is not None and (is_ce or is_pe):
                # Compute intrinsic values and add a modest time value
                diff = base_ltp - strike_val
                intrinsic = max(0.0, diff) if is_ce else max(0.0, -diff)
                # time value ~ 0.3% of base (smaller), with floor
                time_val = max(5.0, 0.003 * base_ltp)
                premium = intrinsic + time_val
                # Bound premiums conservatively to avoid unrealistic thousands in mocks
                cap_by_base = 0.02 * base_ltp  # 2% of base
                cap_by_strike = 0.2 * strike_val  # 20% of strike
                premium = min(premium, cap_by_base, cap_by_strike)
                last_price = round(max(5.0, premium), 2)
            else:
                # For indices or unparsed, keep base_ltp
                last_price = round(base_ltp, 2)
            volume = 1000 if is_ce else (1200 if is_pe else 500)
            oi = 5000 if is_ce else (6000 if is_pe else 1000)
            out[f"{exch}:{sym}"] = {
                "last_price": last_price,
                "volume": volume,
                "oi": oi,
                "average_price": round(last_price * 0.997, 2),
                "ohlc": {"open": last_price * 0.99, "high": last_price * 1.01, "low": last_price * 0.98, "close": last_price},
                "timestamp": time.time(),
                "depth": {"buy": [], "sell": []},
            }
        return out

    async def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> date:
        await asyncio.sleep(0)
        today = date.today()
        # Next Thursday
        for i in range(1, 8):
            d = today + timedelta(days=i)
            if d.weekday() == 3:
                return d
        return today + timedelta(days=7)

    async def option_instruments(self, index_symbol: str, expiry_date, strikes: list[int]):
        return await self.get_option_instruments(index_symbol, expiry_date, strikes)

    async def get_option_instruments(self, index_symbol: str, expiry_date, strikes: list[int]):
        await asyncio.sleep(0)
        out: list[dict[str, Any]] = []
        for s in strikes:
            out.append({
                "tradingsymbol": f"{index_symbol}{expiry_date.strftime('%d%b%y').upper()}{int(s)}CE",
                "exchange": "NFO",
                "instrument_type": "CE",
                "strike": float(s),
            })
            out.append({
                "tradingsymbol": f"{index_symbol}{expiry_date.strftime('%d%b%y').upper()}{int(s)}PE",
                "exchange": "NFO",
                "instrument_type": "PE",
                "strike": float(s),
            })
        return out


__all__ = ["AsyncMockProvider"]
