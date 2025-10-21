"""(Deprecated) Initialization helpers.

The original `apply_group_gating` indirection has been folded back into
`metrics.MetricsRegistry.__init__` for simplicity. This module is
retained temporarily to avoid import errors in any downstream code.
Calls now delegate directly to `gating.configure_registry_groups`.
Will be removed after deprecation window.
"""
from __future__ import annotations

from typing import Any

from src.utils.deprecations import emit_deprecation  # type: ignore

_LEGACY_WARN_EMITTED = False

def apply_group_gating(registry: Any) -> tuple[set[str], set | None, set]:  # pragma: no cover - legacy shim
    global _LEGACY_WARN_EMITTED  # noqa: PLW0603
    if not _LEGACY_WARN_EMITTED:
        try:
            emit_deprecation(
                'metrics-init_helpers-apply_group_gating',
                'init_helpers.apply_group_gating is deprecated; call gating.configure_registry_groups directly (will be removed in a future wave)'
            )
        except Exception:
            pass
        _LEGACY_WARN_EMITTED = True
    from .gating import configure_registry_groups as _cfg  # type: ignore
    return _cfg(registry)

__all__ = ["apply_group_gating"]  # kept for compatibility
