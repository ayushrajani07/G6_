"""Backward compatibility shim for removed enhanced_collector.

This module preserves the public symbol run_enhanced_collectors but simply
routes to the unified collectors (for persistence) or snapshot collectors
when snapshot semantics are desired. Environment flags control behavior:

  G6_ENHANCED_SNAPSHOT_MODE=1 -> uses snapshot collectors (no persistence)
  Otherwise -> unified collectors with optional env-based filters already
               integrated into expiry_processor.

Deprecated: code depending on enhanced_collector should migrate to calling
run_unified_collectors (persistence) or run_snapshot_collectors explicitly.
This shim will be removed in a future major release.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .snapshot_collectors import run_snapshot_collectors
from .unified_collectors import run_unified_collectors

logger = logging.getLogger(__name__)

def run_enhanced_collectors(index_params: dict[str, Any], providers, csv_sink, influx_sink, metrics, *_, **kw):  # signature kept lax
    # Determine snapshot intent: explicit kw flag or env overrides
    snapshot_intent = bool(kw.get('return_snapshots')) or os.environ.get('G6_RETURN_SNAPSHOTS','').lower() in ('1','true','yes','on')
    if os.environ.get('G6_ENHANCED_SNAPSHOT_MODE','').lower() in ('1','true','yes','on') or snapshot_intent:
        logger.warning('enhanced_shim: snapshot mode active (no persistence)')
        return run_snapshot_collectors(index_params, providers, return_snapshots=snapshot_intent)
    logger.warning('enhanced_shim: delegating to unified collectors (enhanced_collector removed)')
    return run_unified_collectors(index_params, providers, csv_sink, influx_sink, metrics, build_snapshots=False)

__all__ = ['run_enhanced_collectors']
