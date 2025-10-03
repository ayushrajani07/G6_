"""Memory Pressure Evaluation (initial stub)

Derives a simple memory tier (0 good, 1 warning, 2 critical) using RSS against
configured thresholds if available. Falls back to environment variable
`G6_MEMORY_TIER` when explicit override is provided.

Threshold Sources:
 - Env overrides: G6_MEMORY_LEVEL1_MB, G6_MEMORY_LEVEL2_MB (critical defaults to level2 * 1.2 if LEVEL3 unset)
 - Optional explicit G6_MEMORY_LEVEL3_MB

Implementation presently uses `psutil` if installed; otherwise no-op unless
explicit tier override exists. Designed to be soft (never raises) and minimal
overhead (single RSS fetch per cycle when enabled).
"""
from __future__ import annotations

import os
from typing import Optional

try:  # psutil optional
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore


def evaluate_memory_tier(ctx) -> None:
    # Explicit override tier (simulate) takes precedence
    override = os.environ.get('G6_MEMORY_TIER_OVERRIDE') or os.environ.get('G6_MEMORY_TIER')
    if override is not None:
        try:
            ctx.set_flag('memory_tier', int(override))
        except Exception:
            pass
        return
    # If psutil missing, skip auto evaluation
    if psutil is None:
        return
    try:
        proc = psutil.Process()
        rss_bytes = proc.memory_info().rss
        rss_mb = rss_bytes / (1024 * 1024)
        lvl1 = float(os.environ.get('G6_MEMORY_LEVEL1_MB', '200'))
        lvl2 = float(os.environ.get('G6_MEMORY_LEVEL2_MB', '300'))
        lvl3 = float(os.environ.get('G6_MEMORY_LEVEL3_MB', str(int(lvl2 * 1.2))))
        tier = 0
        if rss_mb >= lvl3:
            tier = 2
        elif rss_mb >= lvl1 or rss_mb >= lvl2:  # if between lvl1 and lvl3 treat as warning
            tier = 1
        ctx.set_flag('memory_tier', tier)
    except Exception:  # pragma: no cover
        # Silent failure acceptable; adaptive controller will fallback to default tier 0
        return

__all__ = ["evaluate_memory_tier"]
