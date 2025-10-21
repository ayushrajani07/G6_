#!/usr/bin/env python3
"""
Run G6 Platform with Real API
Runs a few collection cycles using real Kite API.
"""

import logging
import os
import sys
import time

from src.config.config_wrapper import ConfigWrapper
from src.utils.logging_utils import setup_logging
from src.utils.path_utils import data_subdir, ensure_sys_path

try:
    from src.error_handling import handle_api_error, handle_collector_error  # type: ignore
except Exception:  # pragma: no cover
    handle_api_error = None  # type: ignore
    handle_collector_error = None  # type: ignore

ensure_sys_path()

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
    env_loaded = True
except ImportError:
    env_loaded = False
    print("Warning: dotenv not installed, using system environment variables")

setup_logging(level="INFO", log_file="logs/real_api.log")
logger = logging.getLogger("g6.real_api")

def main():
    """Run G6 with real API."""
    print("=== G6 Platform with Real API ===")

    # Import components
    from src.broker.kite_provider import KiteProvider
    from src.collectors.providers_interface import Providers
    from src.collectors.unified_collectors import run_unified_collectors
    from src.config.config_loader import ConfigLoader
    from src.metrics import setup_metrics_server  # facade import
    from src.provider.config import get_provider_config
    from src.storage.csv_sink import CsvSink
    from src.storage.influx_sink import NullInfluxSink

    # Load configuration
    config_path = os.environ.get("CONFIG_PATH", "config/g6_config.json")
    logger.info(f"Loading config from: {config_path}")
    raw_config = ConfigLoader.load_config(config_path)
    config = ConfigWrapper(raw_config)

    # Initialize KiteProvider
    try:
        logger.info("Initializing KiteProvider (ProviderConfig snapshot)")
        snap = get_provider_config()
        kite_provider = KiteProvider.from_provider_config(snap)
        if not snap.api_key:
            logger.warning("ProviderConfig snapshot missing api_key (proceeding; downstream may fetch interactively)")
        logger.info("KiteProvider initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize KiteProvider: {e}")
        try:
            if handle_api_error:
                handle_api_error(e, component="tools.run_with_real_api", context={"op": "init_provider"})
        except Exception:
            pass
        return 1

    # Initialize components
    providers = Providers(primary_provider=kite_provider)

    output_dir = data_subdir("real_api_test")
    os.makedirs(output_dir, exist_ok=True)
    csv_sink = CsvSink(base_dir=output_dir)
    influx_sink = NullInfluxSink()

    # Initialize metrics
    metrics, stop_metrics = setup_metrics_server(port=9108)

    # Run collection cycles
    cycles = 3
    interval = 30  # seconds

    logger.info(f"Starting {cycles} collection cycles with {interval}s interval")

    try:
        for i in range(1, cycles + 1):
            logger.info(f"Running collection cycle {i}/{cycles}")
            start_time = time.time()

            # Run collectors
            index_params = config.index_params()
            run_unified_collectors(
                index_params=index_params,
                providers=providers,
                csv_sink=csv_sink,
                influx_sink=influx_sink,
                metrics=metrics,
            )

            elapsed = time.time() - start_time
            logger.info(f"Cycle {i} completed in {elapsed:.2f} seconds")

            # Sleep if not the last cycle
            if i < cycles:
                sleep_time = max(0.1, interval - elapsed)
                logger.info(f"Sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error during collection: {e}")
        try:
            if handle_collector_error:
                handle_collector_error(e, component="tools.run_with_real_api", index_name="ALL", context={"op": "collect_cycle"})
        except Exception:
            pass
    finally:
        # Clean up
        try:
            providers.close()
        finally:
            if callable(stop_metrics):
                stop_metrics()

    logger.info(f"Collection complete! Data saved to {os.path.abspath(output_dir)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
