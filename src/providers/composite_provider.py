"""CompositeProvider offering sequential failover among multiple underlying providers.

Usage:
    cp = CompositeProvider([primary, secondary, tertiary], metrics=metrics, name="market")
    price, ohlc = cp.get_index_data("NIFTY")

Environment:
    G6_PROVIDER_FAILFAST (bool) if set (1/true/on) aborts after first failure instead of continuing.

Metrics:
    g6_provider_failover_total{from,to} incremented when a fallback provider succeeds after a prior one failed.

Events (best effort):
    Emits events 'provider_fail' and 'provider_failover' if event_log.dispatch available.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # optional events
    from src.events.event_log import dispatch as emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(*_, **__):  # type: ignore
        return None


class CompositeProvider:
    def __init__(self, providers: list[Any], metrics: Any | None = None, name: str | None = None):
        self.providers = [p for p in providers if p is not None]
        self.metrics = metrics
        self.name = name or "composite"
        if not self.providers:
            raise ValueError("CompositeProvider requires at least one provider")

    # --- Core Facade Methods (subset) ---
    def get_index_data(self, index_symbol: str):  # returning (price, ohlc?) like existing providers
        return self._exec_with_failover('get_index_data', index_symbol)

    def get_quote(self, instruments):
        return self._exec_with_failover('get_quote', instruments)

    def get_ltp(self, instruments):  # used in some code paths
        return self._exec_with_failover('get_ltp', instruments)

    # Optional interface pass-throughs if present on underlying provider
    def resolve_expiry(self, index_symbol: str, expiry_rule: str):  # chain to first that supports
        for p in self.providers:
            if hasattr(p, 'resolve_expiry'):
                try:
                    return p.resolve_expiry(index_symbol, expiry_rule)  # type: ignore
                except Exception:
                    continue
        raise AttributeError('No underlying provider could resolve expiry')

    # --- Internal failover helper ---
    def _exec_with_failover(self, method: str, *args, **kwargs):
        first_exc = None
        for idx, prov in enumerate(self.providers):
            if not hasattr(prov, method):
                continue
            m = getattr(prov, method)
            try:
                result = m(*args, **kwargs)
                # If earlier providers failed and this one succeeded, record failover
                if idx > 0:
                    prev = self._first_provider_name(idx)
                    curr = type(prov).__name__
                    self._record_failover(prev, curr)
                return result
            except Exception as e:  # collect and continue
                if idx == 0:
                    first_exc = e
                prev_name = type(prov).__name__
                logger.warning("CompositeProvider %s.%s failed provider=%s err=%s", self.name, method, prev_name, e)
                emit_event("provider_fail", context={"method": method, "provider": prev_name, "error": str(e)})
                from src.utils.env_flags import is_truthy_env  # type: ignore
                if is_truthy_env('G6_PROVIDER_FAILFAST'):
                    raise
                continue
        # Exhausted
        if first_exc:
            raise first_exc
        raise RuntimeError(f"CompositeProvider: no provider could execute method {method}")

    def _first_provider_name(self, idx_success: int) -> str:
        # find the first prior provider that exists (simplest: idx_success-1)
        for i in range(idx_success -1, -1, -1):
            try:
                return type(self.providers[i]).__name__
            except Exception:  # pragma: no cover
                pass
        return 'unknown'

    def _record_failover(self, from_name: str, to_name: str):
        try:
            if self.metrics and hasattr(self.metrics, 'provider_failover'):
                self.metrics.provider_failover.labels(src=from_name, dest=to_name).inc()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            emit_event("provider_failover", context={"from": from_name, "to": to_name, "composite": self.name})
        except Exception:
            pass

__all__ = ["CompositeProvider"]
