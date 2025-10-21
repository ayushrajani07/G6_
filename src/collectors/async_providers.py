from __future__ import annotations

import logging
from typing import Any

from src.error_handling import handle_data_collection_error, handle_provider_error
from src.utils.normalization import sanitize_option_fields

logger = logging.getLogger(__name__)


class AsyncProviders:
    """Async facade for providers, mirroring the sync Providers API surface."""

    def __init__(self, primary_provider):
        self.primary_provider = primary_provider

    async def close(self):  # pragma: no cover - trivial
        try:
            await self.primary_provider.close()
        except Exception:
            pass

    async def get_index_data(self, index_symbol: str):
        # Map index symbol to exchange:symbol tuple used by provider
        if index_symbol == "NIFTY":
            instruments = [("NSE", "NIFTY 50")]
        elif index_symbol == "BANKNIFTY":
            instruments = [("NSE", "NIFTY BANK")]
        elif index_symbol == "FINNIFTY":
            instruments = [("NSE", "NIFTY FIN SERVICE")]
        elif index_symbol == "MIDCPNIFTY":
            instruments = [("NSE", "NIFTY MIDCAP SELECT")]
        elif index_symbol == "SENSEX":
            instruments = [("BSE", "SENSEX")]
        else:
            instruments = [("NSE", index_symbol)]

        # Try quote first
        try:
            quotes = await self.primary_provider.get_quote(instruments)
            for _, q in quotes.items():
                return q.get('last_price', 0), q.get('ohlc', {})
        except Exception as e:
            handle_provider_error(e, component="collectors.async_providers", index_name=index_symbol)
            logger.debug(f"async get_quote failed, fallback to LTP: {e}")

        # Fallback to LTP
        try:
            ltp_map = await self.primary_provider.get_ltp(instruments)
            for _, d in ltp_map.items():
                return d.get('last_price', 0), {}
        except Exception as e:
            handle_provider_error(e, component="collectors.async_providers", index_name=index_symbol)
            logger.error(f"async get_ltp fallback failed: {e}")
        return 0, {}

    async def get_ltp(self, index_symbol: str):
        price, _ = await self.get_index_data(index_symbol)
        if index_symbol in ("BANKNIFTY", "SENSEX"):
            return round(float(price) / 100) * 100
        return round(float(price) / 50) * 50

    async def resolve_expiry(self, index_symbol: str, expiry_rule: str):
        return await self.primary_provider.resolve_expiry(index_symbol, expiry_rule)

    async def get_option_instruments(self, index_symbol: str, expiry_date, strikes: list[int]):
        if hasattr(self.primary_provider, 'get_option_instruments'):
            return await self.primary_provider.get_option_instruments(index_symbol, expiry_date, strikes)
        return await self.primary_provider.option_instruments(index_symbol, expiry_date, strikes)

    async def enrich_with_quotes(self, instruments: list[dict[str, Any]]):
        # Convert instruments to quote format and fanout
        quote_instruments: list[tuple[str, str]] = []
        for inst in instruments:
            symbol = inst.get('tradingsymbol', '')
            exchange = inst.get('exchange', 'NFO')
            if symbol:
                quote_instruments.append((exchange, symbol))
        if not quote_instruments:
            return {}
        quotes = await self.primary_provider.get_quote(quote_instruments)
        enriched: dict[str, Any] = {}
        for inst in instruments:
            symbol = inst.get('tradingsymbol', '')
            exchange = inst.get('exchange', 'NFO')
            key = f"{exchange}:{symbol}"
            data = inst.copy()
            q = quotes.get(key) if quotes else None
            if q:
                data['last_price'] = q.get('last_price', 0)
                data['volume'] = q.get('volume', 0)
                data['oi'] = q.get('oi', 0)
                data['avg_price'] = q.get('average_price', 0)
                data['avg_price_fallback_used'] = False
                if (not data['avg_price'] or data['avg_price'] == 0) and 'ohlc' in q:
                    o = q.get('ohlc', {}) or {}
                    try:
                        h = float(o.get('high') or 0); l = float(o.get('low') or 0); last_p = float(q.get('last_price') or 0)
                        if h > 0 and l > 0:
                            if last_p > 0:
                                ap = (h + l + 2 * last_p) / 4.0
                            else:
                                ap = (h + l) / 2.0
                            if ap > 0:
                                data['avg_price'] = ap
                                data['avg_price_fallback_used'] = True
                    except Exception as e:
                        handle_data_collection_error(e, component="collectors.async_providers", index_name=inst.get('index',''), data_type='avg_price_fallback')
                        pass
            # Sanitize before returning (consistent with sync path)
            try:
                data = sanitize_option_fields(data)
            except Exception:
                pass
            enriched[symbol] = data
        return enriched


__all__ = ["AsyncProviders"]
