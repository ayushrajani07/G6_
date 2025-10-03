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

from typing import Any, Iterable, Dict, Sequence, Union, Protocol, Callable, Optional, runtime_checkable
from .types import QuoteTD
import logging, os, time, threading

logger = logging.getLogger(__name__)

# Attempt to reuse provider helpers
try:  # pragma: no cover - defensive import
    from src.broker.kite_provider import _is_auth_error, _timed_call, _CONCISE
except Exception:  # pragma: no cover
    def _is_auth_error(e: BaseException) -> bool:
        return False
    def _timed_call(fn, timeout: float):  # type: ignore[unused-ignore]
        return fn()
    _CONCISE = True

# Retry helper imported lazily to avoid cost if synthetic path only
from src.utils.retry import call_with_retry
try:  # rate limiter optional (Phase 1)
    from .rate_limit import build_default_rate_limiter, RateLimitedError
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

# Simple in-memory quote cache (symbol -> (ts, data)) populated only on real quote success.
_QUOTE_CACHE_LOCK = threading.Lock()
_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
def _quote_cache_get(symbol: str, ttl: float) -> dict | None:
    if ttl <= 0:
        return None
    with _QUOTE_CACHE_LOCK:
        entry = _QUOTE_CACHE.get(symbol)
        if not entry:
            return None
        ts, data = entry
        if (time.time() - ts) <= ttl:
            return data
        return None
def _quote_cache_put(raw: dict, ttl: float) -> None:
    if ttl <= 0 or not isinstance(raw, dict):
        return
    now = time.time()
    with _QUOTE_CACHE_LOCK:
        for k, v in raw.items():
            if isinstance(v, dict):
                _QUOTE_CACHE[k] = (now, v)


@runtime_checkable
class ProviderLike(Protocol):
    kite: Any
    _settings: Any
    _auth_failed: bool
    _api_rl: Optional[Callable[[], None]]
    _rl_fallback: Optional[Callable[[], bool]]
    _rl_quote_fallback: Optional[Callable[[], bool]]
    _synthetic_quotes_used: int
    _last_quotes_synthetic: bool
    def maybe_refresh_token_proactively(self) -> None: ...  # pragma: no cover - optional



InstrumentLike = Union[str, tuple[str, str], Sequence[str]]

def get_ltp(provider: ProviderLike | Any, instruments: Iterable[InstrumentLike]) -> Dict[str, Any]:
    """Return last traded prices (dict) for requested instruments.

    Instruments may be tuples (exchange, symbol) or already formatted strings
    of the form EXCH:SYMBOL. Bare symbol strings are assumed NSE:<symbol>.
    """
    data: Dict[str, Any] = {}
    # Real path
    try:
        # Optional proactive refresh advisory
        try:
            provider.maybe_refresh_token_proactively()  # may not exist on some provider shims
        except Exception:
            pass
        if getattr(provider, '_auth_failed', False):
            raise RuntimeError('kite_auth_failed')
        kite = getattr(provider, 'kite', None)
        if kite is not None:
            formatted: list[str] = []
            for item in instruments:
                try:
                    if isinstance(item, str):
                        if ':' in item:
                            formatted.append(item)
                        else:
                            formatted.append(f"NSE:{item}")
                        continue
                    if isinstance(item, (tuple, list)):
                        if len(item) == 2:
                            exch, ts = item
                            formatted.append(f"{exch}:{ts}")
                            continue
                        elif len(item) == 1:
                            sym = item[0]
                            formatted.append(f"NSE:{sym}")
                            continue
                    logger.debug(f"Skipping malformed LTP instrument entry: {item}")
                except Exception:
                    logger.debug("Error normalizing LTP instrument entry", exc_info=True)
            if formatted:
                def _fetch_ltp() -> Any:
                    rl = getattr(provider, '_api_rl', None)
                    if callable(rl):
                        rl()
                    return _timed_call(lambda: kite.ltp(formatted), getattr(provider._settings, 'kite_timeout_sec', 5.0))
                raw = call_with_retry(_fetch_ltp)
                try:  # quality guard
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
                except Exception as ltp_quality_err:
                    logger.debug(f"LTP response unusable ({ltp_quality_err}); switching to synthetic values")
    except Exception as e:  # Real path failed
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            try:
                provider._auth_failed = True  # may not exist on dummy provider
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

    # Synthetic fallback
    try:
        from src.broker.kite.synthetic import synth_ltp_for_pairs
        # Normalize instruments to (exch, symbol) pairs expected by builder
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
                    ex = str(entry[0])
                    sy = str(entry[1])
                    norm_pairs.append((ex, sy))
            except Exception:
                continue
        return synth_ltp_for_pairs(norm_pairs)
    except Exception:  # pragma: no cover
        for entry in instruments:
            try:
                if isinstance(entry, str):
                    if ':' in entry:
                        exch, ts = entry.split(':', 1)
                    else:
                        exch, ts = 'NSE', entry
                else:
                    exch, ts = entry  # fallback best-effort unpack
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


def get_quote(provider: ProviderLike | Any, instruments: Iterable[InstrumentLike]) -> Dict[str, QuoteTD]:
    """Return full quotes (fallback to synthetic / LTP-based structure).

    Format mirrors provider.get_quote: dict keyed by EXCH:SYMBOL with at least
    'last_price' and 'ohlc'.
    """
    try:
        if getattr(provider, '_auth_failed', False):
            raise RuntimeError('kite_auth_failed')
        kite = getattr(provider, 'kite', None)
        if kite is not None:
            formatted = []
            for item in instruments:
                if isinstance(item, str):
                    if ':' in item:
                        formatted.append(item)
                    else:
                        formatted.append(f"NSE:{item}")
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    exch, sym = item[0], item[1]
                    formatted.append(f"{exch}:{sym}")
            if formatted:
                # Attempt cache fast-path for all symbols if cache enabled
                cache_ttl = 0.0
                try:
                    cache_ttl = float(os.getenv('G6_KITE_QUOTE_CACHE_SECONDS','1') or 1.0)
                except Exception:
                    cache_ttl = 1.0
                # If every requested symbol present in cache within TTL, return composite immediately
                if cache_ttl > 0:
                    aggregate_cached: dict[str, Any] = {}
                    all_hit = True
                    for sym in formatted:
                        cached = _quote_cache_get(sym, cache_ttl)
                        if cached is None:
                            all_hit = False
                            break
                        aggregate_cached[sym] = cached
                    if all_hit and aggregate_cached:
                        try:
                            provider._last_quotes_synthetic = False
                        except Exception:
                            pass
                        return aggregate_cached  # full cache hit
                # Phase 1 rate limiter integration (opt-in via env G6_KITE_LIMITER=1)
                limiter = None
                if build_default_rate_limiter and (str(os.getenv('G6_KITE_LIMITER','0')).lower() in ('1','true','yes','on')):
                    # cache a limiter on provider to reuse tokens
                    limiter = getattr(provider, '_g6_quote_rate_limiter', None)
                    if limiter is None:
                        try:
                            limiter = build_default_rate_limiter()
                            setattr(provider, '_g6_quote_rate_limiter', limiter)
                        except Exception:
                            limiter = None
                def _direct_fetch() -> Any:
                    rl = getattr(provider, '_api_rl', None)
                    if callable(rl):
                        rl()
                    if limiter is not None:
                        try:
                            limiter.acquire()
                        except RateLimitedError:
                            raise
                    return _timed_call(lambda: kite.quote(formatted), getattr(provider._settings, 'kite_timeout_sec', 5.0))

                def _fetch_quote() -> Any:
                    # If batching enabled, delegate to batcher (already handles limiter inside batch network call)
                    if batching_enabled():
                        try:
                            batcher = get_batcher()
                            # batcher expects fully formatted symbols
                            return batcher.fetch(provider, formatted)
                        except Exception:
                            # fallback to direct path on any batcher issue
                            return _direct_fetch()
                    return _direct_fetch()
                try:
                    raw = call_with_retry(_fetch_quote)
                    if limiter is not None:
                        try:
                            limiter.record_success()
                        except Exception:
                            pass
                    # Populate cache (best-effort)
                    if cache_ttl > 0:
                        try:
                            _quote_cache_put(raw, cache_ttl)
                        except Exception:
                            pass
                except Exception as rate_e:
                    # Detect provider-level rate limit messages to inform limiter
                    msg = str(rate_e).lower()
                    if limiter is not None and any(k in msg for k in ("too many requests","rate limit","429")):
                        try:
                            limiter.record_rate_limit_error()
                        except Exception:
                            pass
                    raise
                try:
                    provider._last_quotes_synthetic = False
                except Exception:
                    pass
                return raw
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
    quotes: Dict[str, QuoteTD] = {}
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
