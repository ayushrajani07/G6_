#!/usr/bin/env python3
"""Exercise / Warm Metrics

Purpose:
  - Import and generate all metric families declared in the spec so that dashboards
    do not show empty / N/A panels immediately after startup.
  - (Optional) Perform a strict drift check immediately after warm-up to catch
    spec/runtime mismatches in CI before merging.

Behavior:
  1. Starts the metrics server (if not already started) on the given host/port.
  2. Loads the metrics spec YAML.
  3. For each metric definition, touches / initializes the metric via the auto-generated
     accessors module so that a zero sample is present (histograms create zero buckets,
     gauges set no value until first set so we explicitly set 0, counters remain 0).
  4. For metrics with labels we create a synthetic "_warm" label value for each label key
     unless an allowlist of seed values is provided in the spec in future (not yet implemented).
  5. Optionally runs the drift check script either in info or strict (fail) mode.

Exit codes:
  0 success (or drift ok)
  1 drift detected (strict)
  2 spec load failure
  3 unexpected error

Usage:
  python scripts/exercise_metrics.py --spec metrics/spec/base.yml --run-drift-check --strict-drift
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import types
from typing import Any

import yaml

SPEC_DEFAULT = 'metrics/spec/base.yml'
DRIFT_SCRIPT = 'scripts/metrics_drift_check.py'


def load_spec(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_metrics_server(host: str, port: int) -> None:
    # If already started, reuse. We call setup_metrics_server idempotently.
    from src.metrics.server import setup_metrics_server  # type: ignore
    setup_metrics_server(port=port, host=host)


def warm_metric(metric: dict[str, Any], generated_mod: types.ModuleType) -> None:
    name = metric['name']
    mtype = metric['type']
    labels: list[str] = metric.get('labels') or []
    accessor_name = f"m_{name}"
    if not hasattr(generated_mod, accessor_name):
        # Might happen if code generation not run; skip silently (drift script will catch)
        return
    accessor = getattr(generated_mod, accessor_name)

    if labels:
        # Build deterministic synthetic label dict (alphabetical) for warm sample
        label_values = {lbl: 'warm' for lbl in labels}
        inst = accessor(label_values)
        if mtype == 'gauge':
            try:
                inst.set(0)
            except Exception:
                pass
        elif mtype == 'counter':
            # Counters start at 0 automatically upon first access; we can inc by 0
            try:
                inst.inc(0)
            except Exception:
                pass
        elif mtype == 'histogram':
            try:
                inst.observe(0)
            except Exception:
                pass
    else:
        inst = accessor()
        if mtype == 'gauge':
            try:
                inst.set(0)
            except Exception:
                pass
        elif mtype == 'counter':
            try:
                inst.inc(0)
            except Exception:
                pass
        elif mtype == 'histogram':
            try:
                inst.observe(0)
            except Exception:
                pass


def warm_all(spec: dict) -> int:
    try:
        generated_mod = importlib.import_module('src.metrics.generated')
    except Exception as e:  # pragma: no cover - defensive
        print(f"[warm] Failed to import generated module: {e}", file=sys.stderr)
        return 1
    families = spec.get('families') or {}
    for fam in families.values():
        metrics = fam.get('metrics') or []
        for m in metrics:
            try:
                warm_metric(m, generated_mod)
            except Exception as e:
                # Non-fatal: continue warming others
                print(f"[warm] Error warming {m.get('name')}: {e}", file=sys.stderr)
    return 0


def run_drift(strict: bool) -> int:
    # Execute drift script in-process via runpy for simplicity (could also subprocess)
    import runpy
    env = os.environ.copy()
    if strict:
        env['G6_METRICS_STRICT'] = '1'
    # We rely on drift script's exit code semantics; capture via SystemExit
    try:
        runpy.run_path(DRIFT_SCRIPT, run_name='__main__')
    except SystemExit as e:  # exit code bubbled
        return int(e.code or 0)
    except Exception as e:  # pragma: no cover
        print(f"[warm] Drift script exception: {e}", file=sys.stderr)
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', default=SPEC_DEFAULT)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=9108)
    ap.add_argument('--sleep', type=float, default=0.5, help='Sleep after warming before drift (allow registry exposure)')
    ap.add_argument('--run-drift-check', action='store_true')
    ap.add_argument('--strict-drift', action='store_true')
    args = ap.parse_args()

    try:
        spec = load_spec(args.spec)
    except Exception as e:
        print(f"[warm] Failed to load spec: {e}", file=sys.stderr)
        return 2

    ensure_metrics_server(args.host, args.port)

    warm_all(spec)

    if args.run_drift_check or args.strict_drift:
        time.sleep(args.sleep)
        drift_code = run_drift(args.strict_drift)
        if drift_code != 0:
            print(f"[warm] Drift check failed code={drift_code}")
        return drift_code

    print('[warm] Metrics warmed (no drift check requested)')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
