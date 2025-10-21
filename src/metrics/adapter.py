#!/usr/bin/env python3
"""Metrics Adapter Layer

Goal: central point for creating/accessing on-demand metrics that were historically
instantiated ad-hoc inside hot paths (e.g., expiry processor). This first extraction
covers `empty_quote_fields_total` only. Future migrations: strike coverage, salvage counts, etc.

Usage:
    from src.metrics.adapter import MetricsAdapter
    adapter = MetricsAdapter(metrics_registry)
    adapter.record_empty_quote_fields(index_symbol, expiry_rule)

Design:
- Lazy create the counter once per adapter instance (guard attribute on registry).
- Remains graceful if prometheus_client is unavailable or registry is None.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

class MetricsAdapter:
    def __init__(self, registry: Any):  # registry may be None
        self._reg = registry

    def _ensure_empty_quote_counter(self):  # pragma: no cover - trivial guard
        if not self._reg:
            return None
        if hasattr(self._reg, 'empty_quote_fields_total'):
            return self._reg.empty_quote_fields_total
        try:
            from prometheus_client import Counter  # type: ignore
            self._reg.empty_quote_fields_total = Counter(  # type: ignore[attr-defined]
                'g6_empty_quote_fields_total',
                'Count of expiries where all quotes missing volume/oi/avg_price',
                ['index','expiry_rule'],
            )
            return self._reg.empty_quote_fields_total
        except Exception:
            logger.debug('empty_quote_counter_init_failed', exc_info=True)
            return None

    def record_empty_quote_fields(self, index: str, expiry_rule: str):  # pragma: no cover - simple increment
        try:
            c = self._ensure_empty_quote_counter()
            if c is not None:
                c.labels(index=index, expiry_rule=expiry_rule).inc()
        except Exception:
            logger.debug('empty_quote_counter_inc_failed', exc_info=True)


    # --- Shadow parity / gating metrics (Phase 4) ---------------------------------
    def _ensure_shadow_parity_counters(self):  # pragma: no cover
        if not self._reg:
            return None, None
        ok_attr = 'shadow_parity_ok_total'
        diff_attr = 'shadow_parity_diff_total'
        created = []
        try:
            from prometheus_client import Counter  # type: ignore
        except Exception:
            return None, None
        if not hasattr(self._reg, ok_attr):
            try:
                setattr(self._reg, ok_attr, Counter(  # type: ignore[attr-defined]
                    'g6_shadow_parity_ok_total',
                    'Count of shadow pipeline cycles with zero structural diffs',
                    ['index','rule'],
                ))
                created.append(ok_attr)
            except Exception:
                pass
        if not hasattr(self._reg, diff_attr):
            try:
                setattr(self._reg, diff_attr, Counter(  # type: ignore[attr-defined]
                    'g6_shadow_parity_diff_total',
                    'Count of shadow pipeline cycles with >=1 structural diff field',
                    ['index','rule'],
                ))
                created.append(diff_attr)
            except Exception:
                pass
        return getattr(self._reg, ok_attr, None), getattr(self._reg, diff_attr, None)

    def _ensure_shadow_parity_gauges(self):  # pragma: no cover
        if not self._reg:
            return None, None
        ratio_attr = 'shadow_parity_ok_ratio'
        window_attr = 'shadow_parity_window_size'
        try:
            from prometheus_client import Gauge  # type: ignore
        except Exception:
            return None, None
        if not hasattr(self._reg, ratio_attr):
            try:
                setattr(self._reg, ratio_attr, Gauge(  # type: ignore[attr-defined]
                    'g6_shadow_parity_ok_ratio',
                    'Rolling window parity OK ratio (shadow structural parity)',
                    ['index','rule'],
                ))
            except Exception:
                pass
        if not hasattr(self._reg, window_attr):
            try:
                setattr(self._reg, window_attr, Gauge(  # type: ignore[attr-defined]
                    'g6_shadow_parity_window_size',
                    'Current sample count in parity ratio window',
                    ['index','rule'],
                ))
            except Exception:
                pass
        return getattr(self._reg, ratio_attr, None), getattr(self._reg, window_attr, None)

    def record_shadow_parity(self, index: str, rule: str, *, diff_count: int, decision: dict | None):  # pragma: no cover
        """Emit shadow parity counters/gauges.

        diff_count: number of differing structural fields (0 => ok)
        decision: gating decision dict (may include ratio/window)
        """
        try:
            ok_c, diff_c = self._ensure_shadow_parity_counters()
            ratio_g, window_g = self._ensure_shadow_parity_gauges()
            if diff_count == 0 and ok_c is not None:
                ok_c.labels(index=index, rule=rule).inc()
            elif diff_count > 0 and diff_c is not None:
                diff_c.labels(index=index, rule=rule).inc()
            if decision:
                ratio = decision.get('parity_ok_ratio')
                window = decision.get('window_size')
                if ratio is not None and ratio_g is not None:
                    try:
                        ratio_g.labels(index=index, rule=rule).set(float(ratio))
                    except Exception:
                        pass
                if window is not None and window_g is not None:
                    try:
                        window_g.labels(index=index, rule=rule).set(int(window))
                    except Exception:
                        pass
        except Exception:
            logger.debug('shadow_parity_metrics_failed', exc_info=True)

    # --- Shadow gating decision metrics -----------------------------------------
    def _ensure_shadow_gating_metrics(self):  # pragma: no cover
        if not self._reg:
            return None, None
        dec_attr = 'shadow_gating_decisions_total'
        promo_attr = 'shadow_gating_promotions_total'
        try:
            from prometheus_client import Counter  # type: ignore
        except Exception:
            return None, None
        if not hasattr(self._reg, dec_attr):
            try:
                setattr(self._reg, dec_attr, Counter(  # type: ignore[attr-defined]
                    'g6_shadow_gating_decisions_total',
                    'Count of shadow gating decisions emitted (by mode+reason)',
                    ['index','rule','mode','reason'],
                ))
            except Exception:
                pass
        if not hasattr(self._reg, promo_attr):
            try:
                setattr(self._reg, promo_attr, Counter(  # type: ignore[attr-defined]
                    'g6_shadow_gating_promotions_total',
                    'Count of successful shadow promotions (promote=true decisions)',
                    ['index','rule'],
                ))
            except Exception:
                pass
        return getattr(self._reg, dec_attr, None), getattr(self._reg, promo_attr, None)

    def record_shadow_gating(self, index: str, rule: str, decision: dict | None):  # pragma: no cover
        if not decision:
            return
        try:
            dec_c, promo_c = self._ensure_shadow_gating_metrics()
            if dec_c is not None:
                mode = str(decision.get('mode') or 'na')
                reason = str(decision.get('reason') or 'na')
                try:
                    dec_c.labels(index=index, rule=rule, mode=mode, reason=reason).inc()
                except Exception:
                    pass
            if decision.get('promote') and promo_c is not None:
                try:
                    promo_c.labels(index=index, rule=rule).inc()
                except Exception:
                    pass
        except Exception:
            logger.debug('shadow_gating_metrics_failed', exc_info=True)

    # --- Shadow churn / rollback metrics (Phase 5) -----------------------------
    def _ensure_shadow_churn_metrics(self):  # pragma: no cover
        if not self._reg:
            return None, None
        churn_attr = 'shadow_hash_churn_ratio'
        rollback_attr = 'shadow_rollbacks_total'
        try:
            from prometheus_client import Counter, Gauge  # type: ignore
        except Exception:
            return None, None
        if not hasattr(self._reg, churn_attr):
            try:
                setattr(self._reg, churn_attr, Gauge(  # type: ignore[attr-defined]
                    'g6_shadow_hash_churn_ratio',
                    'Distinct parity hash count / window size (volatility indicator)',
                    ['index','rule'],
                ))
            except Exception:
                pass
        if not hasattr(self._reg, rollback_attr):
            try:
                setattr(self._reg, rollback_attr, Counter(  # type: ignore[attr-defined]
                    'g6_shadow_rollbacks_total',
                    'Count of gating rollbacks triggered (e.g., protected diff threshold)',
                    ['index','rule','reason'],
                ))
            except Exception:
                pass
        return getattr(self._reg, churn_attr, None), getattr(self._reg, rollback_attr, None)

    def record_shadow_churn(self, index: str, rule: str, decision: dict | None):  # pragma: no cover
        if not decision:
            return
        try:
            churn_g, rollback_c = self._ensure_shadow_churn_metrics()
            ratio = decision.get('hash_churn_ratio')
            if ratio is not None and churn_g is not None:
                try:
                    churn_g.labels(index=index, rule=rule).set(float(ratio))
                except Exception:
                    pass
            # rollback detection: reason starts with 'rollback_' or explicit flag later
            reason = str(decision.get('reason') or '')
            if rollback_c is not None and reason.startswith('rollback_'):
                try:
                    rollback_c.labels(index=index, rule=rule, reason=reason).inc()
                except Exception:
                    pass
        except Exception:
            logger.debug('shadow_churn_metrics_failed', exc_info=True)

    # --- Protected field diff counters (optional / allowlisted) --------------
    def _ensure_shadow_protected_field_counter(self):  # pragma: no cover
        if not self._reg:
            return None
        attr = 'shadow_protected_field_diff_total'
        if hasattr(self._reg, attr):
            return getattr(self._reg, attr)
        try:
            from prometheus_client import Counter  # type: ignore
        except Exception:
            return None
        try:
            setattr(self._reg, attr, Counter(  # type: ignore[attr-defined]
                'g6_shadow_protected_field_diff_total',
                'Count of cycles where a protected field diff occurred (allowlisted)',
                ['index','rule','field'],
            ))
        except Exception:
            pass
        return getattr(self._reg, attr, None)

    def record_shadow_protected_field_diffs(self, index: str, rule: str, diff_fields, *, protected_fields: tuple[str,...]):  # pragma: no cover
        try:
            allow_raw = os.getenv('G6_SHADOW_PROTECTED_METRICS_FIELDS','').strip()
            if not allow_raw:
                return
            if allow_raw == '*':
                allow = set(protected_fields)
            else:
                allow = {f.strip() for f in allow_raw.split(',') if f.strip()}
            pf = set(protected_fields)
            target = pf.intersection(diff_fields).intersection(allow)
            if not target:
                return
            c = self._ensure_shadow_protected_field_counter()
            if c is None:
                return
            for f in target:
                try:
                    c.labels(index=index, rule=rule, field=f).inc()
                except Exception:
                    pass
        except Exception:
            logger.debug('shadow_protected_field_metrics_failed', exc_info=True)

__all__ = ["MetricsAdapter"]
