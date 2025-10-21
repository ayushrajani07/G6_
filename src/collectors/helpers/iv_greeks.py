"""IV estimation helper extracted from unified_collectors.

Keeps original logic and metric side-effects identical.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["iv_estimation_block"]

def iv_estimation_block(ctx, enriched_data, index_symbol, expiry_rule, expiry_date, index_price, greeks_calculator,
                        estimate_iv, risk_free_rate, iv_max_iterations, iv_min, iv_max, iv_precision):
    metrics = getattr(ctx, 'metrics', None)
    if not (estimate_iv and greeks_calculator):
        return
    try:
        spot = float(index_price)
        solver_max_iter = iv_max_iterations or 100
        solver_min_iv = iv_min if iv_min is not None else 0.01
        solver_max_iv = iv_max if iv_max is not None else 5.0
        solver_precision = iv_precision if iv_precision is not None else 1e-5
        iv_success = iv_fail = total_iter = 0
        for symbol, data in enriched_data.items():
            try:
                strike = float(data.get('strike') or data.get('strike_price') or 0)
                if strike <= 0 or spot <= 0:
                    continue
                opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                is_call = opt_type == 'CE'
                market_price = float(data.get('last_price', 0))
                if market_price <= 0:
                    continue
                existing_iv = float(data.get('iv', 0))
                if existing_iv <= 0:
                    iv_result = greeks_calculator.implied_volatility(
                        is_call=is_call, S=spot, K=strike, T=expiry_date, market_price=market_price,
                        r=risk_free_rate, max_iterations=solver_max_iter, precision=solver_precision,
                        min_iv=solver_min_iv, max_iv=solver_max_iv, return_iterations=True
                    )
                    if isinstance(iv_result, tuple):
                        iv_est, iters = iv_result
                    else:  # pragma: no cover
                        iv_est, iters = iv_result, 0
                    if metrics and hasattr(metrics, 'iv_iterations_histogram') and iters is not None:
                        try:
                            metrics.iv_iterations_histogram.labels(index=index_symbol, expiry=expiry_rule).observe(iters)
                        except Exception:
                            pass
                    if iv_est > 0:
                        if iv_est < solver_min_iv:
                            iv_est = solver_min_iv
                        elif iv_est > solver_max_iv:
                            iv_est = solver_max_iv
                        data['iv'] = iv_est
                        iv_success += 1
                    else:
                        iv_fail += 1
                    total_iter += iters
            except Exception as iv_e:
                logger.debug(f"IV estimation failed for {symbol}: {iv_e}")
        if metrics:
            try:
                if hasattr(metrics, 'iv_success') and iv_success:
                    metrics.iv_success.labels(index=index_symbol, expiry=expiry_rule).inc(iv_success)
                if hasattr(metrics, 'iv_fail') and iv_fail:
                    metrics.iv_fail.labels(index=index_symbol, expiry=expiry_rule).inc(iv_fail)
                if hasattr(metrics, 'iv_iterations') and (iv_success + iv_fail) > 0:
                    metrics.iv_iterations.labels(index=index_symbol, expiry=expiry_rule).set(total_iter / (iv_success + iv_fail))
                if hasattr(metrics, 'iv_solver_iterations') and total_iter > 0:  # pragma: no cover
                    try:
                        avg_iters = total_iter / max(1, (iv_success + iv_fail))
                        metrics.iv_solver_iterations.observe(avg_iters)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                logger.debug("Failed updating IV estimation metrics", exc_info=True)
    except Exception as batch_e:
        logger.error(f"IV estimation batch failed for {index_symbol} {expiry_rule}: {batch_e}")
