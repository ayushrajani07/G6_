#!/usr/bin/env python3
"""
Test script to validate expiry date extraction from Kite API.
"""

import logging
import sys

try:  # Optional dependency
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        print("[test_expiries] Warning: python-dotenv not installed; skipping .env load")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Main test function."""
    load_dotenv()
    logger.info("===== TESTING KITE PROVIDER EXPIRY EXTRACTION =====")

    from src.broker.kite_provider import KiteProvider
    from src.provider.config import get_provider_config

    # Initialize provider
    kite_provider = KiteProvider.from_provider_config(get_provider_config())
    logger.info("KiteProvider initialized")

    # Test indices
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

    for index in indices:
        logger.info(f"\nTesting {index}:")

        # Get expiry dates
        expiry_dates = kite_provider.get_expiry_dates(index)
        logger.info(f"{index} expiry dates: {expiry_dates}")

        if expiry_dates:
            # Test resolving expiry rules
            this_week = kite_provider.resolve_expiry(index, "this_week")
            next_week = kite_provider.resolve_expiry(index, "next_week")

            logger.info(f"{index} this_week expiry: {this_week}")
            logger.info(f"{index} next_week expiry: {next_week}")

            # Test getting option instruments for first expiry
            expiry = expiry_dates[0]
            atm = 24850 if index == "NIFTY" else 52500 if index == "BANKNIFTY" else 24000
            strikes = [atm-100, atm, atm+100]

            logger.info(f"Getting option instruments for {index} expiry {expiry} strikes {strikes}")

            instruments = kite_provider.option_instruments(index, expiry, strikes)
            logger.info(f"Found {len(instruments)} option instruments")

            if instruments:
                logger.info(f"Sample instrument: {instruments[0]}")
        else:
            logger.warning(f"No expiry dates found for {index}")

    logger.info("\n===== TEST COMPLETED =====")
    return 0

if __name__ == "__main__":
    sys.exit(main())
