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

import logging
import os
import warnings

logger = logging.getLogger(__name__)
_EMITTED: set[str] = set()

# Legacy per-script suppression env vars to fold into unified G6_SUPPRESS_DEPRECATIONS.
_LEGACY_SUPPRESS_VARS = [
    "G6_SUPPRESS_DEPRECATED_RUN_LIVE",
    "G6_SUPPRESS_BENCHMARK_DEPRECATED",
    "G6_SUPPRESS_DEPRECATED_WARNINGS",
]

def _normalize_suppression_env() -> None:
    """Map legacy suppression env vars to unified G6_SUPPRESS_DEPRECATIONS.

    Precedence rules:
      1. If G6_SUPPRESS_DEPRECATIONS already set, legacy keys are ignored (one-time notice if verbose).
      2. Else if any legacy key truthy, set G6_SUPPRESS_DEPRECATIONS to that truthy value and emit a deprecation warning.
      3. Conflicting legacy keys (mixed truthy/falsey) resolve to truthy if any truthy present.
    """
    if "G6_SUPPRESS_DEPRECATIONS" in os.environ:
        # Optionally log if verbose deprecations enabled and legacy still present.
        if any(k in os.environ for k in _LEGACY_SUPPRESS_VARS) and _truthy(os.environ.get("G6_VERBOSE_DEPRECATIONS")):
            try:
                logger.warning(
                    "deprecations.suppress_legacy_ignored: legacy suppression env vars present but overridden by G6_SUPPRESS_DEPRECATIONS"
                )
            except Exception:
                pass
        return
    # Aggregate legacy truthy values.
    legacy_truthy = False
    legacy_set = []
    for key in _LEGACY_SUPPRESS_VARS:
        if key in os.environ:
            legacy_set.append(key)
            if _truthy(os.environ.get(key)):
                legacy_truthy = True
    if not legacy_set:
        return
    if legacy_truthy:
        os.environ.setdefault("G6_SUPPRESS_DEPRECATIONS", "1")
    # Emit single consolidated deprecation notice (not suppressed by the newly set flag since it's critical guidance).
    try:
        warnings.warn(
            "Legacy suppression env vars (%s) are deprecated; use G6_SUPPRESS_DEPRECATIONS=1 instead" % ", ".join(legacy_set),
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "deprecations.suppress_legacy_mapped legacy=%s mapped_value=%s",
            ",".join(legacy_set),
            os.environ.get("G6_SUPPRESS_DEPRECATIONS","0")
        )
    except Exception:  # pragma: no cover
        pass

# Normalize at import so later checks see unified state.
try:  # pragma: no cover - defensive
    _normalize_suppression_env()
except Exception:
    pass

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
