"""Persistence & metrics emission helper extracted from unified_collectors.

Keeps semantics identical; returns original PersistResult.
"""
from __future__ import annotations

import logging
from typing import Any

from src.collectors.persist_result import PersistResult
from src.error_handling import handle_collector_error
from src.utils.exceptions import CsvWriteError, InfluxWriteError

logger = logging.getLogger(__name__)

__all__ = ["persist_and_metrics"]


def persist_and_metrics(ctx, enriched_data: dict[str, dict[str, Any]], index_symbol: str, expiry_rule: str, expiry_date,
                        collection_time, index_price, index_ohlc, allow_per_option_metrics: bool) -> PersistResult:
    try:
        metrics_payload = ctx.csv_sink.write_options_data(
            index_symbol, expiry_date, enriched_data, collection_time,
            index_price=index_price, index_ohlc=index_ohlc,
            suppress_overview=True, return_metrics=True,
            expiry_rule_tag=expiry_rule
        )
    except (OSError, CsvWriteError) as e:
        # Emit CSV write error counter for Grafana wiring (best-effort)
        try:
            metrics = getattr(ctx, 'metrics', None) or getattr(getattr(ctx, 'csv_sink', None), 'metrics', None)
            if metrics is not None and hasattr(metrics, 'csv_write_errors'):
                metrics.csv_write_errors.inc()  # type: ignore[call-arg]
        except Exception:
            pass
        handle_collector_error(
            CsvWriteError(f"CSV write failed for {index_symbol} {expiry_rule} (expiry {expiry_date}): {e}"),
            component="collectors.unified_collectors", index_name=index_symbol,
            context={"stage":"csv_write","rule":expiry_rule,"expiry":str(expiry_date)}
        )
        return PersistResult(option_count=0, pcr=None, metrics_payload=None, failed=True)
    except Exception as e:  # pragma: no cover
        logger.error(f"Unexpected CSV write error {index_symbol} {expiry_rule}: {e}")
        return PersistResult(option_count=0, pcr=None, metrics_payload=None, failed=True)

    influx_sink = ctx.influx_sink
    if influx_sink:
        try:
            influx_sink.write_options_data(index_symbol, expiry_date, enriched_data, collection_time)
        except Exception as e:
            handle_collector_error(
                InfluxWriteError(f"Influx write failed for {index_symbol} {expiry_rule} (expiry {expiry_date}): {e}"),
                component="collectors.unified_collectors", index_name=index_symbol,
                context={"stage":"influx_write","rule":expiry_rule,"expiry":str(expiry_date)}
            )

    metrics = ctx.metrics
    if metrics:
        try:
            metrics.options_collected.labels(index=index_symbol, expiry=expiry_rule).set(len(enriched_data))
            metrics.options_processed_total.inc(len(enriched_data))
            try:
                metrics.index_options_processed_total.labels(index=index_symbol).inc(len(enriched_data))
            except Exception:
                pass
        except Exception:
            logger.debug(f"Failed options_collected metric for {index_symbol}")
        try:
            call_oi = sum(float(d.get('oi',0)) for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper()=='CE')
            put_oi = sum(float(d.get('oi',0)) for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper()=='PE')
            pcr = put_oi / call_oi if call_oi>0 else 0
            metrics.pcr.labels(index=index_symbol, expiry=expiry_rule).set(pcr)
        except Exception:
            logger.debug(f"Failed PCR metric for {index_symbol}")
        try:
            if allow_per_option_metrics:
                try:
                    from src.metrics.cardinality_manager import get_cardinality_manager  # type: ignore
                except Exception:
                    get_cardinality_manager = None  # type: ignore
                mgr = None
                if get_cardinality_manager:
                    try:
                        mgr = get_cardinality_manager()
                        if hasattr(mgr, 'set_metrics'):
                            mgr.set_metrics(metrics)
                    except Exception:
                        mgr = None
                atm_reference = None
                for symbol, data in enriched_data.items():
                    strike_val = data.get('strike') or data.get('strike_price') or 0
                    opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                    if not strike_val or opt_type not in ('CE','PE'):
                        continue
                    emit = True
                    representative_price = data.get('last_price')
                    if mgr and getattr(mgr, 'enabled', False):
                        try:
                            emit = mgr.should_emit(index=index_symbol, expiry=expiry_rule, strike=float(strike_val), opt_type=opt_type, atm_strike=atm_reference, value=representative_price)
                        except Exception:
                            emit = True
                    if not emit:
                        continue
                    try:
                        metrics.option_price.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('last_price',0) or 0))
                        metrics.option_volume.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('volume',0) or 0))
                        metrics.option_oi.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('oi',0) or 0))
                        metrics.option_iv.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('iv',0) or 0))
                        if 'delta' in data: metrics.option_delta.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('delta') or 0))
                        if 'gamma' in data: metrics.option_gamma.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('gamma') or 0))
                        if 'theta' in data: metrics.option_theta.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('theta') or 0))
                        if 'vega' in data: metrics.option_vega.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('vega') or 0))
                        if 'rho' in data: metrics.option_rho.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('rho') or 0))
                    except Exception:
                        logger.debug("Per-option metric emission failure", exc_info=True)
        except Exception:
            logger.debug(f"Failed per-option metrics for {index_symbol}", exc_info=True)
    pcr_val = None
    try:
        if metrics_payload:
            pcr_val = metrics_payload.get('pcr')
    except Exception:
        pass
    return PersistResult(option_count=len(enriched_data), pcr=pcr_val, metrics_payload=metrics_payload, failed=False)


def persist_with_context(ctx, enriched_data: dict[str, dict[str, Any]], expiry_ctx: Any, index_ohlc) -> PersistResult:
    """Wrapper using ExpiryContext to reduce call-site argument noise."""
    return persist_and_metrics(
        ctx,
        enriched_data,
        expiry_ctx.index_symbol,
        expiry_ctx.expiry_rule,
        expiry_ctx.expiry_date,
        expiry_ctx.collection_time,
        expiry_ctx.index_price,
        index_ohlc,
        expiry_ctx.allow_per_option_metrics,
    )
