"""CI Gate: Parity & Fatal Guard (W4-20)

Evaluates rolling parity gauge and recent fatal ratio recording rule output to enforce
minimum quality thresholds in CI before promotion / merge.

Default Metric Names:
- Rolling parity gauge: g6_pipeline_parity_rolling_avg
- Fatal ratio recording rule (15m window): g6:pipeline_fatal_ratio_15m

Exit Codes:
 0 -> PASS (all thresholds satisfied)
 1 -> Failure (parity or fatal ratio breach, or evaluation error when strict)
 2 -> Soft warning (metrics missing but --allow-missing set)

Usage Examples:
  python scripts/ci_gate.py --metrics-url http://127.0.0.1:9108/metrics \
      --min-parity 0.985 --max-fatal-ratio 0.05

  python scripts/ci_gate.py --metrics-file metrics_snapshot.txt --json

Flags:
  --min-parity FLOAT          Minimum allowed rolling parity average (default 0.985)
  --max-fatal-ratio FLOAT     Maximum allowed fatal ratio (default 0.05)
  --metrics-url URL           Prometheus metrics endpoint (mutually exclusive with --metrics-file)
  --metrics-file PATH         Local metrics text file (for tests / offline evaluation)
  --allow-missing             Do not fail build if metrics missing; exit 2 instead
  --json                      Print JSON report to stdout
  --parity-metric NAME        Override parity metric name
  --fatal-metric NAME         Override fatal ratio metric name
  --strict                    Treat any fetch/parse error as hard failure (default behavior)

The script performs a single scrape, parses lines for exact metric names (no labels required),
and compares latest observed scalar values against thresholds.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
from typing import Any, cast


def _read_metrics_text(url: str | None, path: str | None) -> str:
    if url:
        with urllib.request.urlopen(url, timeout=2.5) as resp:  # pragma: no cover (network path)
            data = resp.read()
            return cast(bytes, data).decode('utf-8', errors='replace')
    if path:
        return pathlib.Path(path).read_text(encoding='utf-8')
    raise ValueError("Either url or path must be provided")


def _parse_value(metrics_text: str, metric_name: str) -> float | None:
    # Simple line-based extraction; ignore HELP/TYPE lines; first match wins
    for line in metrics_text.splitlines():
        if not line:
            continue
        # tolerate leading whitespace
        line = line.lstrip()
        if line.startswith('#'):
            continue
        if not line.startswith(metric_name):
            continue
        # Accept patterns: name <value> OR name{labels} <value>
        try:
            parts = line.split()
            if len(parts) < 2:
                continue
            raw_val = parts[-1]
            return float(raw_val)
        except Exception:
            continue
    return None


def evaluate(parity: float | None, fatal_ratio: float | None, *, min_parity: float, max_fatal: float) -> dict[str, Any]:
    status = 'pass'
    reasons = []
    if parity is None:
        reasons.append('parity_metric_missing')
    elif parity < min_parity:
        status = 'fail'
        reasons.append(f'parity_below_threshold({parity} < {min_parity})')
    if fatal_ratio is None:
        reasons.append('fatal_ratio_metric_missing')
    elif fatal_ratio > max_fatal:
        status = 'fail'
        reasons.append(f'fatal_ratio_above_threshold({fatal_ratio} > {max_fatal})')
    return {
        'status': status,
        'parity': parity,
        'fatal_ratio': fatal_ratio,
        'min_parity': min_parity,
        'max_fatal_ratio': max_fatal,
        'reasons': reasons,
    }


from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover (CLI wrapper)
    ap = argparse.ArgumentParser()
    ap.add_argument('--metrics-url')
    ap.add_argument('--metrics-file')
    ap.add_argument('--min-parity', type=float, default=0.985)
    ap.add_argument('--max-fatal-ratio', type=float, default=0.05)
    ap.add_argument('--parity-metric', default='g6_pipeline_parity_rolling_avg')
    ap.add_argument('--fatal-metric', default='g6:pipeline_fatal_ratio_15m')
    ap.add_argument('--allow-missing', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true')
    args = ap.parse_args(argv)
    if bool(args.metrics_url) == bool(args.metrics_file):
        print('Provide exactly one of --metrics-url or --metrics-file', file=sys.stderr)
        return 1
    try:
        text = _read_metrics_text(args.metrics_url, args.metrics_file)
    except Exception as e:
        if args.strict or not args.allow_missing:
            print(f'ERROR: failed to read metrics: {e}', file=sys.stderr)
            return 1
        report = {'status': 'missing', 'error': str(e), 'reasons': ['fetch_error']}
        if args.json:
            print(json.dumps(report, indent=2))
        return 2
    parity_val = _parse_value(text, args.parity_metric)
    fatal_val = _parse_value(text, args.fatal_metric)
    report = evaluate(parity_val, fatal_val, min_parity=args.min_parity, max_fatal=args.max_fatal_ratio)
    # Handle missing metrics under allow-missing
    if report['status'] == 'pass' and ('parity_metric_missing' in report['reasons'] or 'fatal_ratio_metric_missing' in report['reasons']):
        if args.allow_missing:
            report['status'] = 'soft-missing'
        else:
            report['status'] = 'fail'
    if args.json:
        print(json.dumps(report, indent=2))
    if report['status'] == 'pass':
        return 0
    if report['status'] == 'soft-missing':
        return 2
    return 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
