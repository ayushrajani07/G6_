"""Diagnostics utilities (Phase 4 A7 skeleton)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

class Diagnostics:
    def __init__(self) -> None:
        self._emitted: set[str] = set()

    def emit_once(self, key: str, message: str) -> None:
        if key not in self._emitted:
            logger.info(message)
            self._emitted.add(key)

    def snapshot(self, *, core: Any | None = None, legacy_provider: Any | None = None) -> dict[str, Any]:
        """Return aggregated diagnostics.

        Parameters:
            core: Optional ProviderCore instance (for direct cache/auth data).
            legacy_provider: Optional legacy KiteProvider (for synthetic flags until fully migrated).
        """
        out: dict[str, Any] = {"emitted_diagnostics": len(self._emitted)}
        try:
            if core is not None:
                # Auth status
                auth_mgr = getattr(core, 'auth', None)
                out['auth_failed'] = bool(getattr(auth_mgr, 'auth_failed', False))
                # Instrument cache stats
                inst_cache = getattr(core, 'instruments', None)
                if inst_cache is not None:
                    cache_obj = getattr(inst_cache, '_cache', {}) or {}
                    out['instrument_exchanges'] = len(cache_obj)
                    out['instrument_totals'] = sum(len(v or []) for v in cache_obj.values())
                    out['instrument_cache_detail'] = {k: len(v or []) for k, v in cache_obj.items()}
                # Expiry cache stats
                exp_res = getattr(core, 'expiries', None)
                if exp_res is not None:
                    exp_cache = getattr(exp_res, '_cache', {}) or {}
                    out['expiry_indices'] = len(exp_cache)
                    out['expiry_cache_detail'] = {k: len(v or []) for k, v in exp_cache.items()}
            if legacy_provider is not None:
                # Synthetic quote flags until migrated
                out['legacy_synthetic_quotes_used'] = int(getattr(legacy_provider, '_synthetic_quotes_used', 0))
                out['legacy_last_quotes_synthetic'] = bool(getattr(legacy_provider, '_last_quotes_synthetic', False))
                out['legacy_used_instrument_fallback'] = bool(getattr(legacy_provider, '_used_fallback', False))
        except Exception:  # pragma: no cover - defensive
            pass
        return out
