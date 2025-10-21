#!/usr/bin/env python3
"""
Refresh Kite API access token
Generates a fresh token using the API key and secret.

This should be run daily before market open.
"""

import logging
import os
import sys
import webbrowser

from dotenv import load_dotenv

try:
    from src.error_handling import handle_api_error  # type: ignore
except Exception:  # pragma: no cover
    handle_api_error = None  # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("kite-token")

def main():
    """Main function to refresh Kite token."""
    # Load environment variables
    load_dotenv()

    # Check for required variables
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")

    if not api_key:
        logger.error("KITE_API_KEY not found in environment")
        return 1

    if not api_secret:
        logger.error("KITE_API_SECRET not found in environment")
        return 1

    try:
        from kiteconnect import KiteConnect

        # Initialize Kite client
        kite = KiteConnect(api_key=api_key)

        # Get the login URL and open it in a browser
        login_url = kite.login_url()
        logger.info(f"Opening login URL: {login_url}")
        webbrowser.open(login_url)

        # Get the request token from user input
        request_token = input("Enter the request token from URL after login: ")

        if not request_token:
            logger.error("Request token is required")
            return 1

        # Generate session and get access token
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data.get("access_token") if isinstance(data, dict) else None  # type: ignore[assignment]

        if not access_token:
            logger.error("Failed to get access token")
            return 1

        # Update the .env file
        env_file = ".env"
        with open(env_file) as f:
            lines = f.readlines()

        found = False
        with open(env_file, "w") as f:
            for line in lines:
                if line.startswith("KITE_ACCESS_TOKEN="):
                    f.write(f"KITE_ACCESS_TOKEN={access_token}\n")
                    found = True
                else:
                    f.write(line)

            if not found:
                f.write(f"\nKITE_ACCESS_TOKEN={access_token}\n")

        logger.info(f"Access token refreshed and saved to {env_file}")
        return 0

    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        try:
            if handle_api_error:
                handle_api_error(e, component="tools.refresh_kite_token", context={"op": "refresh"})
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    sys.exit(main())
