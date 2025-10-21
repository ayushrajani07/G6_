"""Deprecated legacy cycle tables module (no-op).

Historically this module accumulated per-cycle instrument prefilter and option
match statistics and rendered two human readable tables ("Prefilter Targets"
and "Option Match Stats") plus a phase timing footer. These tables have been
retired in favor of the structured event system (STRUCT lines) which already
carries the underlying data in a machine-friendly & optionally human concise
format.

We intentionally retain the public function names as light no-ops so that any
existing imports continue to work without code changes. A future cleanup may
remove this file entirely once downstream code confirms it no longer imports
these symbols.

Environment flags that previously influenced behaviour are now inert:
  - G6_DISABLE_CYCLE_TABLES
  - G6_DEFER_CYCLE_TABLES
  - G6_CYCLE_TABLE_GRACE_MS / G6_CYCLE_TABLE_GRACE_MAX_MS

All functions accept their prior signatures (loosely) but discard inputs.
"""
from __future__ import annotations

import os
from typing import Any

_PHASES: list[dict[str, Any]] = []  # retained for compatibility (not emitted)
_PIPELINE_SUMMARY: dict[str, Any] | None = None  # new optional integration payload

# --------------- Record Functions ---------------

def record_prefilter(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Deprecated: previously buffered prefilter summary rows (now ignored)."""
    return

def record_option_stats(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Deprecated: previously buffered option match stats rows (now ignored)."""
    return

def record_strike_adjust(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Deprecated: previously tracked strike depth adjustment events."""
    return

def record_adaptive(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Deprecated: previously tracked adaptive controller summaries."""
    return

def record_phase_timing(name: str, duration_s: float) -> None:  # pragma: no cover
    """Retained for compatibility; stores timing silently for potential debug."""
    try:
        _PHASES.append({'name': name, 'dur': round(float(duration_s), 3)})
    except Exception:
        pass

# --------------- Emission ---------------

def emit_cycle_tables(cycle_payload: dict[str, Any]) -> None:  # pragma: no cover
    """Emit legacy cycle tables with optional pipeline summary injection.

    When G6_CYCLE_TABLES_PIPELINE_INTEGRATION is truthy and a pipeline summary has
    been recorded this function mutates the provided cycle_payload in-place by
    attaching a 'pipeline_summary' key. This preserves backward compatibility
    while allowing legacy listeners still hooked into emit_cycle_tables to gain
    access to modern executor summary metrics without parsing panel exports.
    """
    try:
        if os.getenv('G6_CYCLE_TABLES_PIPELINE_INTEGRATION','').lower() in ('1','true','yes','on') and _PIPELINE_SUMMARY:
            cycle_payload['pipeline_summary'] = _PIPELINE_SUMMARY
    except Exception:
        pass

def record_pipeline_summary(summary: dict[str, Any]) -> None:  # pragma: no cover
    """Record latest pipeline summary for optional legacy integration layer."""
    global _PIPELINE_SUMMARY
    try:
        _PIPELINE_SUMMARY = dict(summary)  # shallow copy for isolation
    except Exception:
        pass

def get_pipeline_summary() -> dict[str, Any] | None:  # pragma: no cover
    """Return last recorded pipeline summary (or None)."""
    return _PIPELINE_SUMMARY

def flush_deferred_cycle_tables() -> None:  # pragma: no cover
    """Deprecated: no-op (deferred flush removed)."""
    return

__all__ = [
    'record_prefilter',
    'record_option_stats',
    'record_strike_adjust',
    'record_adaptive',
    'record_phase_timing',
    'emit_cycle_tables',
    'flush_deferred_cycle_tables',
    'record_pipeline_summary',
    'get_pipeline_summary',
]
