#!/usr/bin/env python3
"""
G6 Options Trading Platform - Debug Startup
Helps diagnose where the program is getting stuck.
"""

import logging
import os
import sys

# Add this before launching the subprocess

# Configure logging to be more immediate
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("debug")

# Add this at the beginning before any imports
try:  # Optional dependency
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
    logger.info("Environment variables loaded from .env file")
except ImportError:  # pragma: no cover
    logger.info("python-dotenv not installed; continuing without .env file")

def main():
    """Main diagnostic function."""
    logger.info("Starting diagnostic...")

    # Print API key status (masked for security)
    api_key = os.environ.get("KITE_API_KEY", "")
    if api_key:
        masked_key = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "****"
        logger.info(f"Found KITE_API_KEY in environment: {masked_key}")
    else:
        logger.warning("KITE_API_KEY not found in environment")

    # Step 1: Import core modules
    logger.info("Step 1: Importing config module...")
    logger.info("Config module imported successfully")

    # Rest of the function remains the same...
    # ...
