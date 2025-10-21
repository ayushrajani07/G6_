"""Coverage & field completeness helper functions extracted from unified_collectors.

This modularization step reduces the size and cognitive load of
`unified_collectors.py` while keeping existing behavior unchanged.

Functions are intentionally light on dependencies; they accept a context-like
object exposing `metrics` attribute (duck-typed) to avoid tight coupling.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

_SUPPRESS_COVERAGE_WARN = os.environ.get('G6_SUPPRESS_COVERAGE_WARNINGS','0').lower() in ('1','true','yes','on')

try:  # pragma: no cover
    from src.broker.kite.tracing import is_enabled as _trace_enabled
    from src.broker.kite.tracing import trace as _trace  # type: ignore
except Exception:  # fallback minimal gate
    def _trace(event: str, **ctx):
        if os.environ.get('G6_TRACE_COLLECTOR','0').lower() not in ('1','true','yes','on'):
            return
        try:
            logger.warning("TRACE %s | %s", event, {k: v for k, v in ctx.items() if k not in ('enriched_sample',)})
        except Exception:
            pass
    def _trace_enabled():  # type: ignore
        return os.environ.get('G6_TRACE_COLLECTOR','0').lower() in ('1','true','yes','on')

def coverage_metrics(ctx, instruments: Iterable[dict[str, Any]], strikes, index_symbol: str, expiry_rule: str, expiry_date):  # side effects only; returns strike coverage ratio (0..1)
    try:
        realized_strikes = {float(inst.get('strike', 0)) for inst in instruments if float(inst.get('strike', 0)) > 0}
        coverage_ratio = (len(realized_strikes) / len(strikes)) if strikes else 0.0
        if coverage_ratio < 0.8:
            if not _SUPPRESS_COVERAGE_WARN:
                logger.warning(
                    f"Instrument coverage low for {index_symbol} {expiry_rule} {expiry_date}: {coverage_ratio:.2%} (realized={len(realized_strikes)} requested={len(strikes)})"
                )
        else:
            logger.debug(
                f"Instrument coverage {index_symbol} {expiry_rule} {expiry_date}: {coverage_ratio:.2%} ({len(realized_strikes)}/{len(strikes)})"
            )
        if _trace_enabled():  # type: ignore
            missing = []
            if strikes:
                for s in strikes:
                    if s not in realized_strikes:
                        missing.append(s)
                        if len(missing) >= 10:
                            break
            _trace('instrument_coverage', index=index_symbol, rule=expiry_rule, expiry=str(expiry_date), requested=len(strikes), realized=len(realized_strikes), pct=round(coverage_ratio*100.0,2), sample_missing=missing)
        metrics = getattr(ctx, 'metrics', None)
        if metrics and hasattr(metrics, 'instrument_coverage_pct'):
            try:
                metrics.instrument_coverage_pct.labels(index=index_symbol, expiry=str(expiry_date)).set(coverage_ratio * 100.0)
            except Exception:
                logger.debug("Failed to set instrument coverage metric", exc_info=True)
        return coverage_ratio
    except Exception:
        logger.debug("Coverage diagnostics failed", exc_info=True)
        return None

def field_coverage_metrics(ctx, enriched_data: dict[str, Any], index_symbol: str, expiry_rule: str, expiry_date):  # side effects only; returns full-field coverage ratio (0..1)
    try:
        missing_counts = {'volume':0,'oi':0,'avg_price':0}
        total_options = 0
        for _sym, opt in enriched_data.items():
            if not isinstance(opt, dict):
                continue
            total_options += 1
            if not opt.get('volume'): missing_counts['volume'] += 1
            if not opt.get('oi'): missing_counts['oi'] += 1
            if not opt.get('avg_price'): missing_counts['avg_price'] += 1
        metrics = getattr(ctx, 'metrics', None)
        if total_options > 0:
            if metrics and hasattr(metrics, 'missing_option_fields_total'):
                for field, cnt in missing_counts.items():
                    if cnt > 0:
                        try:
                            metrics.missing_option_fields_total.labels(index=index_symbol, expiry=str(expiry_date), field=field).inc(cnt)
                        except Exception:
                            logger.debug("Failed to inc missing field metric", exc_info=True)
            full_present = sum(1 for _sym,opt in enriched_data.items() if opt.get('volume') and opt.get('oi') and opt.get('avg_price'))
            coverage_pct = (full_present / total_options) * 100.0
            if metrics and hasattr(metrics, 'option_field_coverage_ratio'):
                try:
                    metrics.option_field_coverage_ratio.labels(index=index_symbol, expiry=str(expiry_date)).set(coverage_pct)
                except Exception:
                    logger.debug("Failed to set field coverage ratio", exc_info=True)
            logger.debug(
                f"Field coverage {index_symbol} {expiry_rule} {expiry_date}: total={total_options} full={full_present} missing(volume={missing_counts['volume']},oi={missing_counts['oi']},avg_price={missing_counts['avg_price']}) ratio={coverage_pct:.2f}%"
            )
            if coverage_pct < 60.0 and not _SUPPRESS_COVERAGE_WARN:
                logger.warning(
                    f"Low option field coverage {index_symbol} {expiry_rule} {expiry_date}: {coverage_pct:.2f}% (full={full_present}/{total_options})"
                )
            if _trace_enabled():  # type: ignore
                sample_missing = []
                for sym, opt in enriched_data.items():
                    if not (opt.get('volume') and opt.get('oi') and opt.get('avg_price')):
                        sample_missing.append({
                            'sym': sym,
                            'vol': opt.get('volume'),
                            'oi': opt.get('oi'),
                            'avg_price': opt.get('avg_price'),
                            'type': (opt.get('instrument_type') or opt.get('type')),
                            'strike': opt.get('strike') or opt.get('strike_price')
                        })
                        if len(sample_missing) >= 8:
                            break
                _trace('field_coverage', index=index_symbol, rule=expiry_rule, expiry=str(expiry_date), total=total_options, full=full_present, pct=round(coverage_pct,2), missing_counts=missing_counts, sample=sample_missing)
            return coverage_pct/100.0
        else:
            return 0.0
    except Exception:
        logger.debug("Field coverage diagnostics failure", exc_info=True)
        return None

__all__ = ["coverage_metrics", "field_coverage_metrics"]
