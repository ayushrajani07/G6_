#!/usr/bin/env python3
"""
Kite API Token Manager for G6 Platform

Features:
- Validates existing access tokens
- Multiple token refresh options
- Automatically runs main application after successful validation
"""

import getpass
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypedDict, cast

from src.error_handling import handle_api_error, handle_critical_error

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("token-manager")

# Suppress Flask development server logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

def load_env_vars() -> bool:
    """Load environment variables from .env file if available.

    Behavior:
    - Prefer python-dotenv when installed.
    - If not installed or load fails, perform a minimal fallback loader that reads
      a .env file in the current working directory and sets KEY=VALUE pairs into os.environ.
    Returns True if any mechanism succeeded (best-effort), else False.
    """
    used = False
    try:
        from dotenv import load_dotenv  # local import to avoid hard dependency
        try:
            load_dotenv()
            logger.info("Environment variables loaded from .env file")
            used = True
        except Exception as e:  # pragma: no cover - defensive
            try:
                handle_api_error(e, component="token_manager", context={"op": "load_env"})
            except Exception:
                pass
            logger.warning("Error loading .env via python-dotenv: %s", e)
    except Exception:
        logger.debug("python-dotenv not installed; attempting manual .env parse")
    # Fallback manual loader if .env present in CWD, or overlay if required keys are still missing
    need_overlay = (os.environ.get("KITE_API_KEY") is None or os.environ.get("KITE_API_SECRET") is None)
    if not used or need_overlay:
        try:
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip(); v = v.strip()
                        if k:
                            # Do not overwrite existing explicit environment; only fill in missing
                            if os.environ.get(k) is None:
                                os.environ[k] = v
                logger.info("Environment variables loaded via fallback .env parser (overlay=%s)", need_overlay)
                used = True or used
        except Exception as e:
            logger.debug("Fallback .env parse failed: %s", e)
    return used

class ProfileDict(TypedDict, total=False):
    user_name: str
    userName: str

class SessionDict(TypedDict, total=False):
    access_token: str


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort conversion of arbitrary mapping-like object to dict[str, Any].

    Avoids broad type: ignore usage by normalizing keys to str when possible.
    """
    if isinstance(obj, dict):  # fast path retains original dict
        # Ensure keys are strings; if not, coerce via comprehension
        if all(isinstance(k, str) for k in obj.keys()):
            return cast(dict[str, Any], obj)
        return {str(k): v for k, v in obj.items()}
    if isinstance(obj, Mapping):
        return {str(k): v for k, v in obj.items()}
    if isinstance(obj, Iterable):  # Treat as sequence of pair-likes
        try:
            tentative = dict(cast(Iterable[tuple[Any, Any]], obj))
        except Exception:
            return {}
        if not tentative:
            return {}
        if not all(isinstance(k, str) for k in tentative.keys()):
            tentative = {str(k): v for k, v in tentative.items()}
        return tentative
    return {}


def _kite_validate_token(api_key: str, access_token: str) -> bool:
    """Legacy Kite-specific validation kept for fallback paths.

    New provider aware paths should prefer provider.validate().
    """
    if not api_key or not access_token:
        logger.warning("API key or access token is missing")
        return False
    verbose = os.environ.get("G6_KITE_AUTH_VERBOSE", "").lower() in {"1","true","yes","on"}
    try:  # defer import so fake provider scenarios don't require kiteconnect
        from kiteconnect import KiteConnect  # optional dep
        try:
            from kiteconnect.exceptions import TokenException  # type: ignore
        except Exception:  # pragma: no cover - older versions or import shape changes
            TokenException = Exception  # type: ignore
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        try:
            raw = kite.profile()
        except TokenException as te:  # Expected path for stale / invalid token
            msg = str(te)
            if not verbose and "Incorrect `api_key` or `access_token`" in msg:
                # Suppress noisy stack + error handler escalation; this is a normal invalidation event
                logger.warning("Token invalid (expected case) – %s", msg)
                return False
            # Verbose or unexpected message: fall through to generic handler
            raise
        profile = cast(ProfileDict, _to_dict(raw))
        user_name = profile.get('user_name') or profile.get('userName') or 'Unknown'
        logger.info("Token is valid. Logged in as: %s", user_name)
        return True
    except Exception as e:  # noqa: BLE001
        # Only escalate to generic error handler if verbose or not a common invalid token scenario
        if verbose:
            try:
                handle_api_error(e, component="token_manager", context={"op": "validate_token"})
            except Exception:
                pass
        logger.warning("Token validation failed: %s", e)
        return False


def provider_validate_token(provider, api_key: str, access_token: str) -> bool:
    """Generic provider validation wrapper with error shielding."""
    if not api_key or not access_token:
        return False
    try:
        return bool(provider.validate(api_key, access_token))
    except Exception as e:  # noqa: BLE001
        logger.warning("Provider '%s' validation error: %s", getattr(provider, 'name', '?'), e)
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
    if access_token and _kite_validate_token(api_key, access_token):
        return True
    # Automated browser-based flow
    if auto_open_browser:
        try:
            new_tok = flask_login_server(api_key, api_secret, auto_run_app=False)
            if new_tok and (not validate_after or _kite_validate_token(api_key, new_tok)):
                return True
        except Exception as e:
            try:
                handle_api_error(e, component="token_manager", context={"op": "auto_acquire"})
            except Exception:
                pass
            logger.warning(f"Automated token acquisition failed: {e}")
    # Interactive guided/manual flow
    if interactive:
        try:
            new_tok = guided_token_refresh(api_key, api_secret, auto_run_app=False)
            if new_tok and (not validate_after or _kite_validate_token(api_key, new_tok)):
                return True
        except Exception as e:
            try:
                handle_api_error(e, component="token_manager", context={"op": "guided_refresh"})
            except Exception:
                pass
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
        with open(env_file) as f:
            for line in f:
                if not line.startswith(f"{key}="):
                    lines.append(line.rstrip("\n"))

    # Add or update the key
    lines.append(f"{key}={value}")

    # Write back to file
    with open(env_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    # Also update current process environment so subsequent in-process orchestrator
    # launches without spawning a new process see the
    # refreshed credential immediately. This was missing earlier and caused the
    # provider to initialize with a stale/empty token even after a successful
    # browser login.
    try:
        os.environ[key] = value
    except Exception:
        pass
    logger.info(f"Updated {key} in {env_file} (in-memory env refreshed)")

def _prompt_api_credentials_interactive() -> tuple[str | None, str | None]:
    """Prompt the user for Kite API credentials interactively.

    Returns a tuple (api_key, api_secret). Any missing field returns as None.
    Secrets are read using getpass to avoid echoing to console.
    """
    print("\nKite API credentials are required. Enter them now to continue.")
    try:
        api_key = input("KITE_API_KEY: ").strip()
    except Exception:
        api_key = None
    try:
        api_secret = getpass.getpass("KITE_API_SECRET (hidden): ").strip()
    except Exception:
        api_secret = None
    api_key = api_key or None
    api_secret = api_secret or None
    return api_key, api_secret

def run_main_application(extra_args: list[str] | None = None):
    """Run the G6 orchestrator loop via the canonical runner script.

    Legacy unified_main fallback removed (2025-09-28). Any attempt to import
    or invoke it will raise RuntimeError. This function now only dispatches to
    `scripts/run_orchestrator_loop.py` and returns that process' exit code.
    """
    if extra_args is None:
        extra_args = []
    orchestrator_script = Path('scripts') / 'run_orchestrator_loop.py'
    if not orchestrator_script.exists():
        logger.error("Orchestrator runner script missing: %s. Repository may be incomplete.", orchestrator_script)
        return 1
    cmd = [sys.executable, str(orchestrator_script), *extra_args]
    try:
        logger.info("Launching orchestrator loop: %s", ' '.join(cmd))
        result = subprocess.run(cmd)
        return int(result.returncode)
    except Exception as e:  # noqa: BLE001
        try:
            handle_critical_error(e, component="token_manager", context={"op": "run_orchestrator"})
        except Exception:
            pass
        logger.error("Failed to launch orchestrator loop: %s", e)
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
        from flask import Flask, request  # optional dep
        from kiteconnect import KiteConnect  # optional dep
    except ImportError as e:
        logger.error("Flask and/or kiteconnect packages are not installed")
        try:
            handle_api_error(e, component="token_manager", context={"op": "import_flask_kite"})
        except Exception:
            pass
        print("\nPlease install required packages:")
        print("pip install flask kiteconnect")
        return None

    # Create Flask app
    app = Flask(__name__)

    # Variable to store access token
    access_token_container = {'token': None, 'received': False}

    # Create Kite connect instance
    kite = KiteConnect(api_key=api_key)

    # Determine callback host/port/path from environment
    cb_host = os.environ.get("KITE_REDIRECT_HOST", "127.0.0.1")
    try:
        cb_port = int(os.environ.get("KITE_REDIRECT_PORT", "5000"))
    except Exception:
        cb_port = 5000
    cb_path = os.environ.get("KITE_REDIRECT_PATH", "success").lstrip("/") or "success"

    # Define the registered redirect URI path
    # IMPORTANT: This must match exactly what's registered in your Kite Connect API console
    @app.route(f'/{cb_path}')  # Default redirect path
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

    @app.route('/favicon.ico')
    def favicon_route():
        return ("", 204)

    def handle_callback():
        """Common handler for all callback routes."""
        try:
            logger.info(f"Callback hit: path={request.path} args={dict(request.args)}")
        except Exception:
            pass
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
            try:
                handle_api_error(e, component="token_manager", context={"op": "exchange_request_token"})
            except Exception:
                pass
            logger.error(f"Error exchanging request token: {e}")
            return f"Error: {str(e)}", 500

    # Start Flask server in a separate thread
    def run_flask():
        app.run(host=cb_host, port=cb_port, debug=False)

    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    # Allow the server to start
    time.sleep(1)

    # Generate login URL - specify the correct redirect URI
    redirect_uri = f"http://{cb_host}:{cb_port}/{cb_path}"  # Must match registered URL in Kite console

    # Obtain login URL (omit redirect kwarg for broad compatibility)
    try:
        login_url = kite.login_url()
    except Exception as e:
        try:
            handle_api_error(e, component="token_manager", context={"op": "login_url"})
        except Exception:
            pass
        logger.error(f"Unable to generate login URL: {e}")
        return None

    print("\n" + "=" * 80)
    print("Kite API Authentication")
    print("=" * 80)
    print("\n🔑 Opening browser for Kite login...")
    print("If it doesn't auto-open, copy/paste this URL into your browser:\n")
    print(f"{login_url}\n")
    print("Configured redirect (must match in Kite console):")
    print(f"{redirect_uri}\n")

    # Open browser to login URL
    try:
        webbrowser.open(login_url)
    except Exception:
        pass

    # Wait for callback to complete
    print("Waiting for authentication to complete...\n")

    timeout = int(os.environ.get("KITE_LOGIN_TIMEOUT", "180"))  # seconds
    start_time = time.time()

    while not access_token_container['received'] and time.time() - start_time < timeout:
        time.sleep(0.5)
        sys.stdout.write(".")
        sys.stdout.flush()
        # Allow manual override via env if user pasted request token externally
        if not access_token_container['received']:
            manual_rt = os.environ.get("KITE_REQUEST_TOKEN")
            if manual_rt:
                try:
                    raw_session = kite.generate_session(manual_rt, api_secret=api_secret)
                    session_data = cast(SessionDict, _to_dict(raw_session))
                    access_token = session_data.get('access_token')
                    if access_token:
                        access_token_container['token'] = access_token
                        access_token_container['received'] = True
                        logger.info("Token acquired using KITE_REQUEST_TOKEN from environment")
                        break
                except Exception as e:
                    try:
                        handle_api_error(e, component="token_manager", context={"op": "env_request_token"})
                    except Exception:
                        pass
                    logger.error(f"Error using KITE_REQUEST_TOKEN: {e}")

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
        print("Tip: Ensure your Redirect URL in Kite developer console EXACTLY matches the above 'Configured redirect'.")
        print("Alternatively, run 'python -m src.tools.token_manager' and choose guided manual refresh to paste the request_token.")
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

        logger.info("New access token generated successfully")

        # Run main application automatically if requested
        if auto_run_app:
            run_main_application()

        return access_token

    except Exception as e:
        try:
            handle_api_error(e, component="token_manager", context={"op": "guided_refresh"})
        except Exception:
            pass
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
    parser.add_argument('--provider', default=None, help='Token provider (env G6_TOKEN_PROVIDER overrides). Default: kite')
    parser.add_argument('--headless', action='store_true', help='Force headless token acquisition (or env G6_TOKEN_HEADLESS=1)')
    parser.add_argument('--', dest='passthrough', help=argparse.SUPPRESS)  # placeholder (not used directly)
    # We capture unknown args AFTER parsing known ones
    known_args, unknown_args = parser.parse_known_args()
    auto_run_app = not known_args.no_autorun
    passthrough_args = unknown_args  # list[str]
    provider_name = (known_args.provider or os.environ.get('G6_TOKEN_PROVIDER') or 'kite').lower()
    headless = bool(known_args.headless or os.environ.get('G6_TOKEN_HEADLESS') == '1')

    # Lazy import provider registry (optional deps inside providers handled there)
    try:
        from src.tools.token_providers import get_provider
        provider = get_provider(provider_name)
    except Exception as e:  # noqa: BLE001
        logger.error("Unable to initialize provider '%s': %s", provider_name, e)
        return 1
    logger.info("Using token provider: %s", getattr(provider, 'name', provider_name))

    # Load environment variables
    load_env_vars()

    # Get API credentials
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")

    # Check if we have the required credentials; offer interactive entry outside tests/headless
    if not api_key or not api_secret:
        # Avoid blocking tests/CI
        if 'PYTEST_CURRENT_TEST' in os.environ or os.environ.get('G6_TOKEN_HEADLESS') == '1':
            logger.error("API key or secret missing and interactive prompt disabled (tests/headless)")
            print("\nPlease create a .env file with the following contents:")
            print("\nKITE_API_KEY=your_api_key_here")
            print("KITE_API_SECRET=your_api_secret_here\n")
            return 1
        # Interactive prompt path
        api_key_in, api_secret_in = _prompt_api_credentials_interactive()
        if not api_key_in or not api_secret_in:
            logger.error("API key/secret not provided; cannot continue")
            return 1
        update_env_file("KITE_API_KEY", api_key_in)
        update_env_file("KITE_API_SECRET", api_secret_in)
        api_key, api_secret = api_key_in, api_secret_in

    # Check token validity
    logger.info("Checking for existing access token...")
    token_valid = False
    if access_token:
        logger.info("Found existing access token, validating via provider...")
        token_valid = provider_validate_token(provider, api_key, access_token)

    # If token is valid and auto_run_app is True, run the main application
    if token_valid and auto_run_app:
        return run_main_application(extra_args=passthrough_args)
    # If token is valid, autorun disabled, and we're in headless mode or using a non-kite provider
    # exit immediately without any interactive prompt.
    if token_valid and not auto_run_app and (headless or getattr(provider, 'name', '') != 'kite'):
        logger.info("Fast-exit: valid token, autorun disabled, headless=%s provider=%s", headless, getattr(provider,'name','?'))
        print("\nToken is valid. Headless or non-kite provider selected; exiting without interactive prompt.")
        return 0

    # If token is invalid or missing, offer options
    if not token_valid:
        # First attempt: provider-driven acquisition (non-headless for now)
        try:
            new_tok = provider.acquire(api_key=api_key, api_secret=api_secret, headless=headless, interactive=not headless)
        except TypeError:
            # Backwards compatibility if provider implementations change signature
            try:
                new_tok = provider.acquire(api_key, api_secret)
            except Exception as e:  # noqa: BLE001
                logger.error("Provider acquisition error: %s", e)
                new_tok = None
        except Exception as e:  # noqa: BLE001
            logger.error("Provider acquisition error: %s", e)
            new_tok = None
        if new_tok:
            update_env_file("KITE_ACCESS_TOKEN", new_tok)
            if provider_validate_token(provider, api_key, new_tok):
                logger.info("Token acquired via provider '%s'", provider.name)
                if auto_run_app:
                    return run_main_application(extra_args=passthrough_args)
                else:
                    print("\nToken acquired and stored. Autorun disabled.")
                    return 0
            else:
                logger.warning("Provider returned token but validation failed; falling back to legacy menu for kite provider.")

        # If provider is NOT kite, do not show interactive legacy menu (only kite implements those UX paths currently)
        if getattr(provider, 'name', '') != 'kite' or headless:
            logger.error("Unable to acquire valid token via provider '%s'", provider.name)
            return 1

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
            if not provider_validate_token(provider, api_key, access_token):
                logger.error("The entered token is invalid")
                return 1

            # Run main application automatically if requested
            if auto_run_app:
                return run_main_application(extra_args=passthrough_args)
        else:
            print("\nExiting without refreshing token")
            return 0

    # If we get here, token is valid but auto_run_app is False.
    # For headless mode or non-kite providers we should avoid any interactive prompt and just exit cleanly.
    if headless or getattr(provider, 'name', '') != 'kite':
        print("\nToken is valid. Headless or non-kite provider selected; exiting without interactive prompt.")
        return 0

    print("\nKite API token is valid and ready to use.")
    try:
        choice = input("\nStart G6 Platform now? (y/n): ")
    except OSError:
        # In constrained (e.g., pytest captured) environments fallback to non-interactive safe exit
        logger.debug("StdIn not available for interactive prompt; returning 0.")
        return 0

    if choice.lower().startswith("y"):
        return run_main_application(extra_args=passthrough_args)
    else:
        print("\nYou can start G6 Platform manually with:")
        print("python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60\n")
        return 0

if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user (clean shutdown)")
        rc = 0
    sys.exit(rc)
