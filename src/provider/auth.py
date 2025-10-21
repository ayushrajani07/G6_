"""Auth manager with centralized config integration.

Enhancements:
- Centralized credential discovery via ProviderConfig
- Late refresh if credentials appear after process start
- Explicit credential update path produces new snapshot + optional client rebuild
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .config import ProviderConfig, get_provider_config, update_provider_credentials
from .errors import (
    ProviderAuthError,
    ProviderFatalError,
    ProviderRecoverableError,
    classify_provider_exception,
)
from .logging_events import emit_event
from .metrics_adapter import metrics

logger = logging.getLogger(__name__)

class AuthManager:
    """Manages Kite client lifecycle with centralized configuration."""
    def __init__(self, api_key: str | None = None, access_token: str | None = None, *, cfg: ProviderConfig | None = None) -> None:
        self._cfg: ProviderConfig = cfg or get_provider_config()
        if api_key or access_token:
            self._cfg = self._cfg.with_updates(api_key=api_key, access_token=access_token)
        self._client: Any | None = None
        self._auth_failed = False
        self._last_log_ts = 0.0

    # --- throttle helper -------------------------------------------------
    def _allow_log(self, interval: float = 5.0) -> bool:
        now = time.time()
        if (now - self._last_log_ts) > interval:
            self._last_log_ts = now
            return True
        return False

    # --- public API ------------------------------------------------------
    def ensure_client(self) -> None:  # pragma: no cover (kiteconnect external)
        if self._client is not None or self._auth_failed:
            return
        # Late discovery if snapshot incomplete
        if not self._cfg.is_complete():
            refreshed = get_provider_config(refresh=True)
            if refreshed.is_complete():
                self._cfg = refreshed
                if self._allow_log():
                    logger.info("auth.env.credentials.discovered late_init=1")
            else:
                return
        try:
            from kiteconnect import KiteConnect  # type: ignore
            kc = KiteConnect(api_key=self._cfg.api_key)  # type: ignore[arg-type]
            kc.set_access_token(self._cfg.access_token)  # type: ignore[arg-type]
            self._client = kc
            metrics().incr("provider_auth_init_total", status="ok")
            emit_event(logger, "provider.auth.init", status="ok", method="lazy")
            if self._allow_log():
                logger.info("auth.client.initialized method=lazy")
        except Exception as e:  # pragma: no cover
            self._auth_failed = True
            metrics().incr("provider_auth_init_total", status="fail")
            emit_event(logger, "provider.auth.init", status="fail")
            if self._allow_log():
                logger.warning("auth.client.init_failed err=%s", e)
            err_cls = classify_provider_exception(e)
            if err_cls is ProviderAuthError:
                raise ProviderAuthError(str(e)) from e
            elif err_cls is ProviderRecoverableError:
                raise ProviderRecoverableError(str(e)) from e
            elif err_cls.__name__ == 'ProviderTimeoutError':
                raise err_cls(str(e)) from e
            else:
                raise ProviderFatalError(str(e)) from e

    def update_credentials(self, api_key: str | None = None, access_token: str | None = None, rebuild: bool = True) -> None:
        if api_key or access_token:
            self._cfg = self._cfg.with_updates(api_key=api_key, access_token=access_token)
            update_provider_credentials(api_key=self._cfg.api_key, access_token=self._cfg.access_token)
        if rebuild:
            self._auth_failed = False
            self._client = None
            self.ensure_client()
        else:
            if self._allow_log():
                logger.info("auth.credentials.updated rebuild=0")

    @property
    def client(self) -> Any | None:
        return self._client

    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    @property
    def config(self) -> ProviderConfig:
        return self._cfg
