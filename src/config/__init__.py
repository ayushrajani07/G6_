"""
Configuration module for G6 Platform.
"""
# Add this before launching the subprocess
import os
import sys  # retained for backward compatibility logging or future use

from .config_loader import ConfigLoader


# For backward compatibility
def load_config(config_path):
    """Legacy function to load config (returns raw dict)."""
    return ConfigLoader.load_config(config_path)
