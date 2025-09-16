#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run G6 Platform with Real API
Runs a few collection cycles using real Kite API.
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from src.utils.path_utils import ensure_sys_path, data_subdir
from src.utils.logging_utils import setup_logging
from src.config.config_wrapper import ConfigWrapper

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
    from src.config.config_loader import ConfigLoader
    from src.broker.kite_provider import KiteProvider
    from src.collectors.providers_interface import Providers
    from src.collectors.unified_collectors import run_unified_collectors
    from src.storage.csv_sink import CsvSink
    from src.storage.influx_sink import NullInfluxSink
    from src.metrics.metrics import setup_metrics_server
    
    # Load configuration
    config_path = os.environ.get("CONFIG_PATH", "config/g6_config.json")
    logger.info(f"Loading config from: {config_path}")
    raw_config = ConfigLoader.load_config(config_path)
    config = ConfigWrapper(raw_config)
    
    # Initialize KiteProvider
    try:
        api_key = os.environ.get("KITE_API_KEY")
        if not api_key:
            logger.error("KITE_API_KEY not found in environment")
            return 1
        
        logger.info("Initializing KiteProvider")
        kite_provider = KiteProvider.from_env()
        logger.info("KiteProvider initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize KiteProvider: {e}")
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