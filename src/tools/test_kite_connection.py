"""Kite connection diagnostic script.

Run: python -m src.tools.test_kite_connection

Checks:
1. Load environment (.env)
2. Instantiate KiteProvider
3. Fetch NIFTY expiries
4. Pull option instruments around ATM strikes
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from dotenv import load_dotenv

from src.broker.kite_provider import KiteProvider
from src.provider.config import get_provider_config

if TYPE_CHECKING:
    # For type checking only; at runtime we'll attempt a guarded import
    HandleApiFn = Callable[..., Any]
    HandleProviderFn = Callable[..., Any]
else:
    HandleApiFn = Callable[..., Any]
    HandleProviderFn = Callable[..., Any]

handle_api_error: HandleApiFn | None
handle_provider_error: HandleProviderFn | None
try:
    from src.error_handling import handle_api_error as _rt_handle_api_error
    from src.error_handling import handle_provider_error as _rt_handle_provider_error
    handle_api_error = _rt_handle_api_error  # runtime assignment (types align via Callable[..., Any])
    handle_provider_error = _rt_handle_provider_error
except Exception:  # pragma: no cover
    handle_api_error = None
    handle_provider_error = None

logger = logging.getLogger("kite-test")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_expiry(kite_provider: KiteProvider) -> list[str]:
    """Return list of expiries for NIFTY or [] on failure.

    Uses getattr to avoid attr-defined ignores if provider surface differs.
    """
    try:
        getter: Any = getattr(kite_provider, "get_expiry_dates", None)
        if callable(getter):
            expiries = getter("NIFTY")
        else:
            return []
        if isinstance(expiries, list) and expiries:
            return expiries
    except Exception as e:
        logger.warning(f"Error fetching expiries: {e}")
        try:
            if handle_provider_error is not None:
                handle_provider_error(e, component="tools.test_kite_connection", index_name="NIFTY", context={"op": "get_expiry"})
        except Exception:
            pass
    return []


def main() -> int:
    setup_logging()
    load_dotenv()
    try:
        snap = get_provider_config()
        kite_provider = KiteProvider.from_provider_config(snap)
    except Exception as e:
        logger.error(f"Failed to init KiteProvider: {e}")
        try:
            if handle_api_error is not None:
                handle_api_error(e, component="tools.test_kite_connection", context={"op": "init_provider"})
        except Exception:
            pass
        return 1

    expiry_dates = get_expiry(kite_provider)
    if not expiry_dates:
        logger.error("No expiry dates retrieved")
        return 1

    # Determine ATM
    try:
        get_quote = getattr(kite_provider, "get_quote", None)
        quotes: Any = get_quote([("NSE", "NIFTY 50")]) if callable(get_quote) else None
        nifty_price = 0
        if isinstance(quotes, dict) and quotes:
            key = next(iter(quotes))
            raw_quote = quotes.get(key)
            if isinstance(raw_quote, dict):
                nifty_price = cast(Any, raw_quote).get("last_price", 0)  # last_price typical key
            else:
                try:
                    # Attempt mapping conversion if iterable of pairs
                    if hasattr(raw_quote, 'items'):
                        from collections.abc import Mapping
                        rq_map = cast(Mapping[str, Any], raw_quote)
                        quote_dict = dict(rq_map.items())
                        # quote_dict is already a Dict[str, Any]; cast redundant
                        nifty_price = quote_dict.get("last_price", 0)
                except Exception:
                    pass
    except Exception as e:
        nifty_price = 24600
        try:
            if handle_provider_error is not None:
                handle_provider_error(e, component="tools.test_kite_connection", index_name="NIFTY", context={"op": "get_quote"})
        except Exception:
            pass

    base_strike = round(nifty_price / 50) * 50
    strikes = [base_strike - 100, base_strike - 50, base_strike, base_strike + 50, base_strike + 100]
    logger.info(f"Testing option instruments for NIFTY, {expiry_dates[0]}, strikes {strikes}")

    get_opts = getattr(kite_provider, 'get_option_instruments', None)
    if callable(get_opts):
        try:
            instruments = get_opts("NIFTY", expiry_dates[0], strikes)
        except Exception as e:
            logger.error(f"Error retrieving instruments: {e}")
            try:
                if handle_provider_error is not None:
                    handle_provider_error(e, component="tools.test_kite_connection", index_name="NIFTY", context={"op": "get_option_instruments"})
            except Exception:
                pass
            return 1
        if instruments:
            if isinstance(instruments, list):
                logger.info(f"✅ Got {len(instruments)} option instruments")
                sample = instruments[0].get('tradingsymbol') if instruments and isinstance(instruments[0], dict) else 'n/a'
            else:
                logger.info("✅ Got option instruments (non-list container)")
                sample = 'n/a'
            logger.info(f"Sample: {sample}")
        else:
            logger.warning("No option instruments returned")
    else:
        logger.warning("Provider missing get_option_instruments method")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
