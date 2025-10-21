#!/usr/bin/env python3
"""
Debug collector script to force data collection and verify storage.
"""

import datetime
import logging
import sys

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

"""Legacy debug collector retained for reference; no path mutation required.

This script assumes execution via the project root (e.g. `python -m src.src_debug_collector_Version5`).
"""

from src.broker.kite_provider import KiteProvider
from src.collectors.providers_interface import Providers
from src.provider.config import get_provider_config
from src.storage.csv_sink import CsvSink

try:
    from src.error_handling import handle_collector_error, handle_provider_error  # type: ignore
except Exception:  # pragma: no cover
    handle_provider_error = None  # type: ignore
    handle_collector_error = None  # type: ignore

def main():
    """Main debug function."""
    # Load environment variables
    load_dotenv()
    logger.info("Environment variables loaded from .env file")

    # Initialize provider
    try:
        snap = get_provider_config()
        kite_provider = KiteProvider.from_provider_config(snap)
        providers = Providers(primary_provider=kite_provider)
        logger.info("Providers initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize providers: {e}", exc_info=True)
        try:
            if handle_provider_error:
                handle_provider_error(e, component="debug_collector", index_name="ALL", context={"op": "init_providers"})
        except Exception:
            pass
        return 1

    # Initialize storage
    csv_sink = CsvSink(base_dir='data/g6_debug_data')
    logger.info("CSV storage initialized")

    # Get current time
    timestamp = datetime.datetime.now()  # local-ok

    # Test indices
    indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX']

    for index_symbol in indices:
        logger.info(f"===== Testing {index_symbol} =====")

        # Derive ATM strike using Providers.get_ltp (facade method)
        try:
            atm_strike = providers.get_ltp(index_symbol)
            logger.info(f"{index_symbol} derived ATM strike: {atm_strike}")
        except Exception as e:
            logger.error(f"Error deriving ATM strike for {index_symbol}: {e}", exc_info=True)
            try:
                if handle_provider_error:
                    handle_provider_error(e, component="debug_collector", index_name=index_symbol, context={"op": "get_ltp"})
            except Exception:
                pass
            continue

        # Get this week's expiry
        try:
            expiry_date = providers.resolve_expiry(index_symbol, 'this_week')
            logger.info(f"{index_symbol} this_week expiry: {expiry_date}")
        except Exception as e:
            logger.error(f"Error resolving expiry for {index_symbol}: {e}", exc_info=True)
            try:
                if handle_provider_error:
                    handle_provider_error(e, component="debug_collector", index_name=index_symbol, context={"op": "resolve_expiry"})
            except Exception:
                pass
            continue

        # Calculate strikes
        strike_step = 50.0  # Default step
        if index_symbol == 'BANKNIFTY':
            strike_step = 100.0
        elif index_symbol == 'SENSEX':
            strike_step = 100.0

        strikes = []
        # Add 5 ITM strikes
        for i in range(1, 6):
            strikes.append(atm_strike - (i * strike_step))

        # Add ATM strike
        strikes.append(atm_strike)

        # Add 5 OTM strikes
        for i in range(1, 6):
            strikes.append(atm_strike + (i * strike_step))

        # Sort strikes
        strikes.sort()
        logger.info(f"Strikes to check: {strikes}")

        # Get option instruments via provider if available
        try:
            logger.info(f"Fetching option instruments for {index_symbol} with expiry {expiry_date}")
            instruments = None
            if hasattr(providers.primary_provider, 'get_option_instruments'):
                try:
                    instruments = providers.primary_provider.get_option_instruments(index_symbol, expiry_date, strikes)  # type: ignore[attr-defined]
                except Exception as inner_e:
                    logger.error(f"Provider get_option_instruments error: {inner_e}")
                    try:
                        if handle_provider_error:
                            handle_provider_error(inner_e, component="debug_collector", index_name=index_symbol, context={"op": "get_option_instruments"})
                    except Exception:
                        pass
            if instruments:
                logger.info(f"Found {len(instruments)} option instruments")
                logger.info(f"First instrument: {instruments[0]}")
            else:
                logger.warning(f"No instruments found for {index_symbol}")
                continue
        except Exception as e:
            logger.error(f"Error getting option instruments for {index_symbol}: {e}", exc_info=True)
            try:
                if handle_provider_error:
                    handle_provider_error(e, component="debug_collector", index_name=index_symbol, context={"op": "get_option_instruments_outer"})
            except Exception:
                pass
            continue

        # Convert instruments to dictionary
        options_data = {}
        for instrument in instruments:
            symbol = instrument.get('tradingsymbol', '')
            if symbol:
                options_data[symbol] = instrument

        # Try to get quotes
        if options_data:
            try:
                # Format instruments for quote API
                quote_instruments = []
                for symbol in options_data.keys():
                    quote_instruments.append(('NFO', symbol))

                logger.info(f"Getting quotes for {len(quote_instruments)} instruments")
                quotes = providers.get_quote(quote_instruments[:5])  # Just get first 5 for testing

                logger.info(f"Got quotes: {len(quotes)} items")
                if quotes:
                    # Show a sample
                    sample_key = next(iter(quotes))
                    logger.info(f"Sample quote: {sample_key} = {quotes[sample_key]}")

                # Update options data with quotes
                for exchange, symbol in quote_instruments[:5]:
                    key = f"{exchange}:{symbol}"
                    if key in quotes:
                        quote_data = quotes[key]
                        if symbol in options_data:
                            for field in ['last_price', 'volume', 'oi', 'depth']:
                                if field in quote_data:
                                    options_data[symbol][field] = quote_data[field]
            except Exception as e:
                logger.error(f"Error getting quotes: {e}", exc_info=True)
                try:
                    if handle_provider_error:
                        handle_provider_error(e, component="debug_collector", index_name=index_symbol, context={"op": "get_quote_options"})
                except Exception:
                    pass

        # Write to CSV
        try:
            logger.info(f"Writing {len(options_data)} records to CSV")
            csv_sink.write_options_data(index_symbol, expiry_date, options_data, timestamp)
            logger.info(f"Data written for {index_symbol}")
        except Exception as e:
            logger.error(f"Error writing data to CSV: {e}", exc_info=True)
            try:
                if handle_collector_error:
                    handle_collector_error(e, component="debug_collector", index_name=index_symbol, context={"op": "csv_write"})
            except Exception:
                pass

    logger.info("Debug collection completed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
