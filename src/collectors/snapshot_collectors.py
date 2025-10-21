"""Snapshot collectors (replacement for deprecated enhanced_collector).

This module provides a lightweight path to build in‑memory ExpirySnapshot objects
without invoking the full unified collectors persistence/enrichment pipeline.

It intentionally ports only the unique behaviors that were previously present
in the deprecated enhanced_collector:

  * Synthetic instrument generation (minimal CE/PE pair per strike) when the
    provider facade cannot return instruments.
  * Synthetic quote fallback ensuring downstream snapshot creation still occurs
    even when quotes API returns nothing (enables cache warm‑up + tests).
  * Basic volume / open interest filtering + optional volume percentile trim.
  * Optional domain model mapping gated by G6_DOMAIN_MODELS (non‑intrusive).
  * Optional construction / return of ExpirySnapshot objects when requested.

Differences vs the removed enhanced_collector:

  * No persistence side‑effects (CSV / Influx writes) – the orchestrator or
    unified collectors already handle persistence on the main path.
  * No metrics timing contexts; callers can instrument externally if needed.
  * No implicit market hours gating – orchestrator is responsible for gating.

Usage:
    from src.collectors.snapshot_collectors import run_snapshot_collectors
    snaps = run_snapshot_collectors(index_params, providers, return_snapshots=True)

If return_snapshots is False (default) the function executes collection logic
purely for its side‑effects (currently none) and returns None.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import TYPE_CHECKING, Any

from ..utils.timeutils import get_utc_now
from .providers_interface import Providers

if TYPE_CHECKING:  # circular import safe
    from src.domain.models import ExpirySnapshot, OptionQuote

logger = logging.getLogger(__name__)

def run_snapshot_collectors(
    index_params: dict[str, Any],
    providers: Providers,
    *,
    min_volume: int = 0,
    min_oi: int = 0,
    volume_percentile: float = 0.0,
    return_snapshots: bool = False,
) -> list[ExpirySnapshot] | None:
    """Collect minimal option chain slices and optionally build snapshots.

    Parameters
    ----------
    index_params : dict
        Mapping of index symbol -> parameters (expiry_rules/offsets/strike_step).
    providers : Providers
        Provider facade (must expose get_atm_strike, resolve_expiry, get_option_instruments or option_instruments, get_quote).
    min_volume / min_oi : int
        Hard filters removing quotes below both thresholds.
    volume_percentile : float
        Additional percentile cut filtering out the lowest volume options when > 0.
    return_snapshots : bool
        Whether to materialize and return ExpirySnapshot objects.
    """
    now = get_utc_now()
    snapshots: list[ExpirySnapshot] = [] if return_snapshots else []
    build_domain_models = os.environ.get('G6_DOMAIN_MODELS','').lower() in ('1','true','yes','on')
    for index_symbol, params in (index_params or {}).items():
        try:
            expiry_rules = _get_param(params, 'expiry_rules', ['this_week'])
            offsets = _get_param(params, 'offsets', [-2,-1,0,1,2])
            strike_step = int(_get_param(params, 'strike_step', 50))
            try:
                atm_strike = providers.get_atm_strike(index_symbol)  # type: ignore[attr-defined]
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("snapshot_collectors: ATM strike failed %s %s", index_symbol, e)
                continue
            for expiry_rule in expiry_rules:
                try:
                    try:
                        expiry_date = providers.resolve_expiry(index_symbol, expiry_rule)  # type: ignore[attr-defined]
                    except Exception:
                        # Best effort: treat rule as explicit date (YYYY-MM-DD) else skip
                        import datetime as _dt
                        try:
                            expiry_date = _dt.date.fromisoformat(expiry_rule)
                        except Exception:
                            continue
                    strikes = [atm_strike + off*strike_step for off in offsets]
                    instruments = _load_instruments(providers, index_symbol, expiry_date, strikes)
                    if not instruments:
                        instruments = _build_synthetic_instruments(index_symbol, expiry_date, strikes)
                    calls, puts = _partition_instruments(instruments)
                    symbols = calls + puts
                    if not symbols:
                        continue
                    quotes = _load_quotes(providers, symbols)
                    if not quotes:
                        quotes = _build_synthetic_quotes(symbols, now)
                    # Hard filters
                    if (min_volume > 0 or min_oi > 0) and quotes:
                        quotes = {
                            k: q for k, q in quotes.items()
                            if int(q.get('volume',0)) >= min_volume and int(q.get('oi',0)) >= min_oi
                        }
                    if volume_percentile > 0 and len(quotes) > 10:
                        vols = sorted(int(q.get('volume',0)) for q in quotes.values())
                        cutoff = vols[int(len(vols)*volume_percentile)]
                        quotes = {k:v for k,v in quotes.items() if int(v.get('volume',0)) >= cutoff}
                    # Domain model mapping (optional)
                    option_objs: list[OptionQuote] = []
                    if return_snapshots:
                        try:
                            from src.domain.models import OptionQuote  # type: ignore
                            for k,q in quotes.items():
                                try:
                                    option_objs.append(OptionQuote.from_raw(k,q))
                                except Exception:
                                    continue
                        except Exception:  # pragma: no cover
                            logger.debug("snapshot_collectors: OptionQuote mapping failed", exc_info=True)
                    if return_snapshots:
                        try:
                            from src.domain.models import ExpirySnapshot  # type: ignore
                            snapshots.append(ExpirySnapshot(
                                index=index_symbol,
                                expiry_rule=expiry_rule,
                                expiry_date=expiry_date,
                                atm_strike=atm_strike,
                                options=option_objs,
                                generated_at=now,
                            ))
                        except Exception:  # pragma: no cover
                            logger.debug("snapshot_collectors: building ExpirySnapshot failed", exc_info=True)
                except Exception:  # pragma: no cover
                    logger.debug("snapshot_collectors: per-expiry failure index=%s rule=%s", index_symbol, expiry_rule, exc_info=True)
        except Exception:  # pragma: no cover
            logger.debug("snapshot_collectors: index failure %s", index_symbol, exc_info=True)
    return snapshots if return_snapshots else None


def _get_param(params: Any, name: str, default: Any) -> Any:
    if isinstance(params, dict):
        return params.get(name, default)
    return getattr(params, name, default)

def _load_instruments(providers: Providers, index_symbol: str, expiry_date: date, strikes: list[float]):
    try:
        if hasattr(providers, 'option_instruments'):
            return providers.option_instruments(index_symbol, expiry_date, strikes)  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        if hasattr(providers, 'get_option_instruments'):
            return providers.get_option_instruments(index_symbol, expiry_date, strikes)  # type: ignore[attr-defined]
    except Exception:
        pass
    return []

def _build_synthetic_instruments(index_symbol: str, expiry_date: date, strikes: list[float]):
    out = []
    for strike in strikes:
        for t in ("CE","PE"):
            tsym = f"{index_symbol} {expiry_date:%d%b%y} {int(strike)} {t}".upper()
            out.append({
                'tradingsymbol': tsym,
                'exchange': 'NFO',
                'instrument_type': t,
                'strike': strike,
                'expiry': expiry_date,
            })
    logger.info("Synthetic instruments generated index=%s count=%d", index_symbol, len(out))
    return out

def _partition_instruments(instruments):
    calls = []
    puts = []
    for inst in instruments or []:
        t = inst.get('instrument_type')
        if t == 'CE':
            calls.append((inst.get('exchange'), inst.get('tradingsymbol')))
        elif t == 'PE':
            puts.append((inst.get('exchange'), inst.get('tradingsymbol')))
    return calls, puts

def _load_quotes(providers: Providers, symbols):
    try:
        return providers.get_quote(symbols)  # type: ignore[attr-defined]
    except Exception:
        return {}

def _build_synthetic_quotes(symbols, now):
    out = {}
    ts = now.timestamp()
    for exch, sym in symbols:
        out[f"{exch}:{sym}"] = {
            'last_price': 0.0,
            'volume': 0,
            'oi': 0,
            'timestamp': ts,
        }
    logger.info("Synthetic quotes generated count=%d", len(out))
    return out

__all__ = ["run_snapshot_collectors"]
