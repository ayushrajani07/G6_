#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import os
import time
import warnings
from src.utils.deprecations import emit_deprecation  # type: ignore
from typing import Set
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Iterable, Optional, Protocol, Dict, List

from src.broker.kite.settings import load_settings, Settings
from src.broker.kite.state import ProviderState
from src.utils.rate_limiter import RateLimiter
from src.utils.retry import call_with_retry
from src.error_handling import handle_provider_error, handle_data_collection_error

# Re-export DummyKiteProvider for backwards compatibility
from src.broker.kite.dummy_provider import DummyKiteProvider  # noqa: F401

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Concise logging flag (legacy semantics: default ON unless explicit off)
# ----------------------------------------------------------------------------
CONCISE_ENV_VAR = "G6_CONCISE_LOGS"
_raw_concise = os.environ.get(CONCISE_ENV_VAR)
if _raw_concise is None:
    _CONCISE = True
else:
    _CONCISE = _raw_concise.lower() not in ("0", "false", "no", "off")

# ----------------------------------------------------------------------------
# Index + exchange pool mappings (minimal set used across modules/tests)
# ----------------------------------------------------------------------------
INDEX_MAPPING: Dict[str, tuple[str, str]] = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NSE", "NIFTY MIDCAP SELECT"),
    "SENSEX": ("BSE", "SENSEX"),
}
POOL_FOR: Dict[str, str] = {k: "NFO" for k in INDEX_MAPPING.keys()}

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
    global _CONCISE  # noqa: PLW0603
    _CONCISE = value
    logger.info(f"Concise logging {'ENABLED' if _CONCISE else 'DISABLED'} (runtime override)")

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
        kite_client: Optional[_KiteLike] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        emit_deprecation(
            'kite-provider-init',
            'KiteProvider: direct use is stable but internal attribute access is deprecated; use provider_diagnostics() instead.',
            force=True,
        )
        self._settings = settings or load_settings()
        self._state = ProviderState()
        self._api_key = api_key or os.environ.get("KITE_API_KEY") or os.environ.get("KITE_APIKEY")
        self._access_token = access_token or os.environ.get("KITE_ACCESS_TOKEN") or os.environ.get("KITE_ACCESSTOKEN")
        self.kite: Optional[_KiteLike] = kite_client
        self._auth_failed = False

        # Rate limiter
        ms = getattr(self._settings, 'kite_throttle_ms', 0) or 0
        self._api_rl = RateLimiter(ms / 1000.0) if ms > 0 else None
        self._rl_last_log_ts = 0.0
        self._rl_last_quote_log_ts = 0.0

        # Synthetic / diagnostics counters (referenced by extracted modules)
        self._synthetic_quotes_used = 0
        self._last_quotes_synthetic = False
        self._used_fallback = False

        # Lazy create kite client if credentials supplied and not injected
        if self.kite is None and self._api_key and self._access_token:
            try:  # pragma: no cover - external dependency
                from kiteconnect import KiteConnect  # external dependency
                kc = KiteConnect(api_key=self._api_key)
                kc.set_access_token(self._access_token)
                self.kite = kc
                logger.info("Kite client initialized (lazy)")
            except Exception as e:  # pragma: no cover
                logger.debug(f"Kite client init skipped: {e}")

    # --- construction helpers ---------------------------------------------
    @classmethod
    def from_env(cls):  # pragma: no cover - tiny wrapper, exercised by test
        """Instantiate using environment variables (factory relies on this).

        Looks for KITE_API_KEY / KITE_APIKEY and KITE_ACCESS_TOKEN / KITE_ACCESSTOKEN.
        Missing values are tolerated; the provider will simply operate in synthetic
        fallback mode when real calls are attempted.
        """
        api_key = os.environ.get("KITE_API_KEY") or os.environ.get("KITE_APIKEY")
        access_token = os.environ.get("KITE_ACCESS_TOKEN") or os.environ.get("KITE_ACCESSTOKEN")
        return cls(api_key=api_key, access_token=access_token)

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
    def _rl_fallback(self) -> bool:
        now = time.time()
        if now - self._rl_last_log_ts > 5.0:
            self._rl_last_log_ts = now
            return True
        return False

    def _rl_quote_fallback(self) -> bool:
        now = time.time()
        if now - self._rl_last_quote_log_ts > 5.0:
            self._rl_last_quote_log_ts = now
            return True
        return False

    # --- token refresh stub -------------------------------------------------
    def maybe_refresh_token_proactively(self) -> None:  # pragma: no cover
        return

    # --- instruments --------------------------------------------------------
    def get_instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        exch = exchange or "NFO"
        ttl = getattr(self._settings, 'instrument_cache_ttl', 600.0)
        now = time.time()
        cached = self._state.instruments_cache.get(exch)
        meta_ts = self._state.instruments_cache_meta.get(exch, 0.0)
        if cached is not None and (now - meta_ts) < ttl:
            return cached
        try:
            if self._auth_failed:
                raise RuntimeError("kite_auth_failed")
            if self.kite is None:
                raise RuntimeError("kite_client_unavailable")
            def _fetch():
                if self._api_rl:
                    self._api_rl()
                return _timed_call(lambda: self.kite.instruments(), getattr(self._settings, 'kite_timeout_sec', 5.0))  # type: ignore[arg-type]
            raw = call_with_retry(_fetch)
            if isinstance(raw, list):
                self._state.instruments_cache[exch] = raw
                self._state.instruments_cache_meta[exch] = now
                return raw
            raise ValueError("unexpected_instruments_shape")
        except Exception as e:
            if _is_auth_error(e) or str(e) == 'kite_auth_failed':
                self._auth_failed = True
                if self._rl_fallback():
                    logger.warning("Kite auth failed; using synthetic instruments. Set KITE_API_KEY/KITE_ACCESS_TOKEN for real API.")
            else:
                if self._rl_fallback():
                    logger.debug(f"Instrument fetch failed, using synthetic: {e}")
            try:
                handle_provider_error(e, component="kite_provider.get_instruments", context={"exchange": exch})
            except Exception:
                pass
        try:
            from src.broker.kite.synthetic import generate_synthetic_instruments  # type: ignore
            synth = generate_synthetic_instruments()
        except Exception:  # pragma: no cover
            synth = []
        self._state.instruments_cache[exch] = synth
        self._state.instruments_cache_meta[exch] = now
        self._used_fallback = True
        return synth

    # --- quotes / LTP -------------------------------------------------------
    def get_ltp(self, instruments: Iterable[tuple[str, str]] | Iterable[str]):
        try:
            from src.broker.kite.quotes import get_ltp as _impl
        except Exception:  # pragma: no cover
            logger.error("quotes_module_import_failed", exc_info=True)
            return {}
        return _impl(self, instruments)

    def get_quote(self, instruments: Iterable[tuple[str, str]] | Iterable[str]):
        try:
            from src.broker.kite.quotes import get_quote as _impl
        except Exception:  # pragma: no cover
            logger.error("quotes_module_import_failed", exc_info=True)
            return {}
        return _impl(self, instruments)

    # --- synthetic quote diagnostics ---------------------------------------
    def pop_synthetic_quote_usage(self) -> tuple[int, bool]:
        try:
            cnt = int(self._synthetic_quotes_used)
            last_flag = bool(self._last_quotes_synthetic)
            self._synthetic_quotes_used = 0
            return cnt, last_flag
        except Exception:  # pragma: no cover
            return 0, False

    def last_quotes_were_synthetic(self) -> bool:
        return bool(self._last_quotes_synthetic)

    # --- diagnostics helper -------------------------------------------------
    def provider_diagnostics(self) -> dict[str, Any]:
        """Return a structured snapshot of key counters & cache stats.

        This is the preferred replacement for ad-hoc access of internal
        attributes. Keys kept stable for downstream tooling.
        """
        try:
            # Derive token age / expiry metadata if possible
            token_age_sec = None
            token_expiry = None
            try:
                # Some kiteconnect clients keep public attributes; we try common ones defensively
                kc = getattr(self, 'kite', None)
                issued = getattr(kc, 'api_token_issue_time', None)
                exp = getattr(kc, 'api_token_expiry', None)
                now_ts = time.time()
                if isinstance(issued, (int, float)):
                    token_age_sec = max(0, now_ts - float(issued))
                if isinstance(exp, (int, float)):
                    token_expiry = max(0, float(exp) - now_ts)
            except Exception:
                token_age_sec = None
                token_expiry = None
            return {
                'option_cache_size': len(getattr(self._state, 'option_instrument_cache', {})),
                'option_cache_hits': getattr(self._state, 'option_cache_hits', 0),
                'option_cache_misses': getattr(self._state, 'option_cache_misses', 0),
                'instruments_cached': {k: len(v or []) for k, v in getattr(self._state, 'instruments_cache', {}).items()},
                'expiry_dates_cached': {k: len(v or []) for k, v in getattr(self._state, 'expiry_dates_cache', {}).items()},
                'synthetic_quotes_used': int(self._synthetic_quotes_used),
                'last_quotes_synthetic': bool(self._last_quotes_synthetic),
                'used_instrument_fallback': bool(self._used_fallback),
                'token_age_sec': token_age_sec,
                'token_time_to_expiry_sec': token_expiry,
            }
        except Exception:
            return {}

    # --- deprecation property shims ----------------------------------------
    def _warn_once(self, name: str):
        if not hasattr(self, '_issued_deprecation_warnings'):
            self._issued_deprecation_warnings: Set[str] = set()
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
    def synthetic_quotes_used(self) -> int:
        self._warn_once('synthetic_quotes_used')
        return int(self._synthetic_quotes_used)

    @property
    def last_quotes_synthetic_flag(self) -> bool:
        self._warn_once('last_quotes_synthetic_flag')
        return bool(self._last_quotes_synthetic)

    # --- ATM strike heuristic -----------------------------------------------
    def get_atm_strike(self, index_symbol: str) -> int:
        ltp_data = self.get_ltp([INDEX_MAPPING.get(index_symbol, ("NSE", index_symbol))])
        if isinstance(ltp_data, dict):
            for v in ltp_data.values():
                if isinstance(v, dict):
                    lp = v.get('last_price')
                    if isinstance(lp, (int, float)) and lp > 0:
                        step = 100 if lp > 20000 else 50
                        return int(round(lp / step) * step)
        defaults = {"NIFTY": 24800, "BANKNIFTY": 54000, "FINNIFTY": 26000, "MIDCPNIFTY": 12000, "SENSEX": 81000}
        return defaults.get(index_symbol, 20000)

    # --- expiry discovery ---------------------------------------------------
    def get_expiry_dates(self, index_symbol: str) -> list[_dt.date]:
        try:
            if self._auth_failed:
                raise RuntimeError("kite_auth_failed")
            cache = self._state.expiry_dates_cache.get(index_symbol)
            if cache:
                return cache
            atm = self.get_atm_strike(index_symbol)
            exch = POOL_FOR.get(index_symbol, "NFO")
            instruments = self.get_instruments(exch)
            today = _dt.date.today()
            opts = [
                inst for inst in instruments
                if isinstance(inst, dict)
                and str(inst.get("segment", "")).endswith("-OPT")
                and index_symbol in str(inst.get("tradingsymbol", ""))
                and abs(float(inst.get("strike", 0) or 0) - atm) <= 500
            ]
            expiries: set[_dt.date] = set()
            for inst in opts:
                exp = inst.get('expiry')
                if isinstance(exp, _dt.date):
                    if exp >= today:
                        expiries.add(exp)
                elif isinstance(exp, str):
                    try:
                        dtp = _dt.datetime.strptime(exp[:10], '%Y-%m-%d').date()
                        if dtp >= today:
                            expiries.add(dtp)
                    except Exception:
                        pass
            sorted_dates = sorted(expiries)
            if not sorted_dates:
                days_until_thu = (3 - today.weekday()) % 7
                if days_until_thu == 0:
                    days_until_thu = 7
                this_week = today + _dt.timedelta(days=days_until_thu)
                next_week = this_week + _dt.timedelta(days=7)
                sorted_dates = [this_week, next_week]
            self._state.expiry_dates_cache[index_symbol] = sorted_dates
            return sorted_dates
        except Exception as e:
            if _is_auth_error(e) or str(e) == 'kite_auth_failed':
                self._auth_failed = True
                if self._rl_fallback():
                    logger.warning("Kite auth failed; using synthetic expiry dates.")
                today = _dt.date.today()
                synth = [today + _dt.timedelta(days=14)]
                self._state.expiry_dates_cache[index_symbol] = synth
                return synth
            logger.error(f"Failed to get expiry dates: {e}", exc_info=True)
            try:
                handle_data_collection_error(e, component="kite_provider.get_expiry_dates", index_name=index_symbol, data_type="expiries")
            except Exception:
                pass
            today = _dt.date.today()
            days_until_thu = (3 - today.weekday()) % 7
            this_week = today + _dt.timedelta(days=days_until_thu)
            next_week = this_week + _dt.timedelta(days=7)
            return [this_week, next_week]

    def get_weekly_expiries(self, index_symbol: str) -> list[_dt.date]:
        try:
            all_exp = self.get_expiry_dates(index_symbol)
            return all_exp[:2] if len(all_exp) >= 2 else all_exp
        except Exception:
            return []

    def get_monthly_expiries(self, index_symbol: str) -> list[_dt.date]:
        try:
            all_exp = self.get_expiry_dates(index_symbol)
            today = _dt.date.today()
            by_month: Dict[tuple[int,int], List[_dt.date]] = {}
            for d in all_exp:
                if d >= today:
                    by_month.setdefault((d.year, d.month), []).append(d)
            out: list[_dt.date] = []
            for _, vals in sorted(by_month.items()):
                out.append(max(vals))
            return out
        except Exception:
            return []

    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> _dt.date:
        from src.broker.kite.expiries import resolve_expiry_rule  # local import
        try:
            chosen = resolve_expiry_rule(self, index_symbol, expiry_rule)
            (logger.debug if _CONCISE else logger.info)(f"Resolved '{expiry_rule}' for {index_symbol} -> {chosen}")
            return chosen
        except Exception:  # pragma: no cover
            return _dt.date.today()

    # --- options delegation -------------------------------------------------
    def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        try:
            from src.broker.kite.options import option_instruments as _impl
        except Exception:  # pragma: no cover
            logger.error("options_module_import_failed", exc_info=True)
            return []
        return _impl(self, index_symbol, expiry_date, strikes)

    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[dict[str, Any]]:
        return self.option_instruments(index_symbol, expiry_date, strikes)

    # --- health check -------------------------------------------------------
    def check_health(self) -> dict[str, Any]:
        try:
            pair = INDEX_MAPPING.get("NIFTY", ("NSE", "NIFTY 50"))
            ltp = self.get_ltp([pair])
            price_ok = False
            if isinstance(ltp, dict):
                for v in ltp.values():
                    if isinstance(v, dict) and isinstance(v.get('last_price'), (int,float)) and v['last_price'] > 0:
                        price_ok = True
                        break
            return {"status": "healthy" if price_ok else "degraded", "message": "Provider connected" if price_ok else "Invalid price"}
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ("token", "auth", "unauthor")):
                return {"status": "unhealthy", "message": "Auth/token issue detected"}
            return {"status": "unhealthy", "message": f"Health check failed: {e}"}

# ----------------------------------------------------------------------------
# Public exports
# ----------------------------------------------------------------------------
__all__ = [
    "KiteProvider",
    "DummyKiteProvider",  # re-export
    "enable_concise_logs",
    "_CONCISE",
    "INDEX_MAPPING",
    "POOL_FOR",
]
