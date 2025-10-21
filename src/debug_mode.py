#!/usr/bin/env python3
"""
Debug mode for G6 Platform with real API calls.
"""

import os
import sys

from src.config.config_wrapper import ConfigWrapper
from src.utils.logging_utils import setup_logging
from src.utils.path_utils import data_subdir, ensure_sys_path

ensure_sys_path()

setup_logging(level="DEBUG", log_file="logs/debug_mode.log")

# Import necessary components
# Retain legacy loader fallback for now
from src.broker.kite_provider import KiteProvider
from src.collectors.providers_interface import Providers
from src.collectors.unified_collectors import run_unified_collectors
from src.config.config_loader import ConfigLoader
from src.metrics import setup_metrics_server  # facade import
from src.provider.config import get_provider_config
from src.storage.csv_sink import CsvSink
from src.storage.influx_sink import NullInfluxSink


def main():
    """Debug mode main function."""
    print("=== G6 Platform Debug Mode ===")

    # 1. Load configuration
    config_path = os.environ.get("CONFIG_PATH", "config/g6_config.json")
    print(f"Loading config from: {config_path}")
    raw_config = ConfigLoader.load_config(config_path)
    config = ConfigWrapper(raw_config)

    # 2. Initialize Kite Provider
    print("Initializing KiteProvider from environment variables")
    try:
        snap = get_provider_config()
        kite_provider = KiteProvider.from_provider_config(snap)
        print("✓ KiteProvider initialized successfully")
    except Exception as e:
        print(f"✗ KiteProvider initialization failed: {e}")
        return 1

    # 3. Initialize Providers wrapper
    providers = Providers(primary_provider=kite_provider)

    # 4. Initialize storage
    csv_dir = data_subdir("csv_debug")
    os.makedirs(csv_dir, exist_ok=True)
    csv_sink = CsvSink(base_dir=csv_dir)
    influx_sink = NullInfluxSink()

    # 5. Initialize metrics
    metrics, _ = setup_metrics_server()

    # 6. Test get_atm_strike
    try:
        for index in config.index_params().keys():
            expiry = providers.resolve_expiry(index, 'this_week')
            atm = providers.get_ltp(index)
            print(f"Index: {index}, Expiry: {expiry}, ATM Strike: {atm}")
    except Exception as e:
        print(f"Error getting ATM strikes: {e}")

    # 7. Run a single collection cycle
    print("\nRunning single collection cycle...")
    try:
        run_unified_collectors(
            index_params=config.index_params(),
            providers=providers,
            csv_sink=csv_sink,
            influx_sink=influx_sink,
            metrics=metrics
        )
        print("✓ Collection cycle completed successfully")
        print(f"Data saved to {os.path.abspath(csv_dir)}")
    except Exception as e:
        print(f"✗ Collection cycle failed: {e}")

    # Clean up
    providers.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())
