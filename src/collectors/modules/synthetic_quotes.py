"""Phase 6: Synthetic Quote Generation Extraction

Wraps the existing synthetic quote builder imported from `src.synthetic.strategy`.
Provides a stable pipeline-facing API so enrichment fallback logic can be shared
outside the monolith.

Public Functions:
- build_synthetic_quotes(instruments) -> dict
- record_synthetic_metrics(ctx, index_symbol, expiry_date)

The metric pop logic mirrors `_synthetic_metric_pop` from legacy but is kept
non-fatal and best-effort.
"""
from __future__ import annotations
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)

__all__ = ["build_synthetic_quotes", "record_synthetic_metrics"]

try:  # pragma: no cover
    from src.synthetic.strategy import build_synthetic_quotes as _legacy_build_synth  # type: ignore
except Exception:  # pragma: no cover
    def _legacy_build_synth(instruments: List[Dict[str, Any]]):  # type: ignore
        # Fallback empty implementation (parity safe; triggers warning higher up)
        return {}

def build_synthetic_quotes(instruments: List[Dict[str, Any]]):
    try:
        return _legacy_build_synth(instruments)
    except Exception:
        logger.debug("synthetic_build_failed", exc_info=True)
        return {}

def record_synthetic_metrics(ctx: Any, index_symbol: str, expiry_date) -> None:
    """Replicate legacy synthetic usage metric update (best-effort)."""
    try:
        metrics = getattr(ctx, 'metrics', None)
        providers = getattr(ctx, 'providers', None)
        if metrics and hasattr(metrics, 'synthetic_quotes_used_total') and providers and hasattr(providers, 'primary_provider'):
            prov = getattr(providers, 'primary_provider', None)
            if prov and hasattr(prov, 'pop_synthetic_quote_usage'):
                synth_count, was_synth = prov.pop_synthetic_quote_usage()  # type: ignore[attr-defined]
                if synth_count > 0 or was_synth:
                    try:
                        metrics.synthetic_quotes_used_total.labels(index=index_symbol, expiry=str(expiry_date)).inc(synth_count or 0)  # type: ignore[attr-defined]
                    except Exception:
                        logger.debug("synthetic_metric_inc_failed", exc_info=True)
    except Exception:
        logger.debug("synthetic_metric_pop_failed", exc_info=True)
