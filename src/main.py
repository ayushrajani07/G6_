"""Deprecated legacy entrypoint.

This file has been superseded by `unified_main.py` which merges the logic
previously split between `main.py` and `main_advanced.py`.

Usage:
    python -m src.unified_main ... (see --help)

Keeping this lightweight stub (instead of deleting the file outright) helps
avoid breaking external scripts or docs that still reference `src.main`.
"""

from __future__ import annotations

import sys


def _deprecated() -> None:
    msg = (
        "src.main is deprecated. Use src.unified_main instead. "
        "Example: python -m src.unified_main --help"
    )
    raise RuntimeError(msg)


if __name__ == "__main__":  # pragma: no cover
    _deprecated()
else:
    # If imported, immediately raise to surface misuse early.
    _deprecated()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G6 Platform - Options Data Collection and Analysis Platform
"""

import os
import sys
import time
import json
import logging
import signal
import argparse
import datetime
import threading
from src.utils.path_utils import ensure_sys_path, resolve_path, data_subdir


ensure_sys_path()

from typing import Dict, Any, Optional

# Import market hours utilities
from src.utils.market_hours import is_market_open, get_next_market_open, sleep_until_market_open, DEFAULT_MARKET_HOURS

# Import core modules
from src.collectors.providers_interface import Providers
from src.collectors.unified_collectors import run_unified_collectors
from src.storage.csv_sink import CsvSink
try:
    from storage.influx_sink import InfluxSink
except ImportError:
    InfluxSink = None

# Import health monitoring
from src.health.monitor import HealthMonitor
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.resilience import retry, fallback, HealthCheck



# Then launch your subprocess

# Set up version
__version__ = "1.0.0"

# Configure logging
def setup_logging(log_level=logging.INFO, log_file=None):
    """Set up logging configuration."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Create logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console)
    
    # Add file handler if specified
    if log_file:
        # Create log directory if needed
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)
    
    # Suppress verbose logging from other libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    return root_logger

# State management
class AppState:
    """Application state management."""
    
    def __init__(self):
        self.running: bool = False
        self.stopping: bool = False
        self.collection_thread: Optional[threading.Thread] = None
        self.metrics: Any = None
        self.providers: Optional[Providers] = None
        self.csv_sink: Optional[CsvSink] = None
        self.influx_sink: Any = None
        self.health_monitor: Optional[HealthMonitor] = None
        # Create state directory if it doesn't exist (via centralized utils)
        state_dir = data_subdir('state')
        os.makedirs(state_dir, exist_ok=True)
        # Initialize app-wide lock
        self.lock = threading.RLock()
    
    def save_state(self, filename="data/state/app_state.json"):
        """Save application state to file."""
        from src.utils.timeutils import utc_now, isoformat_z
        state = {
            'version': __version__,
            'timestamp': isoformat_z(utc_now()),
            'running': self.running,
            'metrics': self.metrics is not None
        }
        try:
            resolved_filename = resolve_path(filename, create=True)
            with open(resolved_filename, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving application state: {e}")

# Signal handling
def setup_signal_handling(app_state):
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(sig, frame):
        logging.info(f"Received signal {sig}, shutting down gracefully")
        app_state.stopping = True
        app_state.running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# Command line argument parsing
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='G6 Platform - Options Data Collection')
    
    parser.add_argument('--config', default='config/config.json',
                        help='Path to configuration file (default: config/config.json)')
    
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='Set the logging level')
    
    parser.add_argument('--log-file', default='logs/g6_platform.log',
                        help='Path to log file (default: logs/g6_platform.log)')
    
    parser.add_argument('--debug-midcpnifty', action='store_true',
                        help='Enable detailed debugging for MIDCPNIFTY')
    
    parser.add_argument('--data-dir', default=data_subdir('g6_data'),
                        help='Path to data directory (default: data/g6_data, resolved to project root)')
    
    parser.add_argument('--version', action='version', version=f'G6 Platform {__version__}')
    
    parser.add_argument('--interval', type=int, default=60,
                        help='Collection interval in seconds (default: 60)')
    
    return parser.parse_args()

# Load configuration
def load_config(config_file):
    """Load configuration from JSON file."""
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
            logging.info(f"Loaded configuration from {config_file}")
            return config
        else:
            logging.warning(f"Config file {config_file} not found, using defaults")
            return create_default_config(config_file)
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        return create_default_config()

def create_default_config(config_file=None):
    """Create and optionally save default configuration."""
    default_config = {
    "data_dir": data_subdir("g6_data"),
        "collection_interval": 60,
        "market_hours": {
            "start": "09:15",
            "end": "15:30",
            "timezone": "Asia/Kolkata"
        },
        "indices": {
            "NIFTY": {
                "enable": True,
                "expiries": ["this_week", "next_week"],
                "strikes_otm": 10,
            # Removed unresolved import
                    # from metrics.prometheus import PrometheusMetrics  # Removed unresolved import

            },
            "BANKNIFTY": {
                "enable": True,
                "expiries": ["this_week", "next_week"],
                "strikes_otm": 10,
                "strikes_itm": 10
            },
            "FINNIFTY": {
                "enable": True,
                "expiries": ["this_week"],
                "strikes_otm": 8,
                "strikes_itm": 8
            },
            "MIDCPNIFTY": {
                "enable": False,
                "expiries": ["this_week"],
                "strikes_otm": 8,
                "strikes_itm": 8
            }
        },
        "providers": {
            "primary": {
                "type": "kite",
                "api_key": "",
                "api_secret": "",
                "access_token": "",
                "token_path": "config/kite_token.json"
            }
        },
        "influx": {
            "enable": False,
            "url": "http://localhost:8086",
            "token": "",
            "org": "",
            "bucket": "g6_options"
        },
        "health": {
            "check_interval": 60,
            "circuit_breaker": {
                "failure_threshold": 5,
                "reset_timeout": 300
            }
        }
    }
    
    if config_file:
        try:
            # Create config directory if it doesn't exist
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            logging.info(f"Created default config at {config_file}")
        except Exception as e:
            logging.error(f"Error saving default config: {e}")
    
    return default_config

# Initialize providers
def initialize_providers(config, debug_midcpnifty=False):
    """Initialize data providers based on configuration."""
    primary_provider = None
    secondary_provider = None
    
    provider_config = config.get('providers', {}).get('primary', {})
    provider_type = provider_config.get('type', '').lower()
    
    try:
        if provider_type == 'kite':
            from src.broker.kite_provider import KiteProvider
            api_key = provider_config.get('api_key', '')
            access_token = provider_config.get('access_token', '')
            primary_provider = KiteProvider(
                api_key=api_key,
                access_token=access_token
            )
        elif provider_type == 'dummy':
            from src.broker.kite_provider import DummyKiteProvider
            primary_provider = DummyKiteProvider()
        else:
            logging.error(f"Unsupported provider type: {provider_type}")
            return None
    except Exception as e:
        logging.error(f"Error initializing primary provider: {e}")
        return None
    
    # Initialize secondary provider if configured
    # (code for secondary provider would go here)
    
    # Create providers interface
    providers = Providers(
        primary_provider=primary_provider, 
        secondary_provider=secondary_provider,
    # debug_midcpnifty=debug_midcpnifty  # Removed invalid parameter
    )
    
    return providers

# Initialize storage
def initialize_storage(config):
    """Initialize data storage based on configuration."""
    # Initialize CSV sink
    data_dir = resolve_path(config.get('data_dir', 'data/g6_data'), create=True)
    csv_sink = CsvSink(base_dir=data_dir)
    
    # Initialize InfluxDB sink if enabled
    influx_sink = None
    if config.get('influx', {}).get('enable', False) and InfluxSink is not None:
        try:
            influx_config = config.get('influx', {})
            influx_sink = InfluxSink(
                url=influx_config.get('url', 'http://localhost:8086'),
                token=influx_config.get('token', ''),
                org=influx_config.get('org', ''),
                bucket=influx_config.get('bucket', 'g6_options')
            )
        except Exception as e:
            logging.error(f"Error initializing InfluxDB sink: {e}")
    
    return csv_sink, influx_sink

# Initialize health monitor
def initialize_health_monitor(config, app_state):
    """Initialize health monitoring system."""
    health_config = config.get('health', {})
    check_interval = health_config.get('check_interval', 60)
    
    health_monitor = HealthMonitor(check_interval=check_interval)
    
    # Register components if they exist
    if app_state.providers:
        health_monitor.register_component('providers', app_state.providers)
        
    if app_state.csv_sink:
        health_monitor.register_component('csv_sink', app_state.csv_sink)
        
    if app_state.influx_sink:
        health_monitor.register_component('influx_sink', app_state.influx_sink)
    
    # Register health checks
    if app_state.providers:
        health_monitor.register_health_check(
            'primary_provider_responsive', 
            lambda: HealthCheck.check_provider(
                app_state.providers.primary_provider, 
                'get_ltp', 
                args=['NIFTY']
            )
        )
    
    if app_state.csv_sink:
        health_monitor.register_health_check(
            'csv_storage',
            lambda: HealthCheck.check_storage(app_state.csv_sink)
        )
    
    return health_monitor

# Collection function
def collection_loop(config, app_state):
    """Main collection loop with market hours awareness."""
    interval = config.get('collection_interval', 60)
    
    # Define callbacks for sleep_until_market_open
    def on_wait_start(next_open):
        wait_time = (next_open - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        logging.info(f"Market is closed. Waiting for next open at {next_open} (in {wait_time/60:.1f} minutes)")
    
    def on_wait_tick(seconds_remaining):
        if seconds_remaining % 300 == 0:  # Log every 5 minutes
            logging.info(f"Still waiting for market open: {seconds_remaining/60:.1f} minutes remaining")
        
        # Check if we should stop
        return not app_state.stopping
    
    while app_state.running:
        try:
            # Check if market is open
            if not is_market_open(market_type="equity", session_type="regular"):
                next_open = get_next_market_open(market_type="equity", session_type="regular")
                wait_time = (next_open - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                
                # If we just closed, log a clear message
                logging.info(f"Market is closed. Collection suspended until next open at {next_open}")
                logging.info(f"Waiting {wait_time/60:.1f} minutes until market reopens")
                
                # Sleep until market opens or app stops
                sleep_until_market_open(
                    market_type="equity", 
                    session_type="regular",
                    check_interval=10,  # Check every 10 seconds
                    on_wait_start=on_wait_start,
                    on_wait_tick=on_wait_tick
                )
                
                # If we're stopping, exit the loop
                if app_state.stopping:
                    break
                
                # Market opened, log and continue
                logging.info("Market has opened, starting collection")
                continue  # Start collecting immediately
            
            # Market is open, run collection
            start_time = time.time()
            
            # Run collectors
            indices_config = config.get('indices', {})
            run_unified_collectors(
                indices_config,
                app_state.providers,
                app_state.csv_sink,
                app_state.influx_sink,
                app_state.metrics
            )
            
            # Calculate time taken
            elapsed = time.time() - start_time
            logging.info(f"Collection cycle completed in {elapsed:.2f} seconds")
            
            # Calculate sleep time for next collection
            sleep_time = max(0, interval - elapsed)
            
            # Check if market will still be open for the next collection
            next_collection_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=sleep_time)
            if not is_market_open(market_type="equity", session_type="regular", reference_time=next_collection_time):
                # Market will close before next collection
                logging.info("Market will close before next scheduled collection")
                
                # Find out when market will close
                current_time = datetime.datetime.now(datetime.timezone.utc)
                # Get market hours from your constants
                # DEFAULT_MARKET_HOURS already imported from src.utils.market_hours
                
                # Parse market close time
                equity_close = DEFAULT_MARKET_HOURS["equity"]["regular"]["end"]
                close_time = datetime.datetime.strptime(equity_close, "%H:%M:%S").time()
                
                # Convert current time to IST for comparison
                ist_offset = datetime.timedelta(hours=5, minutes=30)
                ist_now = current_time + ist_offset
                
                # Calculate time remaining until close
                close_datetime = datetime.datetime.combine(ist_now.date(), close_time)
                if ist_now.time() > close_time:
                    # Already past closing time
                    sleep_time = 0
                else:
                    # Convert closing time back to UTC and calculate seconds until then
                    utc_close = close_datetime - ist_offset
                    seconds_to_close = (utc_close - current_time).total_seconds()
                    # Sleep until just after closing time
                    sleep_time = seconds_to_close + 5  # Add 5 seconds to ensure we're past closing
                
                logging.info(f"Sleeping for {sleep_time:.2f} seconds until market closes")
            else:
                logging.debug(f"Sleeping for {sleep_time:.2f} seconds until next collection")
            
            # Use small sleep intervals to check for stopping
            for _ in range(int(sleep_time)):
                # Check if market has closed during our sleep (in case of early closure)
                if not is_market_open(market_type="equity", session_type="regular") and _ % 60 == 0:
                    logging.info("Market has closed during sleep period. Ending collection cycle.")
                    break
                
                if app_state.stopping:
                    break
                time.sleep(1)
            
            # Sleep any remaining fraction
            if sleep_time % 1 > 0 and not app_state.stopping:
                time.sleep(sleep_time % 1)
            
        except Exception as e:
            logging.error(f"Error in collection loop: {e}")
            # Sleep a bit before retrying
            time.sleep(5)
        
        # Check if we should stop
        if app_state.stopping:
            break
    
  
    logging.info("Collection loop stopped")

# Main application entry point
def main():
    """Main application entry point."""
    # Parse command-line arguments
    args = parse_arguments()
    
    # Set up logging
    log_level = getattr(logging, args.log_level)
    logger = setup_logging(log_level=log_level, log_file=args.log_file)
    
    # Log startup information
    logger.info(f"G6 Platform {__version__} starting up")
    logger.info(f"Python version: {sys.version}")
    
    # Initialize application state
    app_state = AppState()
    
    # Set up signal handling
    setup_signal_handling(app_state)
    
    # Load configuration
    config = load_config(args.config)
    
    # Override config with command line args
    if args.data_dir:
        config['data_dir'] = args.data_dir
    
    if args.interval:
        config['collection_interval'] = args.interval
    
    # Initialize components
    try:
        # Initialize providers
        logger.info("Initializing data providers")
        app_state.providers = initialize_providers(config, debug_midcpnifty=args.debug_midcpnifty)
        if not app_state.providers:
            logger.error("Failed to initialize providers, exiting")
            return 1
        
        # Initialize storage
        logger.info("Initializing data storage")
        app_state.csv_sink, app_state.influx_sink = initialize_storage(config)
        
        # Metrics initialization removed (Prometheus integration not yet implemented here)
        app_state.metrics = None
        
        # Initialize health monitor
        logger.info("Initializing health monitor")
        app_state.health_monitor = initialize_health_monitor(config, app_state)
        app_state.health_monitor.start()
        
        # Apply circuit breakers if configured
        circuit_config = config.get('health', {}).get('circuit_breaker', {})
        if circuit_config:
            failure_threshold = circuit_config.get('failure_threshold', 5)
            reset_timeout = circuit_config.get('reset_timeout', 300)
            
            if app_state.providers and hasattr(app_state.providers, 'primary_provider'):
                logger.info("Applying circuit breakers to provider methods")
                provider = app_state.providers.primary_provider
                
                # Apply to common methods if they exist
                if hasattr(provider, 'get_quote'):
                    api_circuit = CircuitBreaker(
                        "api_quote", 
                        failure_threshold=failure_threshold, 
                        reset_timeout=reset_timeout
                    )
                    if provider is not None and hasattr(provider, 'get_quote'):
                        provider.get_quote = api_circuit(provider.get_quote)
                
                if hasattr(provider, 'get_ltp'):
                    api_circuit = CircuitBreaker(
                        "api_ltp", 
                        failure_threshold=failure_threshold, 
                        reset_timeout=reset_timeout
                    )
                    if provider is not None and hasattr(provider, 'get_ltp'):
                        provider.get_ltp = api_circuit(provider.get_ltp)
        
        # Start collection thread
        logger.info("Starting collection loop")
        app_state.running = True
        app_state.collection_thread = threading.Thread(
            target=collection_loop,
            args=(config, app_state)
        )
        app_state.collection_thread.daemon = True
        app_state.collection_thread.start()
        
        # Save initial state
        app_state.save_state()
        
        # Main thread will wait for signals
        logger.info("G6 Platform is running. Press Ctrl+C to stop.")
        
        while app_state.running:
            time.sleep(1)
        
    except Exception as e:
        logger.error(f"Error during initialization: {e}")
        return 1
    
    finally:
        # Cleanup on exit
        logger.info("Shutting down G6 Platform")
        
        # Stop collection thread
        app_state.running = False
        app_state.stopping = True
        
        if app_state.collection_thread and app_state.collection_thread.is_alive():
            app_state.collection_thread.join(timeout=5.0)
        
        # Stop health monitor
        if app_state.health_monitor:
            logger.info("Stopping health monitor")
            app_state.health_monitor.stop()
        
        # Close providers
        if app_state.providers:
            logger.info("Closing data providers")
            app_state.providers.close()
        
        # Save final state
        app_state.save_state()
        
        logger.info("Shutdown complete")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())