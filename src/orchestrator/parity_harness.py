"""Orchestrator parity harness.

Provides a light-weight utility to execute exactly one collection cycle
through both the legacy `unified_main.collection_loop` path and the new
refactored orchestrator `run_cycle` path, capturing a normalized structural
snapshot for comparison in tests.

Design goals:
  * Zero external API calls (forces mock provider via env)
  * Avoid writing large CSV volumes (still uses real sink to preserve logic)
  * Deterministic ordering: sort expiries & strikes before emitting
  * Minimal surface: only include fields required to assert functional parity

Normalization Schema (per index):
  {
    "expiries": ["2025-09-26", ...],          # sorted unique expiry codes observed
    "expiry_option_counts": { code: count },   # number of option rows persisted for that expiry in this cycle
    "total_options": <int>                    # aggregate options across expiries
  }

Public API:
  run_parity_cycle(config_provider) -> { "legacy": {...}, "new": {...} }

The caller provides a minimal config wrapper (or any object exposing
`index_params()` and `data_dir()` plus dict-like access for greeks section).

Notes:
  * The legacy path relies on invoking `run_collection_cycle` directly rather
    than the full `collection_loop` to avoid sleeping / panel rendering.
  * We temporarily patch environment variables to force deterministic behavior
    (mock provider, market open, disable adaptive scaling variability).
"""
from __future__ import annotations

import copy
import datetime as _dt
import glob
import json
import os
from typing import Any

from .context import RuntimeContext  # type: ignore
from .cycle import run_cycle  # type: ignore

# Lazy import of legacy helpers to keep module import cost low in normal runtime
try:  # pragma: no cover - import errors handled gracefully in tests
    from src.unified_main import run_collection_cycle  # type: ignore
except Exception:  # pragma: no cover
    run_collection_cycle = None  # type: ignore


def _force_mock_env():
    os.environ.setdefault('G6_USE_MOCK_PROVIDER', '1')
    os.environ.setdefault('G6_FORCE_MARKET_OPEN', '1')
    # Disable parallel & adaptive noise for deterministic output
    os.environ.setdefault('G6_PARALLEL_INDICES', '0')
    os.environ.setdefault('G6_ADAPTIVE_STRIKE_SCALING', '0')


def _collect_csv_snapshot(base_dir: str, index_keys: list[str]) -> dict[str, dict[str, Any]]:
    """Scan CSV directory for option files written during a cycle and aggregate counts.

    We expect option files under base_dir/g6_data/<INDEX>/<EXPIRY>/options_*.csv
    (pattern derived from existing sink conventions). If structure changes,
    this function can be adapted without modifying tests.
    """
    out: dict[str, dict[str, Any]] = {}
    g6_data_dir = os.path.join(base_dir, 'g6_data')
    for idx in index_keys:
        idx_dir = os.path.join(g6_data_dir, idx)
        expiry_dirs = []
        try:
            if os.path.isdir(idx_dir):
                for p in os.listdir(idx_dir):
                    full = os.path.join(idx_dir, p)
                    if os.path.isdir(full):
                        expiry_dirs.append(p)
        except Exception:
            pass
        expiry_dirs.sort()
        expiry_counts: dict[str, int] = {}
        total = 0
        for exp in expiry_dirs:
            pattern = os.path.join(idx_dir, exp, 'options_*.csv')
            rows = 0
            for fname in glob.glob(pattern):
                try:
                    with open(fname, encoding='utf-8') as f:
                        # subtract header if present
                        lines = f.read().strip().splitlines()
                        if not lines:
                            continue
                        # Heuristic: first line header if contains 'strike' & 'option_type'
                        if 'strike' in lines[0] and 'option' in lines[0].lower():
                            rows += max(0, len(lines) - 1)
                        else:
                            rows += len(lines)
                except Exception:
                    continue
            expiry_counts[exp] = rows
            total += rows
        out[idx] = {
            'expiries': expiry_dirs,
            'expiry_option_counts': expiry_counts,
            'total_options': total,
        }
    return out


def run_parity_cycle(config, use_enhanced: bool = False) -> dict[str, Any]:
    """Execute one legacy and one new-cycle collection and return normalized snapshots.

    Parameters
    ----------
    config : object
        Must expose `index_params()` returning dict and `data_dir()` returning path.
        Also used as mapping for greeks config lookups (duck-typed).
    """
    _force_mock_env()
    index_params = config.index_params() if callable(getattr(config, 'index_params', None)) else getattr(config, 'index_params', lambda: {})()
    base_dir = getattr(config, 'data_dir', lambda: '.')()
    # Deep copy index_params to avoid mutation across loops
    legacy_params = copy.deepcopy(index_params)
    new_params = copy.deepcopy(index_params)

    # Build shared sinks & providers through orchestrator bootstrap components to mirror prod semantics
    from .components import init_providers, init_storage  # type: ignore
    providers = init_providers(config)
    csv_sink, influx_sink = init_storage(config)
    metrics = getattr(config, 'metrics', None)

    # Legacy execution (single cycle) -------------------------------------------------
    if run_collection_cycle is not None:
        try:
            run_collection_cycle(config, providers, csv_sink, influx_sink, metrics, False, legacy_params)
        except Exception:
            # Intentionally swallow to still allow new path comparison (will show zero counts)
            pass

    legacy_snapshot = _collect_csv_snapshot(base_dir, list(legacy_params.keys()))

    # New cycle execution --------------------------------------------------------------
    ctx = RuntimeContext(
        config=config,
        providers=providers,
        csv_sink=csv_sink,
        influx_sink=influx_sink,
        metrics=metrics,
        index_params=new_params,
    )
    try:
        # Pass through requested enhanced mode (default False to preserve existing test behavior)
        run_cycle(ctx, use_enhanced=use_enhanced)
    except Exception:
        pass
    new_snapshot = _collect_csv_snapshot(base_dir, list(new_params.keys()))

    # Use timezone-aware UTC now to comply with repository time usage policy
    generated_at = _dt.datetime.now(_dt.UTC).isoformat()
    return {'legacy': legacy_snapshot, 'new': new_snapshot, 'generated_at': generated_at}


def write_parity_report(config, path: str) -> str:
    """Helper to run parity and write JSON report to path (used for golden regen)."""
    data = run_parity_cycle(config)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path

__all__ = ["run_parity_cycle", "write_parity_report"]
