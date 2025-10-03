"""Centralized deprecation warning helpers.

Enhancements (2025-10-02):
 - Added generic `emit_deprecation` function supporting:
     * One-time emission (default) keyed by logical id.
     * Optional repeat when `G6_VERBOSE_DEPRECATIONS=1` (debugging).
     * Global suppression via `G6_SUPPRESS_DEPRECATIONS` (already policy for script stubs).
     * Custom logger channel while still issuing a Python `DeprecationWarning`.
 - Existing `check_pipeline_flag_deprecation` now delegates to generic helper.
 - Backward compatibility preserved: existing imports keep functioning.
"""
from __future__ import annotations

import os, warnings, logging

logger = logging.getLogger(__name__)
_EMITTED: set[str] = set()

def _truthy(val: str | None) -> bool:
    return bool(val) and str(val).lower() in {"1","true","yes","on"}

def emit_deprecation(
    key: str,
    message: str,
    *,
    repeat: bool | None = None,
    log: logging.Logger | None = None,
    critical: bool = False,
    force: bool = False,
) -> None:
    """Emit a standardized deprecation warning.

    Parameters
    ----------
    key: str
        Logical identifier used to ensure one-time emission unless verbose mode / repeat.
    message: str
        Human-readable guidance (actionable replacement preferred).
    repeat: bool | None
        Override one-time behavior. When None (default) repeats only if verbose env set.
    log: logging.Logger | None
        Logger to use (defaults to module logger).
    """
    if _truthy(os.environ.get("G6_SUPPRESS_DEPRECATIONS")) and not critical:
        return
    verbose = _truthy(os.environ.get("G6_VERBOSE_DEPRECATIONS"))
    allow_repeat = verbose if repeat is None else repeat
    if not force and not allow_repeat and key in _EMITTED:
        return
    _EMITTED.add(key)
    try:
        warnings.warn(message, DeprecationWarning, stacklevel=3)
    except Exception:  # pragma: no cover - defensive
        pass
    (log or logger).warning(message)

def check_pipeline_flag_deprecation() -> None:
    if os.environ.get('G6_PIPELINE_COLLECTOR') is not None:
        emit_deprecation(
            'G6_PIPELINE_COLLECTOR',
            'G6_PIPELINE_COLLECTOR is deprecated: pipeline is default. Remove this flag; use G6_LEGACY_COLLECTOR=1 to force legacy.'
        )

__all__ = ["check_pipeline_flag_deprecation", "emit_deprecation"]
