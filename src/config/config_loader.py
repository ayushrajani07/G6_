#!/usr/bin/env python3
"""
Configuration loader for G6 Options Trading Platform.
"""

import json
import logging
import os

# Add this before launching the subprocess

logger = logging.getLogger(__name__)
from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler


class ConfigLoader:
    """Configuration loader for G6 Platform."""

    @staticmethod
    def load_config(config_path):
        """
        Load configuration from a JSON file.
        
        Args:
            config_path: Path to the config JSON file
            
        Returns:
            dict: Configuration dictionary
        """
        return load_config(config_path)

def load_config(config_path):
    """
    Load configuration from a JSON file.
    
    Args:
        config_path: Path to the config JSON file
        
    Returns:
        dict: Configuration dictionary
    """
    try:
        # Check if file exists
        if not os.path.exists(config_path):
            logger.error(f"Configuration file not found: {config_path}")

            # Create default config if file doesn't exist
            default_config = create_default_config()

            # Ensure directory exists
            try:
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
            except Exception as e:
                try:
                    get_error_handler().handle_error(
                        e,
                        category=ErrorCategory.FILE_IO,
                        severity=ErrorSeverity.MEDIUM,
                        component="config_loader",
                        function_name="load_config",
                        message="Failed to create config directory",
                        context={"path": config_path},
                    )
                except Exception:
                    pass

            # Write default config
            try:
                with open(config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
            except Exception as e:
                try:
                    get_error_handler().handle_error(
                        e,
                        category=ErrorCategory.FILE_IO,
                        severity=ErrorSeverity.MEDIUM,
                        component="config_loader",
                        function_name="load_config",
                        message="Failed to write default config",
                        context={"path": config_path},
                    )
                except Exception:
                    pass

            logger.info(f"Created default configuration at {config_path}")
            return default_config

        # Open and parse JSON file
        with open(config_path) as f:
            config = json.load(f)

        logger.info(f"Loaded configuration from {config_path}")
        return config

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {config_path}")
        try:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.CONFIGURATION,
                severity=ErrorSeverity.HIGH,
                component="config_loader",
                function_name="load_config",
                message="Invalid JSON in configuration file",
                context={"path": config_path},
            )
        except Exception:
            pass
        return create_default_config()
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        try:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.FILE_IO,
                severity=ErrorSeverity.MEDIUM,
                component="config_loader",
                function_name="load_config",
                message="Error loading configuration",
                context={"path": config_path},
            )
        except Exception:
            pass
        return create_default_config()

def create_default_config():
    """Create default configuration."""
    default_config = {
        "metrics": {
            "enabled": True,
            "port": 9108
        },
        "collection": {
            "interval_seconds": 60
        },
        "storage": {
            "csv_dir": "data/g6_data",
            "influx": {
                "enabled": False,
                "url": "http://localhost:8086",
                "token": "",
                "org": "g6platform",
                "bucket": "g6_data"
            }
        },
        "indices": {
            "NIFTY": {
                "enable": True,
                "expiries": ["this_week", "next_week"],
                "strikes_otm": 10,
                "strikes_itm": 10
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
                "strikes_otm": 10,
                "strikes_itm": 10
            },
            "SENSEX": {
                "enable": True,
                "expiries": ["this_week"],
                "strikes_otm": 10,
                "strikes_itm": 10
            }
        }
    }
    return default_config
