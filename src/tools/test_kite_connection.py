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
from typing import List
from dotenv import load_dotenv

from src.broker.kite_provider import KiteProvider
from typing import Dict, Any, cast

logger = logging.getLogger("kite-test")


def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_expiry(kite_provider: KiteProvider) -> List[str]:
    try:
        expiries = kite_provider.get_expiry_dates("NIFTY")  # type: ignore[attr-defined]
        if isinstance(expiries, list) and expiries:
            return expiries
    except Exception as e:
        logger.warning(f"Error fetching expiries: {e}")
    return []


def main():
    setup_logging()
    load_dotenv()
    try:
        kite_provider = KiteProvider.from_env()
    except Exception as e:
        logger.error(f"Failed to init KiteProvider: {e}")
        return 1

    expiry_dates = get_expiry(kite_provider)
    if not expiry_dates:
        logger.error("No expiry dates retrieved")
        return 1

    # Determine ATM
    try:
        quotes = kite_provider.get_quote([("NSE", "NIFTY 50")])  # type: ignore[attr-defined]
        key = next(iter(quotes))
        raw_quote = quotes[key]
        try:
            quote_dict = dict(raw_quote)  # type: ignore[arg-type]
        except Exception:
            quote_dict = {}
        quote_dict_t = cast(Dict[str, Any], quote_dict)
        nifty_price = quote_dict_t.get("last_price", 0)  # type: ignore[index]
    except Exception:
        nifty_price = 24600

    base_strike = round(nifty_price / 50) * 50
    strikes = [base_strike - 100, base_strike - 50, base_strike, base_strike + 50, base_strike + 100]
    logger.info(f"Testing option instruments for NIFTY, {expiry_dates[0]}, strikes {strikes}")

    if hasattr(kite_provider, 'get_option_instruments'):
        try:
            instruments = kite_provider.get_option_instruments("NIFTY", expiry_dates[0], strikes)  # type: ignore[attr-defined]
        except Exception as e:
            logger.error(f"Error retrieving instruments: {e}")
            return 1
        if instruments:
            logger.info(f"✅ Got {len(instruments)} option instruments")
            logger.info(f"Sample: {instruments[0].get('tradingsymbol') if isinstance(instruments, list) else 'n/a'}")
        else:
            logger.warning("No option instruments returned")
    else:
        logger.warning("Provider missing get_option_instruments method")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())