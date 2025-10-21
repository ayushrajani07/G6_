"""Greeks computation helper extracted from unified_collectors.

Encapsulates per-option Greeks backfill using a provided calculator implementing
black_scholes(is_call,S,K,T,sigma,r) -> mapping with keys delta,gamma,theta,vega,rho.
Maintains original semantics: only fill missing (==0) greek fields, normalizes IV,
and emits success/fail/batch metrics when available.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["compute_greeks_block"]


def compute_greeks_block(ctx, enriched_data: dict[str, dict[str, Any]], index_symbol: str, expiry_rule: str,
                         expiry_date, index_price, greeks_calculator, risk_free_rate: float,
                         compute_greeks: bool, mp_manager, mem_flags):
    metrics = getattr(ctx, 'metrics', None)
    if not (compute_greeks and greeks_calculator):
        return
    try:
        skip_due_mem = False
        try:
            if mp_manager and mem_flags.get('skip_greeks'):
                skip_due_mem = True
        except Exception:  # pragma: no cover
            pass
        if skip_due_mem:
            logger.debug(f"Skipping Greek computation due to memory pressure: {index_symbol} {expiry_rule}")
            return
        greek_success = greek_fail = 0
        try:
            spot = float(index_price)
        except Exception:
            spot = 0.0
        for symbol, data in enriched_data.items():
            try:
                strike = float(data.get('strike') or data.get('strike_price') or 0)
                if strike <= 0 or spot <= 0:
                    continue
                opt_type = data.get('instrument_type') or data.get('type') or ''
                is_call = opt_type.upper() == 'CE'
                iv_raw = float(data.get('iv', 0))
                iv_fraction = iv_raw/100.0 if iv_raw > 1.5 else (iv_raw if iv_raw > 0 else 0.25)
                if iv_fraction <= 0:
                    iv_fraction = 0.25
                g = greeks_calculator.black_scholes(is_call=is_call, S=spot, K=strike, T=expiry_date,
                                                    sigma=iv_fraction, r=risk_free_rate)
                for k_src, k_dst in [('delta','delta'), ('gamma','gamma'), ('theta','theta'), ('vega','vega'), ('rho','rho')]:
                    try:
                        if float(data.get(k_dst, 0)) == 0:
                            data[k_dst] = g.get(k_src, 0)
                    except Exception:
                        pass
                if float(data.get('iv', 0)) == 0 and iv_fraction:
                    data['iv'] = iv_fraction
                greek_success += 1
            except Exception as oge:
                greek_fail += 1
                logger.debug(f"Greek calc failed for {symbol}: {oge}")
        if metrics:
            try:
                if greek_success and hasattr(metrics, 'greeks_success'):
                    metrics.greeks_success.labels(index=index_symbol, expiry=expiry_rule).inc(greek_success)
                if greek_fail and hasattr(metrics, 'greeks_fail'):
                    metrics.greeks_fail.labels(index=index_symbol, expiry=expiry_rule).inc(greek_fail)
            except Exception:  # pragma: no cover
                pass
    except Exception as gex:
        logger.error(f"Greek computation batch failed for {index_symbol} {expiry_rule}: {gex}")
        if metrics and hasattr(metrics, 'greeks_batch_fail'):
            try:
                metrics.greeks_batch_fail.labels(index=index_symbol, expiry=expiry_rule).inc()
            except Exception:  # pragma: no cover
                pass


def compute_greeks(ctx, enriched_data: dict[str, dict[str, Any]], expiry_ctx: Any, greeks_calculator, mp_manager, mem_flags):
    """Thin wrapper accepting ExpiryContext instance.

    Keeps original internal function untouched to minimize diff surface.
    """
    compute_greeks_block(
        ctx,
        enriched_data,
        expiry_ctx.index_symbol,
        expiry_ctx.expiry_rule,
        expiry_ctx.expiry_date,
        expiry_ctx.index_price,
        greeks_calculator,
        expiry_ctx.risk_free_rate or 0.0,
        expiry_ctx.compute_greeks,
        mp_manager,
        mem_flags,
    )
