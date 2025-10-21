"""DummyKiteProvider (Phase 8 extraction).

Provides a lightweight stand-in for the real Kite provider used in tests,
smoke demos, and fallback scenarios. Relocated from `kite_provider.py` to
reduce monolith size and align with modular layout.

Backwards compatibility: `src.broker.kite_provider` will re-export
DummyKiteProvider so existing imports continue to function.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

# Basic index mapping reused (duplicated minimally to avoid importing heavy provider module)
INDEX_DEFAULTS = {
    "NIFTY": 24800,
    "BANKNIFTY": 54000,
    "FINNIFTY": 26000,
    "MIDCPNIFTY": 12000,
    "SENSEX": 81000,
}

class DummyKiteProvider:  # pragma: no cover - logic exercised indirectly in tests
    """Dummy Kite provider for testing and fallback purposes.

    Implements a minimal subset of the real provider surface:
      - get_instruments(exchange)
      - get_ltp(instruments)
      - get_quote(instruments)
      - get_atm_strike(index_symbol)
      - get_expiry_dates(index_symbol)
      - option_instruments(index_symbol, expiry_date, strikes)
      - get_option_instruments (alias)
      - resolve_expiry (delegation via expiries module)
      - check_health
    """
    def __init__(self) -> None:
        self.current_time = datetime.datetime.now()  # local-ok
        logger.info("DummyKiteProvider initialized")

    def close(self) -> None:
        logger.info("DummyKiteProvider closed")

    # ------------------------------------------------------------------
    # Instrument / option universe
    # ------------------------------------------------------------------
    def get_instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        if exchange == "NFO":
            expiry = datetime.date.today() + datetime.timedelta(days=15)
            base = expiry.strftime('%d%b').upper()
            return [
                {
                    "instrument_token": 1,
                    "exchange_token": "1",
                    "tradingsymbol": f"NIFTY{base}{INDEX_DEFAULTS['NIFTY']}CE",
                    "name": "NIFTY",
                    "last_price": 100,
                    "expiry": expiry,
                    "strike": INDEX_DEFAULTS['NIFTY'],
                    "tick_size": 0.05,
                    "lot_size": 50,
                    "instrument_type": "CE",
                    "segment": "NFO-OPT",
                    "exchange": "NFO",
                },
                {
                    "instrument_token": 2,
                    "exchange_token": "2",
                    "tradingsymbol": f"NIFTY{base}{INDEX_DEFAULTS['NIFTY']}PE",
                    "name": "NIFTY",
                    "last_price": 100,
                    "expiry": expiry,
                    "strike": INDEX_DEFAULTS['NIFTY'],
                    "tick_size": 0.05,
                    "lot_size": 50,
                    "instrument_type": "PE",
                    "segment": "NFO-OPT",
                    "exchange": "NFO",
                },
            ]
        return []

    # ------------------------------------------------------------------
    # LTP / Quotes
    # ------------------------------------------------------------------
    def get_ltp(self, instruments: Iterable[tuple[str, str]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for exch, ts in instruments:
            price = 1000.0
            if "NIFTY 50" in ts:
                price = INDEX_DEFAULTS['NIFTY']
            elif "NIFTY BANK" in ts:
                price = INDEX_DEFAULTS['BANKNIFTY']
            elif "NIFTY FIN SERVICE" in ts:
                price = INDEX_DEFAULTS['FINNIFTY']
            elif "NIFTY MIDCAP SELECT" in ts:
                price = INDEX_DEFAULTS['MIDCPNIFTY']
            elif "SENSEX" in ts:
                price = INDEX_DEFAULTS['SENSEX']
            out[f"{exch}:{ts}"] = {"instrument_token": 1, "last_price": price}
        return out

    def get_quote(self, instruments: Iterable[tuple[str, str]]) -> dict[str, Any]:
        base = self.get_ltp(instruments)
        quotes: dict[str, Any] = {}
        for key, payload in base.items():
            lp = payload.get('last_price', 0.0)
            quotes[key] = {
                'last_price': lp,
                'ohlc': {},
            }
        return quotes

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    def get_atm_strike(self, index_symbol: str) -> int:
        return INDEX_DEFAULTS.get(index_symbol, 20000)

    def get_expiry_dates(self, index_symbol: str) -> list[datetime.date]:
        today = datetime.date.today()
        next_week = today + datetime.timedelta(days=7)
        return [today, next_week]

    def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        strikes_set = {float(s) for s in strikes}
        out: list[dict[str, Any]] = []
        universe = self.get_instruments('NFO')
        for inst in universe:
            if (inst.get('instrument_type') or '') not in ('CE','PE'):
                continue
            if index_symbol not in str(inst.get('tradingsymbol','')):
                continue
            exp_val = inst.get('expiry')
            tgt_iso = expiry_date.strftime('%Y-%m-%d') if hasattr(expiry_date, 'strftime') else str(expiry_date)[:10]
            if exp_val is not None and hasattr(exp_val, 'strftime'):
                try:
                    if exp_val.strftime('%Y-%m-%d') != tgt_iso:
                        continue
                except Exception:
                    continue
            else:
                if str(exp_val)[:10] != tgt_iso:
                    continue
            try:
                sv = float(inst.get('strike') or 0)
            except Exception:
                continue
            if sv not in strikes_set:
                continue
            out.append(inst)
        return out

    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        return self.option_instruments(index_symbol, expiry_date, strikes)

    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> datetime.date:  # pragma: no cover
        try:
            from src.broker.kite.expiries import resolve_expiry_rule
            return resolve_expiry_rule(self, index_symbol, expiry_rule)
        except Exception:
            return datetime.date.today()

    def check_health(self) -> dict[str, Any]:
        pair = ("NSE", "NIFTY 50")
        ltp_resp = self.get_ltp([pair])
        price_ok = False
        for _k, _v in ltp_resp.items():
            if isinstance(_v, dict) and isinstance(_v.get('last_price'), (int, float)) and _v['last_price'] > 0:
                price_ok = True
                break
        return {'status': 'healthy' if price_ok else 'degraded', 'message': 'Dummy provider connected' if price_ok else 'Dummy provider invalid price'}
