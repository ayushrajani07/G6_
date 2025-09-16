#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kite API Token Manager for G6 Platform

Features:
- Validates existing access tokens
- Multiple token refresh options
- Automatically runs main application after successful validation
"""

import os
import sys
import time
import logging
import webbrowser
from pathlib import Path
import subprocess
import threading
from typing import Any, Dict, TypedDict, Optional, cast
try:  # Optional dependency
    from dotenv import load_dotenv  # type: ignore
except Exception:  # noqa: BLE001
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False


# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("token-manager")

# Suppress Flask development server logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

def load_env_vars():
    """Load environment variables from .env file."""
    try:
        load_dotenv()
        logger.info("Environment variables loaded from .env file")
        return True
    except Exception as e:
        logger.warning(f"Error loading .env file: {e}")
        return False

class ProfileDict(TypedDict, total=False):
    user_name: str
    userName: str

class SessionDict(TypedDict, total=False):
    access_token: str


def _to_dict(obj: Any) -> Dict[str, Any]:
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}


def validate_token(api_key, access_token):
    """Validate current token. Cast responses to dict for type safety."""
    if not api_key or not access_token:
        logger.warning("API key or access token is missing")
        return False
        
    try:
        from kiteconnect import KiteConnect
        
        # Initialize Kite with the token
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        
        # Try a simple API call to validate
        logger.info("Validating token with a simple API call...")
        raw = kite.profile()
        profile = cast(ProfileDict, _to_dict(raw))
        user_name = profile.get('user_name') or profile.get('userName') or 'Unknown'
        logger.info(f"Token is valid. Logged in as: {user_name}")
        return True
        
    except Exception as e:
        logger.warning(f"Token validation failed: {e}")
        return False

def acquire_or_refresh_token(auto_open_browser: bool = True, interactive: bool = True, validate_after: bool = True) -> bool:
    """Programmatic helper to ensure a valid Kite access token exists.

    Args:
        auto_open_browser: If True, attempt automated (Flask) flow first.
        interactive: If True, allows guided/manual flows if automation fails.
        validate_after: Re-validate token after acquisition.

    Returns:
        bool: True if a valid token is present (existing or newly acquired), else False.
    """
    load_env_vars()
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key or not api_secret:
        logger.error("Missing KITE_API_KEY or KITE_API_SECRET in environment")
        return False
    # Existing token fast path
    if access_token and validate_token(api_key, access_token):
        return True
    # Automated browser-based flow
    if auto_open_browser:
        try:
            new_tok = flask_login_server(api_key, api_secret, auto_run_app=False)
            if new_tok and (not validate_after or validate_token(api_key, new_tok)):
                return True
        except Exception as e:
            logger.warning(f"Automated token acquisition failed: {e}")
    # Interactive guided/manual flow
    if interactive:
        try:
            new_tok = guided_token_refresh(api_key, api_secret, auto_run_app=False)
            if new_tok and (not validate_after or validate_token(api_key, new_tok)):
                return True
        except Exception as e:
            logger.warning(f"Guided token refresh failed: {e}")
    logger.error("Unable to acquire a valid Kite access token")
    return False

def manual_token_entry():
    """Allow user to manually enter an access token."""
    print("\n" + "=" * 80)
    print("Manual Access Token Entry")
    print("=" * 80)
    
    print("\nYou can enter a Kite access token directly.")
    print("This is useful if you have a valid token from another source.")
    
    access_token = input("\nEnter Kite access token: ").strip()
    
    if not access_token:
        logger.warning("No token entered")
        return None
    
    return access_token

def update_env_file(key, value):
    """Update a value in the .env file."""
    env_file = ".env"
    
    # Read existing file or create new one
    lines = []
    if os.path.isfile(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if not line.startswith(f"{key}="):
                    lines.append(line.rstrip("\n"))
    
    # Add or update the key
    lines.append(f"{key}={value}")
    
    # Write back to file
    with open(env_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    
    logger.info(f"Updated {key} in {env_file}")

def run_main_application(extra_args: Optional[list[str]] = None):
    """Run the unified G6 Platform application.

    Prefers in-process import of `src.unified_main` for faster startup; falls back
    to a subprocess invocation if import-time issues arise (keeps isolation when
    debugging path/env problems).
    """
    if extra_args is None:
        extra_args = []
    try:
        logger.info("Starting G6 Unified Platform...")
        try:
            from src import unified_main  # type: ignore
            # Simulate CLI argv for unified_main
            prev_argv = sys.argv[:]
            sys.argv = [prev_argv[0], *extra_args]
            try:
                return unified_main.main()
            finally:
                sys.argv = prev_argv
        except Exception as imp_err:  # noqa: BLE001
            logger.warning(f"In-process unified_main launch failed ({imp_err}); falling back to subprocess")
            cmd = [sys.executable, '-m', 'src.unified_main', *extra_args]
            result = subprocess.run(cmd)
            return result.returncode
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error starting unified main application: {e}")
        return 1

def flask_login_server(api_key, api_secret, auto_run_app=True):
    """
    Run a Flask server to handle Kite login callback.
    
    Args:
        api_key: Kite API key
        api_secret: Kite API secret
        auto_run_app: Whether to automatically run the main app after successful token validation
        
    Returns:
        str or None: The new access token if successful, None otherwise
    """
    # Flask is required for this method
    try:  # Optional dependency path
        from flask import Flask, request  # type: ignore
        from kiteconnect import KiteConnect  # type: ignore
    except ImportError:
        logger.error("Flask and/or kiteconnect packages are not installed")
        print("\nPlease install required packages:")
        print("pip install flask kiteconnect")
        return None
    
    # Create Flask app
    app = Flask(__name__)
    
    # Variable to store access token
    access_token_container = {'token': None, 'received': False}
    
    # Create Kite connect instance
    kite = KiteConnect(api_key=api_key)
    
    # Define the registered redirect URI path
    # IMPORTANT: This must match exactly what's registered in your Kite Connect API console
    @app.route('/success')  # Default redirect path
    def success_route():
        """Handle the callback at /success path."""
        return handle_callback()
    
    # Also register common alternate paths
    @app.route('/callback')
    def callback_route():
        """Handle the callback at /callback path."""
        return handle_callback()
    
    @app.route('/')  # Root path as fallback
    def root_route():
        """Handle the callback at root path."""
        return handle_callback()
    
    def handle_callback():
        """Common handler for all callback routes."""
        status = request.args.get('status')
        request_token = request.args.get('request_token')
        
        if status != 'success' or not request_token:
            return "Login failed or missing request token", 400
        
        try:
            # Exchange request token for access token
            raw_session = kite.generate_session(request_token, api_secret=api_secret)
            session_data = cast(SessionDict, _to_dict(raw_session))
            access_token = session_data.get('access_token')
            if not access_token:
                raise RuntimeError('Access token missing in session response')
            
            # Store token in container
            access_token_container['token'] = access_token
            access_token_container['received'] = True
            
            # Return success page
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>G6 Platform - Authentication Success</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
                    .success { color: green; font-weight: bold; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; 
                               border: 1px solid #ddd; border-radius: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Authentication Successful!</h1>
                    <p class="success">✅ Token received and validated</p>
                    <p>You can now close this browser window and return to the G6 Platform.</p>
                    <p>The application will start automatically.</p>
                </div>
            </body>
            </html>
            """
            return html
            
        except Exception as e:
            logger.error(f"Error exchanging request token: {e}")
            return f"Error: {str(e)}", 500
    
    # Start Flask server in a separate thread
    def run_flask():
        app.run(port=5000, debug=False)
    
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    # Allow the server to start
    time.sleep(1)
    
    # Generate login URL - specify the correct redirect URI
    redirect_uri = "http://localhost:5000/success"  # This should match what's registered in Kite
    
    # Obtain login URL (omit redirect kwarg for broad compatibility)
    try:
        login_url = kite.login_url()
    except Exception as e:
        logger.error(f"Unable to generate login URL: {e}")
        return None
    
    print("\n" + "=" * 80)
    print("Kite API Authentication")
    print("=" * 80)
    print("\n🔑 Opening browser for Kite login...")
    print("If it doesn't auto-open, copy/paste this URL into your browser:\n")
    print(f"{login_url}\n")
    
    # Open browser to login URL
    try:
        webbrowser.open(login_url)
    except Exception:
        pass
    
    # Wait for callback to complete
    print("Waiting for authentication to complete...\n")
    
    timeout = 180  # 3 minutes
    start_time = time.time()
    
    while not access_token_container['received'] and time.time() - start_time < timeout:
        time.sleep(0.5)
        sys.stdout.write(".")
        sys.stdout.flush()
    
    print("\n")
    
    # Check if we got a token
    if access_token_container['received']:
        logger.info("Authentication completed successfully!")
        # Update .env file
        update_env_file("KITE_ACCESS_TOKEN", access_token_container['token'])
        
        # Run main application automatically if requested
        if auto_run_app:
            run_main_application()
            
        return access_token_container['token']
    else:
        logger.error("Authentication timed out")
        return None

def guided_token_refresh(api_key, api_secret, auto_run_app=True):
    """
    Guide the user through manual token refresh.
    
    Args:
        api_key: Kite API key
        api_secret: Kite API secret
        auto_run_app: Whether to automatically run the main app after successful token validation
        
    Returns:
        str or None: The new access token if successful, None otherwise
    """
    try:
        from kiteconnect import KiteConnect
        
        # Initialize Kite client
        kite = KiteConnect(api_key=api_key)
        
        # Get the login URL
        login_url = kite.login_url()
        
        print("\n" + "=" * 80)
        print("Manual Token Refresh")
        print("=" * 80)
        print("\n1. A browser window will open for you to log in to Kite")
        print("2. After login, look at the URL in your browser")
        print("3. Copy the 'request_token' parameter from that URL\n")
        
        # Open browser
        try:
            webbrowser.open(login_url)
            print("   Browser opened with Kite login page")
        except Exception:
            print(f"   Please open this URL manually: {login_url}")
        
        # Wait for user to log in and get redirected
        print("\nAfter logging in, you'll be redirected to a page with an error or a blank screen.")
        print("That's expected! Look at the URL in your browser's address bar.\n")
        
        # Get request token from user
        request_token = input("Enter the request token from the URL: ").strip()
        
        if not request_token:
            print("\nNo request token provided!")
            return None
        
        # Exchange for access token
        logger.info("Generating session with request token...")
        raw_session = kite.generate_session(request_token, api_secret=api_secret)
        session_data = cast(SessionDict, _to_dict(raw_session))
        access_token = session_data.get("access_token")
        
        if not access_token:
            logger.error("Failed to get access token from response")
            return None
        
        # Save to .env file
        update_env_file("KITE_ACCESS_TOKEN", access_token)
        
        logger.info(f"New access token generated successfully")
        
        # Run main application automatically if requested
        if auto_run_app:
            run_main_application()
            
        return access_token
    
    except Exception as e:
        logger.error(f"Error in guided token refresh: {e}")
        return None

def main():
    """Main entry point for token management and optional unified app launch.

    Supports forwarding of arbitrary flags to unified_main by using '--' separator:
        python -m src.tools.token_manager -- --run-once --validate-auth
    """
    print("\n=== G6 Platform: Kite API Token Manager ===\n")

    import argparse
    parser = argparse.ArgumentParser(description='G6 Platform Token Manager', add_help=True)
    parser.add_argument('--no-autorun', action='store_true', help='Do not automatically run main application')
    parser.add_argument('--', dest='passthrough', help=argparse.SUPPRESS)  # placeholder (not used directly)
    # We capture unknown args AFTER parsing known ones
    known_args, unknown_args = parser.parse_known_args()
    auto_run_app = not known_args.no_autorun
    passthrough_args = unknown_args  # list[str]
    
    # Load environment variables
    load_env_vars()
    
    # Get API credentials
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")
    
    # Check if we have the required credentials
    if not api_key or not api_secret:
        logger.error("API key or secret not found in environment")
        print("\nPlease create a .env file with the following contents:")
        print("\nKITE_API_KEY=your_api_key_here")
        print("KITE_API_SECRET=your_api_secret_here\n")
        return 1
    
    # Check token validity
    logger.info("Checking for existing access token...")
    token_valid = False
    
    if access_token:
        logger.info("Found existing access token, validating...")
        token_valid = validate_token(api_key, access_token)
    
    # If token is valid and auto_run_app is True, run the main application
    if token_valid and auto_run_app:
        return run_main_application(extra_args=passthrough_args)
        
    # If token is invalid or missing, offer options
    if not token_valid:
        print("\nYour Kite API access token is invalid or missing.")
        print("\nOptions:")
        print("1. Automated token refresh (Flask server)")
        print("2. Guided manual token refresh")
        print("3. Enter access token directly")
        print("4. Exit")
        
        choice = input("\nSelect an option (1-4): ")
        
        if choice == "1":
            access_token = flask_login_server(api_key, api_secret, auto_run_app)
            if not access_token:
                logger.error("Failed to refresh access token")
                print("\nAutomated token refresh failed. Would you like to try manual refresh? (y/n)")
                if input().lower().startswith('y'):
                    access_token = guided_token_refresh(api_key, api_secret, auto_run_app)
                    if not access_token:
                        logger.error("Manual token refresh failed")
                        return 1
                else:
                    return 1
        elif choice == "2":
            access_token = guided_token_refresh(api_key, api_secret, auto_run_app)
            if not access_token:
                logger.error("Failed to refresh access token manually")
                return 1
        elif choice == "3":
            access_token = manual_token_entry()
            if not access_token:
                logger.error("No valid token provided")
                return 1
                
            # Save the manually entered token
            update_env_file("KITE_ACCESS_TOKEN", access_token)
            
            # Validate the entered token
            if not validate_token(api_key, access_token):
                logger.error("The entered token is invalid")
                return 1
                
            # Run main application automatically if requested
            if auto_run_app:
                return run_main_application(extra_args=passthrough_args)
        else:
            print("\nExiting without refreshing token")
            return 0
    
    # If we get here, token is valid but auto_run_app is False
    print("\nKite API token is valid and ready to use.")
    choice = input("\nStart G6 Platform now? (y/n): ")
    
    if choice.lower().startswith("y"):
        return run_main_application(extra_args=passthrough_args)
    else:
        print("\nYou can start G6 Platform manually with:")
        print("python -m src.unified_main --help\n")
        return 0

if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user (clean shutdown)")
        rc = 0
    sys.exit(rc)