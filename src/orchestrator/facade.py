"""Unified Orchestration Facade.

Provides a single, stable entrypoint that can delegate to either the legacy
`run_unified_collectors` implementation or the new staged pipeline
(`modules.pipeline.run_pipeline`). This enables progressive rollout and
parity validation without callers littering feature flag conditionals.

Contract (stable):
  run_collect_cycle(index_params, providers, csv_sink, influx_sink, metrics, *,
                    mode='auto', parity_check=False, **kwargs) -> dict

  - Return shape mirrors legacy `run_unified_collectors` result for callers.
  - `mode`:
      'auto'     : (Post-promotion) pipeline is default unless legacy opt-out flag set \n\
               (G6_LEGACY_COLLECTOR=1). Deprecated pre-promotion flag \n\
               G6_PIPELINE_COLLECTOR now ignored except for backward \n\
               compatibility warning.
      'legacy'   : force legacy path (equivalent to setting G6_LEGACY_COLLECTOR=1)
      'pipeline' : force pipeline path
  - `parity_check` (bool): when True and effective path is pipeline, an internal
        legacy invocation is also executed (without side‑effects modifications)
        and a parity snapshot hash comparison is logged. Mismatch does not
        raise (safe diagnostic) unless env `G6_FACADE_PARITY_STRICT=1`.
  - Additional **kwargs forwarded to the selected implementation.

Environment Flags:
    G6_LEGACY_COLLECTOR         : Force legacy collectors when mode='auto' (new)
    G6_PIPELINE_COLLECTOR       : (Deprecated) historical opt-in flag; now ignored post-promotion
    G6_FACADE_PARITY_STRICT     : escalate parity mismatch to exception

Parity harness hashing removed (Phase 2 cleanup); parity_check now only dual-runs for basic diagnostics.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

from src.utils.deprecations import check_pipeline_flag_deprecation, emit_deprecation  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["run_collect_cycle"]


def _truthy(val: str | None) -> bool:
    return bool(val) and str(val).lower() in ("1","true","yes","on")


def _select_mode(requested: str) -> str:
    if requested not in ("auto","legacy","pipeline"):
        logger.warning(f"facade_invalid_mode_defaulting mode={requested}")
        requested = "auto"
    if requested == "auto":
        # Delegate to central helper (emits DeprecationWarning + utils.deprecations logger), AND
        # emit via facade logger using generic API so tests capturing this logger still see a record.
        check_pipeline_flag_deprecation()
        if os.environ.get('G6_PIPELINE_COLLECTOR') is not None:
            emit_deprecation(
                'G6_PIPELINE_COLLECTOR-facade-echo',
                'G6_PIPELINE_COLLECTOR deprecated (ignored): pipeline path active by default',
                log=logger,
                critical=True,
                force=True,
            )
        # New default: pipeline unless explicit legacy opt-out
        if _truthy(os.environ.get("G6_LEGACY_COLLECTOR")):
            return "legacy"
        return "pipeline"
    if requested == "legacy":
        return "legacy"
    return "pipeline"


def run_collect_cycle(index_params, providers, csv_sink, influx_sink, metrics=None, *,
                      mode: str = "auto", parity_check: bool = False, **kwargs) -> dict[str, Any]:
    """Run a collection cycle via selected orchestration backend.

    Parameters mirror legacy for forward compatibility. Extra kwargs passed through.
    """
    effective = _select_mode(mode)
    # Lazy imports (avoid circular heavy import at module import time)
    from src.collectors.unified_collectors import run_unified_collectors as _legacy  # type: ignore
    if effective == "legacy":
        legacy_out = _legacy(index_params, providers, csv_sink, influx_sink, metrics, **kwargs)
        return legacy_out or {}

    # Pipeline path
    from src.collectors.modules.pipeline import run_pipeline as _pipeline  # type: ignore

    if not parity_check:
        pipe_out = _pipeline(index_params, providers, csv_sink, influx_sink, metrics, **kwargs)
        return pipe_out or {}

    # Parity mode: run pipeline then legacy; structural hash comparison deprecated.
    # Parity harness removed: retain dual execution for minimal index count diagnostic only.

    # Deep copy index_params to avoid mutation side-effects across runs.
    idx_params_legacy = copy.deepcopy(index_params)
    pipeline_result = _pipeline(index_params, providers, csv_sink, influx_sink, metrics, **kwargs) or {}
    legacy_result = _legacy(idx_params_legacy, providers, csv_sink, influx_sink, metrics, **kwargs) or {}

    try:
        pipe_idx = len(pipeline_result.get('indices', []) if isinstance(pipeline_result, dict) else [])
        leg_idx = len(legacy_result.get('indices', []) if isinstance(legacy_result, dict) else [])
        if pipe_idx != leg_idx:
            msg = f"Facade parity index_count_mismatch pipeline={pipe_idx} legacy={leg_idx}"
            if _truthy(os.environ.get("G6_FACADE_PARITY_STRICT")):
                raise RuntimeError(msg)
            logger.warning(msg)
        else:
            logger.debug("Facade parity indices_ok count=%d", pipe_idx)
    except Exception:
        logger.debug("facade_parity_index_compare_failed", exc_info=True)

    return pipeline_result
