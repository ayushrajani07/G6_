#!/usr/bin/env python3
"""
Configuration validation for G6 Platform.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

class ConfigError(Exception):
    """Exception raised for configuration errors."""
    pass

def validate_config(config: dict[str, Any]) -> list[str]:
    """
    Validate configuration and return a list of errors.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        List of error messages, empty if no errors
    """
    errors = []

    # Check required top-level keys
    required_keys = ['collection_interval', 'indices']
    for key in required_keys:
        if key not in config:
            errors.append(f"Missing required config key: {key}")

    # Validate collection interval
    if 'collection_interval' in config:
        interval = config['collection_interval']
        if not isinstance(interval, (int, float)) or interval <= 0:
            errors.append(f"Invalid collection_interval: {interval}, must be positive number")

    # Validate market hours
    if 'market_hours' in config:
        market_hours = config['market_hours']

        if not isinstance(market_hours, dict):
            errors.append("market_hours must be a dictionary")
        else:
            for time_key in ['start', 'end']:
                if time_key not in market_hours:
                    errors.append(f"Missing {time_key} in market_hours")
                else:
                    # Check time format (HH:MM)
                    time_value = market_hours[time_key]
                    if not isinstance(time_value, str) or len(time_value.split(':')) != 2:
                        errors.append(f"Invalid time format for market_hours.{time_key}: {time_value}")

    # Validate indices configuration
    if 'indices' in config and isinstance(config['indices'], dict):
        indices = config['indices']

        if not indices:
            errors.append("No indices configured")

        for index_name, index_config in indices.items():
            if not isinstance(index_config, dict):
                errors.append(f"Invalid config for index {index_name}")
                continue

            # Check required fields
            if 'expiries' not in index_config:
                errors.append(f"Missing expiries for index {index_name}")
            elif not isinstance(index_config['expiries'], list):
                errors.append(f"expiries for index {index_name} must be a list")
            else:
                valid_expiries = ['this_week', 'next_week', 'this_month', 'next_month']
                for expiry in index_config['expiries']:
                    if expiry not in valid_expiries:
                        errors.append(f"Invalid expiry '{expiry}' for index {index_name}")

            # Check numeric fields
            for field in ['strikes_otm', 'strikes_itm']:
                if field in index_config:
                    if not isinstance(index_config[field], int) or index_config[field] < 0:
                        errors.append(f"{field} for index {index_name} must be a non-negative integer")
    else:
        errors.append("Missing or invalid indices configuration")

    # Validate provider configuration
    if 'providers' in config and isinstance(config['providers'], dict):
        providers = config['providers']

        if 'primary' not in providers:
            errors.append("No primary provider configured")
        elif not isinstance(providers['primary'], dict):
            errors.append("Invalid primary provider configuration")
        else:
            primary = providers['primary']

            if 'type' not in primary:
                errors.append("Missing provider type in primary provider config")
            elif primary['type'] not in ['kite', 'dummy']:
                errors.append(f"Unsupported provider type: {primary['type']}")

            if primary.get('type') == 'kite':
                if not primary.get('api_key'):
                    errors.append("Missing api_key for Kite provider")
                if not primary.get('api_secret'):
                    errors.append("Missing api_secret for Kite provider")
    else:
        errors.append("Missing or invalid providers configuration")

    # Validate InfluxDB configuration if enabled
    if 'influx' in config and isinstance(config['influx'], dict):
        influx = config['influx']

        if influx.get('enable', False):
            for field in ['url', 'token', 'org', 'bucket']:
                if not influx.get(field):
                    errors.append(f"Missing {field} in InfluxDB configuration")

    # Return all errors
    return errors

def apply_environment_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """
    Apply environment variable overrides to configuration.
    
    Environment variables should be prefixed with G6_
    Examples:
    - G6_COLLECTION_INTERVAL -> collection_interval
    - G6_PROVIDERS_PRIMARY_API_KEY -> providers.primary.api_key
    
    Args:
        config: Original configuration
        
    Returns:
        Updated configuration with environment overrides
    """
    # Create a copy of the config to modify
    updated_config = config.copy()

    # Find environment variables with G6_ prefix
    for key, value in os.environ.items():
        if not key.startswith('G6_'):
            continue

        # Remove prefix and convert to lowercase
        config_key = key[3:].lower()

        # Handle nested keys (separated by _)
        key_parts = config_key.split('_')

        # Start with the top-level config
        current_level = updated_config

        # Navigate to the correct nested level
        for i, part in enumerate(key_parts):
            # If we're at the last part, set the value
            if i == len(key_parts) - 1:
                # Try to convert string value to appropriate type
                try:
                    # Check if existing value is a specific type and convert accordingly
                    if part in current_level and isinstance(current_level[part], bool):
                        current_level[part] = value.lower() in ('true', 'yes', '1')
                    elif part in current_level and isinstance(current_level[part], int):
                        current_level[part] = int(value)
                    elif part in current_level and isinstance(current_level[part], float):
                        current_level[part] = float(value)
                    else:
                        current_level[part] = value
                except (ValueError, TypeError):
                    # If conversion fails, use the string value
                    current_level[part] = value

                logger.info(f"Applied environment override for {key}")
                break

            # Create nested dict if it doesn't exist
            if part not in current_level:
                current_level[part] = {}

            # Move to next level
            if isinstance(current_level[part], dict):
                current_level = current_level[part]
            else:
                # Can't go deeper, replace with new dict
                current_level[part] = {}
                current_level = current_level[part]

    return updated_config

def load_config_with_validation(config_file: str) -> dict[str, Any]:
    """
    Load and validate configuration from file.
    
    Args:
        config_file: Path to configuration file
        
    Returns:
        Validated configuration dictionary
        
    Raises:
        ConfigError: If configuration is invalid
    """
    # Check if config file exists
    if not os.path.exists(config_file):
        logger.warning(f"Config file {config_file} not found, creating default")

        # Create default config
        from src.main import create_default_config
        config = create_default_config(config_file)
    else:
        # Load config from file
        try:
            with open(config_file) as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Error reading config file: {e}")

    # Apply environment overrides
    config = apply_environment_overrides(config)

    # Validate configuration
    errors = validate_config(config)
    if errors:
        error_message = "Configuration errors:\n" + "\n".join(f"- {error}" for error in errors)
        logger.error(error_message)
        raise ConfigError(error_message)

    return config
