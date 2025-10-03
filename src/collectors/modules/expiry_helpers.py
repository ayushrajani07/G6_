"""Expiry helper primitives extracted from unified_collectors.

Behavior preserved verbatim (copy-paste) to maintain zero drift.
Functions keep the same names (without leading underscore externally) and are
re-exported via __all__ so legacy wrappers in unified_collectors can delegate.
"""
from __future__ import annotations
from typing import Any, List
import os, time, datetime, logging

from src.collectors.cycle_context import CycleContext
from src.collectors.persist_result import PersistResult  # noqa: F401 (may be used by callers indirectly)
from src.utils.exceptions import ResolveExpiryError, NoInstrumentsError, NoQuotesError
from src.error_handling import handle_collector_error

logger = logging.getLogger(__name__)

_EXPIRY_SERVICE_SINGLETON = None  # cached instance or None (mirrors original)

def _get_expiry_service():  # lazy import + build to avoid overhead
    global _EXPIRY_SERVICE_SINGLETON
    if _EXPIRY_SERVICE_SINGLETON is not None:
        return _EXPIRY_SERVICE_SINGLETON
    try:
        from src.utils.expiry_service import build_expiry_service  # type: ignore
        _EXPIRY_SERVICE_SINGLETON = build_expiry_service()
    except Exception:  # pragma: no cover
        _EXPIRY_SERVICE_SINGLETON = None
    return _EXPIRY_SERVICE_SINGLETON


def fetch_option_instruments(index_symbol, expiry_rule, expiry_date, strikes, providers, metrics):
    _t_api = time.time()
    instruments = []
    try:
        instruments = providers.get_option_instruments(index_symbol, expiry_date, strikes)
    except (NoInstrumentsError,) as inst_err:
        try:
            from src.collectors.modules.error_bridge import report_instrument_fetch_error  # type: ignore
            report_instrument_fetch_error(inst_err, index_symbol, expiry_rule, expiry_date, len(strikes))
        except Exception:
            handle_collector_error(inst_err, component="collectors.expiry_helpers", index_name=index_symbol,
                                   context={"stage":"get_option_instruments","rule":expiry_rule,"expiry":str(expiry_date),"strike_count":len(strikes)})
        instruments = []
    except Exception as inst_err:
        logger.error(f"Unexpected instrument fetch error {index_symbol} {expiry_rule}: {inst_err}")
        instruments = []
    if metrics and hasattr(metrics, 'mark_api_call'):
        metrics.mark_api_call(success=bool(instruments), latency_ms=(time.time()-_t_api)*1000.0)
    return instruments

def enrich_quotes(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics):
    enrich_start = time.time()
    try:
        enriched_data = providers.enrich_with_quotes(instruments)
    except (NoQuotesError,) as enrich_err:
        try:
            from src.collectors.modules.error_bridge import report_quote_enrich_error  # type: ignore
            report_quote_enrich_error(enrich_err, index_symbol, expiry_rule, expiry_date, len(instruments))
        except Exception:
            handle_collector_error(enrich_err, component="collectors.expiry_helpers", index_name=index_symbol,
                                   context={"stage":"enrich_with_quotes","rule":expiry_rule,"expiry":str(expiry_date),"instrument_count":len(instruments)})
        enriched_data = {}
    except Exception as enrich_err:
        import traceback
        tb = traceback.format_exc(limit=3)
        logger.error(f"Unexpected quote enrich error {index_symbol} {expiry_rule}: {enrich_err} | type={type(enrich_err).__name__} tb_snip={tb.strip().replace('\n',' | ')}")
        enriched_data = {}
    enrich_elapsed = time.time() - enrich_start
    if metrics and hasattr(metrics, 'mark_api_call'):
        metrics.mark_api_call(success=bool(enriched_data), latency_ms=enrich_elapsed*1000.0)
    return enriched_data

def synthetic_metric_pop(ctx: CycleContext, index_symbol, expiry_date):
    try:
        metrics = ctx.metrics; providers = ctx.providers
        if metrics and hasattr(metrics, 'synthetic_quotes_used_total') and hasattr(providers, 'primary_provider'):
            prov = getattr(providers, 'primary_provider', None)
            if prov and hasattr(prov, 'pop_synthetic_quote_usage'):
                synth_count, was_synth = prov.pop_synthetic_quote_usage()  # type: ignore[attr-defined]
                if synth_count > 0 or was_synth:
                    try:
                        metrics.synthetic_quotes_used_total.labels(index=index_symbol, expiry=str(expiry_date)).inc(synth_count or 0)
                    except Exception:
                        logger.debug("Failed to increment synthetic_quotes_used_total", exc_info=True)
    except Exception:
        logger.debug("Synthetic quotes metric wiring failed", exc_info=True)

__all__ = [
    'resolve_expiry',
    'fetch_option_instruments',
    'enrich_quotes',
    'synthetic_metric_pop',
]

# ---------------------------------------------------------------------------
# Backward-compatible minimal resolve_expiry implementation
# ---------------------------------------------------------------------------
def resolve_expiry(index_symbol, expiry_rule, providers, metrics, concise_mode):
    """Lightweight resolver preserved for backward compatibility.

    Semantics:
      * Accept explicit ISO date (YYYY-MM-DD) tokens directly.
      * If legacy ExpiryService enabled (singleton build), use it to select from
        provider candidate list (if available) respecting holidays.
      * Fallback to providers.resolve_expiry.
      * Raise ResolveExpiryError on failure for callers expecting that type.
    """
    import datetime as _dt, time as _time
    start = _time.time()
    expiry_date = None
    # Explicit ISO date short‑circuit
    try:
        if isinstance(expiry_rule, str) and len(expiry_rule) == 10 and expiry_rule[4] == '-' and expiry_rule[7] == '-':
            y, m, d = expiry_rule.split('-')
            if all(p.isdigit() for p in (y, m, d)):
                expiry_date = _dt.date(int(y), int(m), int(d))
    except Exception:
        expiry_date = None
    # Attempt legacy service
    if expiry_date is None:
        svc = _get_expiry_service()
        if svc is not None:
            try:
                candidates = []
                # Support both facade and direct provider
                prov_obj = getattr(providers, 'primary_provider', providers)
                if hasattr(prov_obj, 'get_expiry_dates'):
                    try:
                        candidates = list(prov_obj.get_expiry_dates(index_symbol))  # type: ignore[attr-defined]
                    except Exception:
                        candidates = []
                if candidates:
                    expiry_date = svc.select(expiry_rule, candidates)  # type: ignore[attr-defined]
            except Exception:
                expiry_date = None
    # Provider fallback
    if expiry_date is None and hasattr(providers, 'resolve_expiry'):
        try:
            expiry_date = providers.resolve_expiry(index_symbol, expiry_rule)
        except Exception:
            expiry_date = None
    if metrics and hasattr(metrics, 'mark_api_call'):
        try:
            metrics.mark_api_call(success=bool(expiry_date), latency_ms=(_time.time()-start)*1000.0)
        except Exception:
            pass
    if not expiry_date:
        raise ResolveExpiryError(f"Failed to resolve expiry for {index_symbol} rule={expiry_rule}")
    return expiry_date
