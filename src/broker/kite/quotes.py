"""Quote & LTP retrieval (Phase 7 extraction).

Provides two public functions mirroring KiteProvider methods:
  - get_ltp(provider, instruments)
  - get_quote(provider, instruments)

They accept a provider-like object exposing:
  * kite (client or None)
  * _settings (with kite_timeout_sec)
  * _auth_failed flag (bool)
  * _api_rl (RateLimiter or None)
  * _rl_fallback / _rl_quote_fallback (rate-limited log helpers)
  * _synthetic_quotes_used / _last_quotes_synthetic counters (for quote path)
  * maybe_refresh_token_proactively (optional advisory method)

Behavior parity retained:
  * Normalization of instrument tuples/strings
  * Soft timeout using provider._settings.kite_timeout_sec
  * Auth failure detection -> set _auth_failed, skip further real calls
  * Quality guard: empty or all-zero LTP response triggers synthetic fallback
  * Quote fallback to LTP synthetic values
  * Synthetic builders delegated to synthetic.py utilities
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol, Union, runtime_checkable

from .types import QuoteTD

logger = logging.getLogger(__name__)

# Attempt to reuse provider helpers
try:  # pragma: no cover - defensive import
    from src.broker.kite_provider import _is_auth_error, _timed_call, is_concise_logging
except Exception:  # pragma: no cover
    def _is_auth_error(e: BaseException) -> bool:
        return False
    def _timed_call(fn, timeout: float):  # type: ignore[unused-ignore]
        return fn()
    def is_concise_logging() -> bool:  # type: ignore
        return True

# Retry helper imported lazily to avoid cost if synthetic path only
from src.utils.retry import call_with_retry

try:  # rate limiter optional (Phase 1)
    from .rate_limit import RateLimitedError, build_default_rate_limiter
except Exception:  # pragma: no cover
    build_default_rate_limiter = None  # type: ignore
    class RateLimitedError(RuntimeError): ...  # type: ignore

# Batching (Phase 2) optional
try:
    from .quote_batcher import batching_enabled, get_batcher
except Exception:  # pragma: no cover
    def batching_enabled() -> bool:  # type: ignore
        return False
    def get_batcher():  # type: ignore
        raise RuntimeError('batcher_unavailable')



@runtime_checkable
class ProviderLike(Protocol):
    kite: Any
    _settings: Any
    _auth_failed: bool
    _api_rl: Callable[[], None] | None
    _rl_fallback: Callable[[], bool] | None
    _rl_quote_fallback: Callable[[], bool] | None
    _synthetic_quotes_used: int
    _last_quotes_synthetic: bool
    def maybe_refresh_token_proactively(self) -> None: ...  # pragma: no cover - optional



InstrumentLike = Union[str, tuple[str, str], Sequence[str]]

def _normalize_instruments(instruments: Iterable[InstrumentLike], default_exchange: str = 'NSE') -> list[str]:
    formatted: list[str] = []
    for item in instruments:
        try:
            if isinstance(item, str):
                if ':' in item:
                    formatted.append(item)
                else:
                    formatted.append(f"{default_exchange}:{item}")
                continue
            if isinstance(item, (tuple, list)):
                if len(item) >= 2:
                    exch, sym = item[0], item[1]
                    formatted.append(f"{exch}:{sym}")
                    continue
                if len(item) == 1:
                    sym = item[0]
                    formatted.append(f"{default_exchange}:{sym}")
                    continue
            logger.debug(f"Skipping malformed instrument entry: {item}")
        except Exception:
            logger.debug("Error normalizing instrument entry", exc_info=True)
    return formatted


def _quality_guard_ltps(raw: Any) -> Any:
    if isinstance(raw, dict):
        if not raw:
            raise ValueError('empty_ltp_response')
        all_zero = True
        for _k, _v in raw.items():
            if isinstance(_v, dict):
                lp = _v.get('last_price')
                if isinstance(lp, (int, float)) and lp and lp > 0:
                    all_zero = False
                    break
        if all_zero:
            raise ValueError('zero_ltp_response')
    return raw


def _synthetic_ltp(provider, instruments: Iterable[InstrumentLike]) -> dict[str, Any]:
    # Synthetic fallback
    try:
        from src.broker.kite.synthetic import synth_ltp_for_pairs
        norm_pairs: list[tuple[str, str]] = []
        for entry in instruments:
            try:
                if isinstance(entry, str):
                    if ':' in entry:
                        ex, sy = entry.split(':', 1)
                    else:
                        ex, sy = 'NSE', entry
                    norm_pairs.append((ex, sy))
                elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    ex = str(entry[0]); sy = str(entry[1])
                    norm_pairs.append((ex, sy))
            except Exception:
                continue
        return synth_ltp_for_pairs(norm_pairs)
    except Exception:  # pragma: no cover
        data: dict[str, Any] = {}
        for entry in instruments:
            try:
                if isinstance(entry, str):
                    if ':' in entry:
                        exch, ts = entry.split(':', 1)
                    else:
                        exch, ts = 'NSE', entry
                else:
                    exch, ts = entry  # type: ignore
            except Exception:
                continue
            price = 1000
            if "NIFTY 50" in ts:
                price = 24800
            elif "NIFTY BANK" in ts:
                price = 54000
            elif "NIFTY FIN SERVICE" in ts:
                price = 26000
            elif "MIDCAP" in ts:
                price = 12000
            elif "SENSEX" in ts:
                price = 81000
            data[f"{exch}:{ts}"] = {"last_price": price}
        return data


def get_ltp(provider: ProviderLike | Any, instruments: Iterable[InstrumentLike]) -> dict[str, Any]:
    """Return last traded prices (dict) for requested instruments (parity preserved)."""
    try:
        try:
            provider.maybe_refresh_token_proactively()
        except Exception:
            pass
        if getattr(provider, '_auth_failed', False):
            raise RuntimeError('kite_auth_failed')
        kite = getattr(provider, 'kite', None)
        if kite is not None:
            formatted = _normalize_instruments(instruments)
            if formatted:
                def _fetch_ltp() -> Any:
                    rl = getattr(provider, '_api_rl', None)
                    if callable(rl):
                        rl()
                    return _timed_call(lambda: kite.ltp(formatted), getattr(provider._settings, 'kite_timeout_sec', 5.0))
                raw = call_with_retry(_fetch_ltp)
                try:
                    return _quality_guard_ltps(raw)
                except Exception as ltp_quality_err:
                    logger.debug(f"LTP response unusable ({ltp_quality_err}); switching to synthetic values")
    except Exception as e:
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            try:
                provider._auth_failed = True
            except Exception:
                pass
            if getattr(provider, '_rl_fallback', lambda: True)():
                logger.warning("Kite auth failed; using synthetic LTP. Set KITE_API_KEY/KITE_ACCESS_TOKEN to enable real API.")
        else:
            logger.debug(f"LTP real fetch failed, using synthetic: {e}")
        try:
            from src.error_handling import handle_provider_error
            handle_provider_error(e, component='kite_provider.get_ltp')
        except Exception:
            pass
    return _synthetic_ltp(provider, instruments)


def get_quote(provider: ProviderLike | Any, instruments: Iterable[InstrumentLike]) -> dict[str, QuoteTD]:
    """Return full quotes (fallback to synthetic / LTP-based structure).

    Format mirrors provider.get_quote: dict keyed by EXCH:SYMBOL with at least
    'last_price' and 'ohlc'.
    """
    try:
        if getattr(provider, '_auth_failed', False):
            raise RuntimeError('kite_auth_failed')
        # Delegate real path to extracted fetch module
        from .quote_fetch import fetch_real_quotes
        real = fetch_real_quotes(provider, instruments)
        if real is not None:
            return real
    except Exception as e:
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            try:
                provider._auth_failed = True
            except Exception:
                pass
            if getattr(provider, '_rl_quote_fallback', lambda: True)():
                logger.warning("Kite auth failed; using synthetic quotes. Set KITE_API_KEY/KITE_ACCESS_TOKEN to enable real API.")
        else:
            if getattr(provider, '_rl_quote_fallback', lambda: True)():
                logger.debug(f"Quote real fetch failed, falling back to LTP: {e}")
        try:
            from src.error_handling import handle_provider_error
            handle_provider_error(e, component='kite_provider.get_quote')
        except Exception:
            pass

    # Fallback -> build synthetic quotes from LTP
    ltp_data = get_ltp(provider, instruments)
    quotes: dict[str, QuoteTD] = {}
    if isinstance(ltp_data, dict):
        try:
            from src.broker.kite.synthetic import build_synthetic_quotes
            quotes = build_synthetic_quotes(ltp_data)
        except Exception:  # pragma: no cover
            for key, payload in ltp_data.items():
                if not isinstance(payload, dict):
                    continue
                lp = payload.get('last_price', 0)
                high = round(lp * 1.01, 2) if lp else 0
                low = round(lp * 0.99, 2) if lp else 0
                open_p = round((high + low) / 2, 2) if lp else 0
                close = lp
                base = int(lp // 10) if lp else 0
                volume = max(1, base * 3 + 100) if lp else 0
                oi = volume * 5 if volume else 0
                avg_price = round((high + low + 2 * close) / 4, 2) if lp else 0
                quotes[key] = {  # runtime shape broad; conforms to QuoteTD subset
                    'last_price': lp,
                    'volume': volume,
                    'oi': oi,
                    'average_price': avg_price,
                    'ohlc': {'open': open_p, 'high': high, 'low': low, 'close': close},
                }
        try:
            provider._synthetic_quotes_used = getattr(provider, '_synthetic_quotes_used', 0) + len(quotes)
            provider._last_quotes_synthetic = True
        except Exception:
            pass
        if getattr(provider, '_rl_quote_fallback', lambda: True)():
            logger.warning(
                "Synthetic quotes generated (count=%d) - fabricated volume/oi/ohlc placeholders in use",
                len(quotes),
            )
    return quotes
