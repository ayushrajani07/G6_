from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from typing import TYPE_CHECKING, Any, cast

from kiteconnect import KiteConnect  # optional external dependency

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    try:
        from flask import Flask, Request  # type: ignore
    except Exception:  # noqa: BLE001
        Flask = object  # type: ignore
        Request = object  # type: ignore

logger = logging.getLogger("token-provider.kite")


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)  # potential mapping conversion
    except Exception:  # noqa: BLE001
        return {}


class KiteTokenProvider:
    name = "kite"

    def validate(self, api_key: str, access_token: str) -> bool:  # noqa: D401
        if not api_key or not access_token:
            return False
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            raw = kite.profile()
            profile = cast(dict, _to_dict(raw))
            logger.info("Validated token; user=%s", profile.get('user_name') or profile.get('userName'))
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Token validation failed: %s", e)
            return False

    def acquire(
        self,
        api_key: str,
        api_secret: str,
        headless: bool = False,
        interactive: bool = True,
    ) -> str | None:  # noqa: D401
        # Headless mode: no browser or interactive prompt; rely on KITE_REQUEST_TOKEN env
        if headless:
            manual_rt = os.environ.get("KITE_REQUEST_TOKEN")
            if not manual_rt:
                logger.error("Headless mode: KITE_REQUEST_TOKEN not set; cannot acquire token")
                return None
            try:
                kite = KiteConnect(api_key=api_key)
                raw_session = kite.generate_session(manual_rt, api_secret=api_secret)
                token = _to_dict(raw_session).get("access_token")
                if token:
                    return token
            except Exception as e:  # noqa: BLE001
                logger.error("Headless token exchange failed: %s", e)
            return None

        # Non-headless automated browser flow (minimal inline variant to avoid duplicating full logic)
        try:
            from flask import Flask, request
        except Exception:  # noqa: BLE001
            logger.error("Flask not installed; cannot run automated browser flow. Install flask or use headless.")
            if interactive:
                return self._interactive(api_key, api_secret)
            return None

        kite = KiteConnect(api_key=api_key)
        try:
            login_url = kite.login_url()
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get login URL: %s", e)
            if interactive:
                return self._interactive(api_key, api_secret)
            return None

        cb_host = os.environ.get("KITE_REDIRECT_HOST", "127.0.0.1")
        try:
            cb_port = int(os.environ.get("KITE_REDIRECT_PORT", "5000"))
        except Exception:  # noqa: BLE001
            cb_port = 5000
        cb_path = os.environ.get("KITE_REDIRECT_PATH", "success").lstrip("/") or "success"

        app = Flask(__name__)
        container: dict[str, str | None] = {"token": None}

        @app.route(f"/{cb_path}")
        @app.route("/callback")
        @app.route("/")
        def _cb():
            status = request.args.get("status")
            request_token = request.args.get("request_token")
            if status != "success" or not request_token:
                return "Missing/invalid request token", 400
            try:
                raw_session = kite.generate_session(request_token, api_secret=api_secret)
                token = _to_dict(raw_session).get("access_token")
                if token:
                    container["token"] = token
                    return "Token acquired. You may close this window.", 200
            except Exception as e:  # noqa: BLE001
                logger.error("Callback exchange failed: %s", e)
            return "Exchange failed", 500

        def _run():  # pragma: no cover - network server
            app.run(host=cb_host, port=cb_port, debug=False)

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        time.sleep(0.5)
        try:
            webbrowser.open(login_url)
        except Exception:  # noqa: BLE001
            logger.info("Unable to auto-open browser; open manually: %s", login_url)
        deadline = time.time() + int(os.environ.get("KITE_LOGIN_TIMEOUT", "180"))
        while time.time() < deadline and not container["token"]:
            time.sleep(0.5)
            sys.stdout.write('.')
            sys.stdout.flush()
        sys.stdout.write('\n')
        return container["token"]

    # Interactive manual path
    def _interactive(self, api_key: str, api_secret: str) -> str | None:
        try:
            kite = KiteConnect(api_key=api_key)
            login_url = kite.login_url()
            print("Open this URL, login, copy the request_token parameter, then paste it below:\n")
            print(login_url)
            request_token = input("request_token: ").strip()
            if not request_token:
                return None
            raw_session = kite.generate_session(request_token, api_secret=api_secret)
            token = _to_dict(raw_session).get("access_token")
            return token
        except Exception as e:  # noqa: BLE001
            logger.error("Interactive token acquisition failed: %s", e)
            return None
