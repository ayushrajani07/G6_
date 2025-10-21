#!/usr/bin/env python3
"""
Test script to validate data collection for all supported indices.
"""

import datetime
import logging
import os
import sys
from typing import Any

try:  # Optional dependency
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        print("[test_all_indices] Warning: python-dotenv not installed; skipping .env load")
from src.utils.logging_utils import setup_logging
from src.utils.path_utils import data_subdir, ensure_sys_path

ensure_sys_path()

setup_logging(level="INFO", log_file="logs/test_all_indices.log")
logger = logging.getLogger("g6.test_all_indices")

def main():
    """Main test function."""
    load_dotenv()
    logger.info("\033[1;32m===== TESTING ALL INDICES =====\033[0m")

    from src.broker.kite_provider import KiteProvider
    from src.provider.config import get_provider_config
    from src.storage.csv_sink import CsvSink

    # Initialize provider and storage
    kite_provider = KiteProvider.from_provider_config(get_provider_config())
    csv_dir = data_subdir('g6_indices_test')
    csv_sink = CsvSink(base_dir=csv_dir)

    # Test all supported indices
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]

    for index in indices:
        logger.info(f"\033[1;33m\n{'=' * 30} TESTING {index} {'=' * 30}\033[0m")

        try:
            # Get ATM strike
            atm_strike = kite_provider.get_atm_strike(index)

            # Get expiry dates
            expiry_dates = kite_provider.get_expiry_dates(index)

            if not expiry_dates:
                logger.warning(f"No expiry dates found for {index}")
                continue

            # Take first expiry
            expiry = expiry_dates[0]

            # Calculate strikes to collect (5 ITM, ATM, 5 OTM)
            strikes = []
            step = 100 if index == "BANKNIFTY" or index == "SENSEX" else 50

            for i in range(-5, 6):
                strikes.append(atm_strike + (i * step))

            # Get option instruments
            instruments = kite_provider.option_instruments(index, expiry, strikes)

            if not instruments:
                logger.warning(f"No option instruments found for {index}")
                continue

            def normalize(inst: Any) -> dict[str, Any] | None:
                if inst is None:
                    return None
                if isinstance(inst, dict):
                    return inst.copy()
                if hasattr(inst, '_asdict'):
                    try:
                        return dict(inst._asdict())  # type: ignore
                    except Exception:
                        pass
                if hasattr(inst, '__dict__') and isinstance(inst.__dict__, dict):
                    return dict(inst.__dict__)
                fields = [
                    'instrument_token','exchange_token','tradingsymbol','name','last_price','expiry','strike',
                    'tick_size','lot_size','instrument_type','segment','exchange'
                ]
                extracted = {f: getattr(inst, f) for f in fields if hasattr(inst, f)}
                return extracted if extracted else None

            options_data: dict[str, dict[str, Any]] = {}
            skipped = 0
            for instrument in instruments:
                norm = normalize(instrument)
                if not norm:
                    skipped += 1
                    continue
                symbol = norm.get('tradingsymbol') or norm.get('symbol')
                if not symbol:
                    skipped += 1
                    continue
                options_data[symbol] = norm
            if skipped:
                logger.debug(f"Skipped {skipped} instruments during normalization for {index}")

            # Get quotes for first 5 instruments (limit API requests)
            if options_data:
                sample_instruments = list(options_data.keys())[:5]
                quote_instruments = [('NFO', symbol) for symbol in sample_instruments]

                logger.info(f"Getting quotes for {len(quote_instruments)} sample instruments")
                quotes = kite_provider.get_quote(quote_instruments)

                # Update options data with quote information
                for exchange, symbol in quote_instruments:
                    key = f"{exchange}:{symbol}"
                    if key in quotes:
                        q_any = quotes[key]
                        if not isinstance(q_any, dict):
                            continue
                        # Normalize quote mapping defensively (duck-typed)
                        quote_data = dict(q_any) if hasattr(q_any, 'items') else q_any  # type: ignore[assignment]
                        if symbol in options_data:
                            entry_any = options_data.get(symbol)
                            if not isinstance(entry_any, dict):
                                continue
                            entry: dict[str, Any] = entry_any
                            for field in ['last_price', 'volume', 'oi', 'depth']:
                                if field in quote_data:
                                    entry[field] = quote_data[field]
                            options_data[symbol] = entry

                # Write test data
                timestamp = datetime.datetime.now()  # local-ok
                logger.info(f"Writing sample data for {index}")
                csv_sink.write_options_data(index, expiry, options_data, timestamp)

                # Check if file was created
                expected_dir = os.path.join(csv_sink.base_dir, index, str(expiry))
                expected_file = os.path.join(expected_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")

                if os.path.exists(expected_file):
                    file_size = os.path.getsize(expected_file)
                    logger.info(f"Data file created: {expected_file} ({file_size} bytes)")
                else:
                    logger.warning(f"Data file not created: {expected_file}")

        except Exception as e:
            logger.error(f"Error testing {index}: {e}", exc_info=True)
            try:
                from src.error_handling import handle_collector_error
                handle_collector_error(e, component="tests.test_all_indices", index_name=index)
            except Exception:
                pass

    logger.info("\033[1;32m\n===== TESTING COMPLETED =====\033[0m")
    return 0

if __name__ == "__main__":
    sys.exit(main())
