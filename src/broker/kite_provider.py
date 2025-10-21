#!/usr/bin/env python3
"""Primary Kite provider facade (post modular Phases 1–8).

Reconstructed after extraction phases:
  * Expiry resolution -> src.broker.kite.expiries
  * Option filtering  -> src.broker.kite.options
  * Quote / LTP logic -> src.broker.kite.quotes
  * Dummy provider    -> src.broker.kite.dummy_provider

This module now focuses on light orchestration: wiring settings, state, client,
rate limiting, caching, and delegating to specialized modules. Public API and
behaviour are kept broadly backwards compatible for tests and existing code.
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
import warnings
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Protocol

# Re-export DummyKiteProvider for backwards compatibility
from src.broker.kite.dummy_provider import DummyKiteProvider  # noqa: F401
from src.broker.kite.settings import Settings, load_settings
from src.broker.kite.state import ProviderState
from src.provider.errors import (
    ProviderAuthError,
    ProviderFatalError,
    ProviderRecoverableError,
    ProviderTimeoutError,
    classify_provider_exception,
)
from src.utils.deprecations import emit_deprecation  # type: ignore
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Internal error taxonomy raise helper (reduces duplication after instrumentation)
# ----------------------------------------------------------------------------
def _raise_classified(e: BaseException):  # pragma: no cover - thin utility
    """Classify raw exception and raise the mapped Provider* error.

    Maintains existing behavior: message preserved, original chained for trace.
    Centralizing this logic reduces the repetitive if/elif cascade making future
    taxonomy adjustments (e.g., introducing ProviderThrottledError) simpler.
    """
    err_cls = classify_provider_exception(e)
    if err_cls is ProviderAuthError:
        raise ProviderAuthError(str(e)) from e
    if err_cls is ProviderTimeoutError:
        raise ProviderTimeoutError(str(e)) from e
    if err_cls is ProviderRecoverableError:
        raise ProviderRecoverableError(str(e)) from e
    raise ProviderFatalError(str(e)) from e

# ----------------------------------------------------------------------------
# Deprecation warning message constants (centralized to prevent drift)
# ----------------------------------------------------------------------------
DEPRECATION_MSG_DIRECT_CREDENTIALS = (
    "Passing api_key/access_token directly to KiteProvider is deprecated; "
    "use ProviderConfig (get_provider_config().with_updates(...)) or kite_provider_factory() instead."
)
DEPRECATION_MSG_FROM_ENV = (
    "KiteProvider.from_env removed legacy env scanning; now strictly uses ProviderConfig snapshot."
)
DEPRECATION_MSG_FACTORY_IMPLICIT = (
    "Implicit env credential construction via create_provider('kite', {}) is deprecated; "
    "pass explicit overrides or use kite_provider_factory() with overrides for silence."
)
DEPRECATION_MSG_IMPLICIT_ENV_HELPER = (
    "Implicit env-sourced credentials path is deprecated; prefer explicit ProviderConfig layering or overrides."
)

# ----------------------------------------------------------------------------
# Concise logging flag migration (A23 cleanup):
# The legacy module-level `_CONCISE` export is being deprecated. Downstream
# code should call `is_concise_logging()` (new helper) or inspect a provider
# instance's settings. We keep a private `_legacy_concise` during migration
# to satisfy any still-active imports until A24 when it will be removed.
# ----------------------------------------------------------------------------
try:  # derive initial concise value from settings once to avoid duplicate env parses
    _BOOT_SETTINGS = load_settings()
    _legacy_concise = bool(getattr(_BOOT_SETTINGS, 'concise', True))
except Exception:  # pragma: no cover - very unlikely
    _BOOT_SETTINGS = None  # type: ignore
    _legacy_concise = True

def is_concise_logging() -> bool:
    """Return current concise logging mode (migration safe).

    Prefers live provider settings when a KiteProvider instance updates the
    mode via enable_concise_logs; falls back to the boot snapshot.
    """
    return bool(_legacy_concise)

# ----------------------------------------------------------------------------
# Index + exchange pool mappings (minimal set used across modules/tests)
# ----------------------------------------------------------------------------
INDEX_MAPPING: dict[str, tuple[str, str]] = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NSE", "NIFTY MIDCAP SELECT"),
    "SENSEX": ("BSE", "SENSEX"),
}
POOL_FOR: dict[str, str] = {k: "NFO" for k in INDEX_MAPPING.keys()}

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
class _KiteLike(Protocol):  # minimal protocol for type hints
    # Match KiteConnect signature (param name access_token)
    def set_access_token(self, access_token: str) -> None: ...  # pragma: no cover
    def instruments(self) -> list[dict[str, Any]] | Any: ...  # pragma: no cover
    def ltp(self, *args: Any, **kwargs: Any) -> Any: ...  # pragma: no cover
    def quote(self, *args: Any, **kwargs: Any) -> Any: ...  # pragma: no cover

def _timed_call(fn, timeout: float) -> Any:
    with ThreadPoolExecutor(max_workers=1) as exe:
        fut = exe.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            raise TimeoutError(f"operation timed out after {timeout}s")

def _is_auth_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("auth", "token", "unauthorized", "forbidden", "expired"))

def enable_concise_logs(value: bool = True):
    global _legacy_concise  # noqa: PLW0603
    _legacy_concise = value
    logger.info(f"Concise logging {'ENABLED' if _legacy_concise else 'DISABLED'} (runtime override)")

# ----------------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------------
class KiteProvider:
    """Thin orchestration facade around modular provider logic.

    Phase 10 (cleanup & deprecation):
      * Added deprecation shims for legacy direct attribute access (option cache metrics etc.).
      * Added provider_diagnostics() helper for structured inspection instead of reaching into internals.
      * Future removal notice: direct access to internal state attributes (e.g. ._state.option_instrument_cache) will be
        discouraged and eventually removed; rely on public helpers.
    """
    def __init__(
        self,
        api_key: str | None = None,
        access_token: str | None = None,
        kite_client: _KiteLike | None = None,
        settings: Settings | None = None,
    ) -> None:
        # Phase A7 Step 4: delegate .env hydration to bootstrap helper (kept for side-effects)
        try:  # pragma: no cover - best effort
            from src.broker.kite.client_bootstrap import hydrate_env as _hydrate_env
            _hydrate_env()
        except Exception:
            pass

        # Settings (reuse boot settings if any)
        self._settings = settings or _BOOT_SETTINGS or load_settings()
        global _legacy_concise  # noqa: PLW0603
        if settings is None:
            try:
                _legacy_concise = bool(getattr(self._settings, 'concise', _legacy_concise))
            except Exception:  # pragma: no cover
                pass

        # Provider configuration snapshot (no legacy env fallback now)
        from src.provider.config import get_provider_config as _get_pc  # type: ignore
        _pc = _get_pc()
        if api_key or access_token:
            _pc = _pc.with_updates(api_key=api_key, access_token=access_token)
        self._api_key = getattr(_pc, 'api_key', None)
        self._access_token = getattr(_pc, 'access_token', None)
        self._provider_config = _pc
        self.kite: _KiteLike | None = kite_client
        self._auth_failed = False

        # Initialize mutable provider state (was lost during refactor removing legacy env fallback)
        # Tests rely on _state existing for diagnostics + deprecated property shims.
        try:
            self._state = ProviderState()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            # Extremely unlikely; keep a lightweight fallback object with needed attrs
            class _FallbackState:  # pragma: no cover
                instruments_cache = {}
                instruments_cache_meta = {}
                expiry_dates_cache = {}
                option_instrument_cache = {}
                option_cache_hits = 0
                option_cache_misses = 0
            self._state = _FallbackState()  # type: ignore

        # Emit a deprecation warning once when credentials are supplied directly (tests assert this)
        # Now that ProviderConfig is authoritative, direct constructor credentials are transitional.
        if (api_key or access_token):  # user passed explicit credentials
            warnings.warn(DEPRECATION_MSG_DIRECT_CREDENTIALS, DeprecationWarning, stacklevel=2)

        # Rate limiter (delegated to provider_core helper)
        try:
            from src.broker.kite.provider_core import setup_rate_limiter as _setup_rl_core
            rl, last_log, last_quote = _setup_rl_core(self._settings)
            self._api_rl = rl
            self._rl_last_log_ts = last_log
            self._rl_last_quote_log_ts = last_quote
        except Exception:  # pragma: no cover
            ms = getattr(self._settings, 'kite_throttle_ms', 0) or 0
            self._api_rl = RateLimiter(ms / 1000.0) if ms > 0 else None
            self._rl_last_log_ts = 0.0
            self._rl_last_quote_log_ts = 0.0

        # Legacy synthetic fallback counters removed (Aggressive cleanup 2025-10-08)
        # Placeholders retained only to avoid AttributeError in any straggler code; values fixed.
        self._synthetic_quotes_used = 0  # deprecated – always zero
        self._last_quotes_synthetic = False  # deprecated – always False
        self._used_fallback = False  # unrelated legacy flag kept

        # Delegate initial client creation if credentials are present
        try:
            from src.broker.kite.client_bootstrap import build_client_if_possible as _build_client
            _build_client(self)
        except Exception:  # pragma: no cover
            pass

        # Phase A7 Step 5: startup summary emission via provider_core
        try:
            from src.broker.kite.provider_core import emit_startup_summary_if_needed as _emit_core
            _emit_core(self)
        except Exception:  # pragma: no cover
            pass

    # --- late / lazy client initialization ---------------------------------
    def _ensure_client(self) -> None:  # backward compatibility shim (delegates)
        try:
            from src.broker.kite.auth import ensure_client_auth as _ensure
            _ensure(self)
        except Exception:  # pragma: no cover
            pass

    # --- explicit credential update ---------------------------------------
    def update_credentials(self, api_key: str | None = None, access_token: str | None = None, rebuild: bool = True) -> None:  # delegate
        try:
            from src.broker.kite.auth import update_credentials_auth as _update
            _update(self, api_key=api_key, access_token=access_token, rebuild=rebuild)
        except Exception:  # pragma: no cover
            pass

    # --- construction helpers ---------------------------------------------
    @classmethod
    def from_env(cls):  # pragma: no cover - tiny wrapper, exercised by test
        import warnings
        warnings.warn(DEPRECATION_MSG_FROM_ENV, DeprecationWarning, stacklevel=2)
        snap = _get_pc()
        # Constructor will emit deprecation warning if credentials passed; suppress duplicate warning here
        with warnings.catch_warnings():  # avoid double emission in tests
            warnings.simplefilter('ignore', DeprecationWarning)
            return cls(api_key=snap.api_key, access_token=snap.access_token)

    @classmethod
    def from_provider_config(cls, cfg):  # type: ignore[override]
        """Instantiate from a ProviderConfig snapshot (duck-typed)."""
        # Suppress constructor deprecation warning for the canonical ProviderConfig path
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            return cls(api_key=getattr(cfg, 'api_key', None), access_token=getattr(cfg, 'access_token', None))

    # --- lifecycle ---------------------------------------------------------
    def close(self) -> None:  # pragma: no cover - graceful no-op
        """Best-effort resource cleanup hook (kept for parity / tests)."""
        try:
            kc = getattr(self, 'kite', None)
            # kiteconnect does not expose explicit close; if future client exposes .close(), call it
            if kc and hasattr(kc, 'close'):
                try:
                    kc.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass

    # --- context manager support -----------------------------------------
    def __enter__(self):  # pragma: no cover - thin wrapper
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - thin wrapper
        try:
            self.close()
        finally:
            return False  # do not suppress exceptions

    # --- internal RL helpers ------------------------------------------------
    def _rl_fallback(self) -> bool:  # delegate to helper logic
        try:
            from src.broker.kite.rate_limiter_helpers import log_allowed as _allowed
            # Use ephemeral dict referencing existing timestamps to avoid state drift
            flags = {'last_log_ts': self._rl_last_log_ts}
            ok = _allowed(flags)
            self._rl_last_log_ts = flags['last_log_ts']
            return ok
        except Exception:  # pragma: no cover
            now = time.time()
            if now - self._rl_last_log_ts > 5.0:
                self._rl_last_log_ts = now
                return True
            return False

    def _rl_quote_fallback(self) -> bool:  # delegate to helper logic
        try:
            from src.broker.kite.rate_limiter_helpers import quote_log_allowed as _q_allowed
            flags = {'last_quote_log_ts': self._rl_last_quote_log_ts}
            ok = _q_allowed(flags)
            self._rl_last_quote_log_ts = flags['last_quote_log_ts']
            return ok
        except Exception:  # pragma: no cover
            now = time.time()
            if now - self._rl_last_quote_log_ts > 5.0:
                self._rl_last_quote_log_ts = now
                return True
            return False

    # --- token refresh stub -------------------------------------------------
    def maybe_refresh_token_proactively(self) -> None:  # pragma: no cover
        return

    # --- instruments --------------------------------------------------------
    def get_instruments(self, exchange: str | None = None, force_refresh: bool = False) -> list[dict[str, Any]]:
        exch = exchange or "NFO"
        # Local import to avoid overhead when logging disabled
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("instruments", "fetch", exchange=exch, force_refresh=force_refresh) as evt:
            try:
                from src.broker.kite.instruments import fetch_instruments as _fetch_impl
                data = _fetch_impl(self, exch, force_refresh=force_refresh)
                try:
                    evt.add_field("instruments_count", len(data))
                except Exception:  # pragma: no cover
                    pass
                return data
            except Exception as e:  # pragma: no cover
                err_cls = classify_provider_exception(e)
                evt.add_field("error_class", err_cls.__name__)
                logger.error("provider.instruments.fail cls=%s err=%s", err_cls.__name__, e)
                _raise_classified(e)

    # --- quotes / LTP -------------------------------------------------------
    def get_ltp(self, instruments: Iterable[tuple[str, str]] | Iterable[str]):
        from src.broker.kite.provider_events import provider_event  # type: ignore
        # Attempt to derive a simple count for observability (works for list/tuple or set)
        try:
            requested = len(list(instruments))  # list() in case of generator (small typical)
        except Exception:  # pragma: no cover
            requested = 0
        with provider_event("quotes", "ltp", instruments_requested=requested) as evt:
            try:
                from src.broker.kite.quotes import get_ltp as _impl
                data = _impl(self, instruments)
                # data is expected to be a mapping of instrument->price
                try:
                    evt.add_field("returned", len(data) if hasattr(data, '__len__') else 0)
                except Exception:  # pragma: no cover
                    pass
                return data
            except Exception as e:  # pragma: no cover
                err_cls = classify_provider_exception(e)
                evt.add_field("error_class", err_cls.__name__)
                logger.error("provider.ltp.fail cls=%s err=%s", err_cls.__name__, e)
                _raise_classified(e)

    def get_quote(self, instruments: Iterable[tuple[str, str]] | Iterable[str]):
        from src.broker.kite.provider_events import provider_event  # type: ignore
        try:
            requested = len(list(instruments))
        except Exception:  # pragma: no cover
            requested = 0
        with provider_event("quotes", "full", instruments_requested=requested) as evt:
            try:
                from src.broker.kite.quotes import get_quote as _impl
                data = _impl(self, instruments)
                try:
                    evt.add_field("returned", len(data) if hasattr(data, '__len__') else 0)
                except Exception:  # pragma: no cover
                    pass
                return data
            except Exception as e:  # pragma: no cover
                err_cls = classify_provider_exception(e)
                evt.add_field("error_class", err_cls.__name__)
                logger.error("provider.quote.fail cls=%s err=%s", err_cls.__name__, e)
                _raise_classified(e)

    # Synthetic diagnostics removed: methods retained as inert stubs for one release window.
    def pop_synthetic_quote_usage(self) -> tuple[int, bool]:  # pragma: no cover - legacy stub
        return 0, False

    def last_quotes_were_synthetic(self) -> bool:  # pragma: no cover - legacy stub
        return False

    # --- diagnostics helper -------------------------------------------------
    def provider_diagnostics(self) -> dict[str, Any]:
        try:
            from src.broker.kite.diagnostics import provider_diagnostics as _impl
        except Exception:  # pragma: no cover
            logger.error("diagnostics_import_failed", exc_info=True)
            return {}
        return _impl(self)

    # --- deprecation property shims ----------------------------------------
    def _warn_once(self, name: str):
        if not hasattr(self, '_issued_deprecation_warnings'):
            self._issued_deprecation_warnings: set[str] = set()
        if name not in self._issued_deprecation_warnings:
            emit_deprecation(
                f'kite-provider-attr-{name}',
                f"Accessing '{name}' directly is deprecated; use provider_diagnostics() for a structured snapshot."
            )
            self._issued_deprecation_warnings.add(name)

    @property
    def option_cache_hits(self) -> int:
        self._warn_once('option_cache_hits')
        return getattr(self._state, 'option_cache_hits', 0)

    @property
    def option_cache_misses(self) -> int:
        self._warn_once('option_cache_misses')
        return getattr(self._state, 'option_cache_misses', 0)

    @property
    def instruments_cache(self):  # shallow copy to avoid mutation
        self._warn_once('instruments_cache')
        try:
            return dict(getattr(self._state, 'instruments_cache', {}))
        except Exception:
            return {}

    @property
    def expiry_dates_cache(self):
        self._warn_once('expiry_dates_cache')
        try:
            return dict(getattr(self._state, 'expiry_dates_cache', {}))
        except Exception:
            return {}

    @property
    def synthetic_quotes_used(self) -> int:  # pragma: no cover - legacy stub
        self._warn_once('synthetic_quotes_used')
        return 0

    @property
    def last_quotes_synthetic_flag(self) -> bool:  # pragma: no cover - legacy stub
        self._warn_once('last_quotes_synthetic_flag')
        return False

    # --- ATM strike heuristic -----------------------------------------------
    def get_atm_strike(self, index_symbol: str) -> int:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("expiries", "atm", index=index_symbol) as evt:
            try:
                from src.broker.kite.expiry_discovery import get_atm_strike as _impl
            except Exception:  # pragma: no cover
                logger.error("expiry_discovery_import_failed_atm", exc_info=True)
                defaults = {"NIFTY": 24800, "BANKNIFTY": 54000, "FINNIFTY": 26000, "MIDCPNIFTY": 12000, "SENSEX": 81000}
                val = defaults.get(index_symbol, 20000)
                evt.add_field("fallback", True)
                evt.add_field("atm", val)
                return val
            val = _impl(self, index_symbol)
            evt.add_field("atm", val)
            return val

    # --- expiry discovery ---------------------------------------------------
    def get_expiry_dates(self, index_symbol: str) -> list[_dt.date]:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("expiries", "list", index=index_symbol) as evt:
            try:
                from src.broker.kite.expiry_discovery import get_expiry_dates as _impl
            except Exception:  # pragma: no cover
                logger.error("expiry_discovery_import_failed_expiries", exc_info=True)
                evt.add_field("fallback", True)
                return []
            dates = _impl(self, index_symbol)
            evt.add_field("count", len(dates))
            return dates

    def get_weekly_expiries(self, index_symbol: str) -> list[_dt.date]:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("expiries", "weekly", index=index_symbol) as evt:
            try:
                from src.broker.kite.expiry_discovery import get_weekly_expiries as _impl
            except Exception:  # pragma: no cover
                logger.error("expiry_discovery_import_failed_weekly", exc_info=True)
                evt.add_field("fallback", True)
                return []
            dates = _impl(self, index_symbol)
            evt.add_field("count", len(dates))
            return dates

    def get_monthly_expiries(self, index_symbol: str) -> list[_dt.date]:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("expiries", "monthly", index=index_symbol) as evt:
            try:
                from src.broker.kite.expiry_discovery import get_monthly_expiries as _impl
            except Exception:  # pragma: no cover
                logger.error("expiry_discovery_import_failed_monthly", exc_info=True)
                evt.add_field("fallback", True)
                return []
            dates = _impl(self, index_symbol)
            evt.add_field("count", len(dates))
            return dates

    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> _dt.date:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("expiries", "resolve", index=index_symbol, rule=expiry_rule) as evt:
            from src.broker.kite.expiries import resolve_expiry_rule  # local import
            try:
                chosen = resolve_expiry_rule(self, index_symbol, expiry_rule)
                evt.add_field("resolved", str(chosen))
                (logger.debug if is_concise_logging() else logger.info)(f"Resolved '{expiry_rule}' for {index_symbol} -> {chosen}")
                return chosen
            except Exception:  # pragma: no cover
                fallback = _dt.date.today()
                evt.add_field("fallback", True)
                evt.add_field("resolved", str(fallback))
                return fallback

    # --- options delegation -------------------------------------------------
    def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("options", "filter", index=index_symbol, expiry=str(expiry_date)) as evt:
            try:
                from src.broker.kite.options import option_instruments as _impl
            except Exception:  # pragma: no cover
                logger.error("options_module_import_failed", exc_info=True)
                evt.add_field("fallback", True)
                return []
            data = _impl(self, index_symbol, expiry_date, strikes)
            try:
                evt.add_field("count", len(data))
            except Exception:  # pragma: no cover
                pass
            return data

    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        return self.option_instruments(index_symbol, expiry_date, strikes)

    # --- health check -------------------------------------------------------
    def check_health(self) -> dict[str, Any]:
        from src.broker.kite.provider_events import provider_event  # type: ignore
        with provider_event("health", "check") as evt:
            try:
                from src.broker.kite.diagnostics import check_health as _impl
            except Exception:  # pragma: no cover
                logger.error("diagnostics_import_failed_health", exc_info=True)
                evt.add_field("fallback", True)
                status = {"status": "unhealthy", "message": "Diagnostics module import failed"}
                evt.add_field("status", status.get("status"))
                return status
            status = _impl(self)
            try:
                evt.add_field("status", status.get("status"))
            except Exception:  # pragma: no cover
                pass
            return status

# ----------------------------------------------------------------------------
# Public exports
# ----------------------------------------------------------------------------
__all__ = [
    "KiteProvider",
    "DummyKiteProvider",  # re-export
    "enable_concise_logs",
    "is_concise_logging",
    "INDEX_MAPPING",
    "POOL_FOR",
    "kite_provider_factory",
]

# ----------------------------------------------------------------------------
# Public convenience helper (post deprecation): kite_provider_factory
# ----------------------------------------------------------------------------
def kite_provider_factory(**overrides):
    """Return a `KiteProvider` built from the current ProviderConfig snapshot.

    Optional keyword arguments (api_key / access_token) are applied via
    ProviderConfig.with_updates() before instantiation. This avoids triggering
    the direct-constructor credential deprecation warning in test and runtime
    paths that simply need a provider instance.
    """
    from src.provider.config import get_provider_config as _get_pc  # type: ignore
    cfg = _get_pc()
    emit_dep = False
    if overrides:
        cfg = cfg.with_updates(**overrides)  # type: ignore[arg-type]
    else:
        # If credentials came purely from env (snapshot source) emit a one-time deprecation warning
        # preserving historical test expectation that creating a provider via factory without explicit
        # overrides surfaces the transition away from implicit env discovery.
        try:
            if getattr(cfg, 'source', '') == 'env' and getattr(cfg, 'complete', False):
                emit_dep = True
        except Exception:  # pragma: no cover
            pass
    if emit_dep:
        import warnings
        warnings.warn(DEPRECATION_MSG_IMPLICIT_ENV_HELPER, DeprecationWarning, stacklevel=2)
    return KiteProvider.from_provider_config(cfg)
