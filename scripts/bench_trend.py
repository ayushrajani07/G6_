#!/usr/bin/env python3
"""Benchmark trend visualization (B11).

Reads recent benchmark cycle artifacts (JSON or JSON.GZ) from a directory
(G6_BENCHMARK_DUMP or --dir) and prints a compact trend table including:
 - Timestamp (latest N)
 - options_total with sparkline
 - duration_s with sparkline
 - Anomaly flags (if anomalies field present in artifact)

Optionally recomputes anomalies on the fly with --compute-anomalies if
artifacts were produced without annotation (uses same MAD method).

Usage:
  python scripts/bench_trend.py --dir data/benchmarks --limit 40
  G6_BENCHMARK_DUMP=data/benchmarks python scripts/bench_trend.py

Exit codes:
 0 success, 2 no artifacts found, 3 other error.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pathlib
import sys
from collections.abc import Sequence
from typing import Any

# Optional local anomaly helper (robust z-score)
try:  # pragma: no cover
    from src.bench.anomaly import detect_anomalies as _detect_anomalies  # type: ignore
except Exception:  # pragma: no cover
    _detect_anomalies = None  # type: ignore
    # Attempt a late sys.path injection for portability when run via scripts/ without PYTHONPATH
    try:  # pragma: no cover
        _here = pathlib.Path(__file__).resolve()
        _src = _here.parent.parent / 'src'
        if str(_src) not in sys.path and _src.exists():
            sys.path.insert(0, str(_src))
            from bench.anomaly import detect_anomalies as _detect_anomalies  # type: ignore
    except Exception:
        pass

_SPARK_CHARS = "▁▂▃▄▅▆▇█"  # 8 levels
_ASCII_SPARK_CHARS = "._-~=^*#"  # fallback

def sparkline(values: Sequence[float]) -> str:
    vals = [v for v in values if isinstance(v,(int,float)) and not math.isnan(v)]
    if not vals:
        return '-' * len(values)
    lo = min(vals); hi = max(vals)
    if hi - lo <= 1e-12:
        return _SPARK_CHARS[0] * len(values)
    out = []
    span = hi - lo
    for v in values:
        if not isinstance(v,(int,float)) or math.isnan(v):
            out.append('-'); continue
        norm = (v - lo)/span
        idx = min(len(_SPARK_CHARS)-1, max(0, int(round(norm*(len(_SPARK_CHARS)-1)))))
        out.append(_SPARK_CHARS[idx])
    return ''.join(out)

def load_artifacts(root: pathlib.Path) -> list[dict[str,Any]]:
    files = sorted([p for p in root.glob('benchmark_cycle_*.json*') if p.is_file()])
    arts: list[dict[str,Any]] = []
    for fp in files:
        try:
            if fp.suffix == '.gz' or fp.name.endswith('.json.gz'):
                with gzip.open(fp,'rt',encoding='utf-8') as f:
                    data = json.load(f)
            else:
                with open(fp,encoding='utf-8') as f:
                    data = json.load(f)
            if isinstance(data, dict):
                data['__file'] = str(fp)
                arts.append(data)
        except Exception:
            continue
    return arts

def recompute_anomalies(seq: Sequence[float], threshold: float) -> list[bool]:
    if not _detect_anomalies or len(seq) < 5:
        return [False]*len(seq)
    flags, _scores = _detect_anomalies(seq, threshold=threshold)
    return flags

def format_table(rows: list[dict[str,Any]]) -> str:
    # Determine column widths (excluding sparkline which is fixed by limit)
    ts_w = max(15, *(len(r['ts']) for r in rows)) if rows else 15
    line_hdr = f"{'Timestamp':<{ts_w}}  Options  Dur(s)  o_spark  d_spark  oA dA"
    out = [line_hdr, '-'*len(line_hdr)]
    for r in rows:
        out.append(f"{r['ts']:<{ts_w}}  {r['opts']:>7}  {r['dur']:>6.2f}  {r['o_spark']}  {r['d_spark']}  {r['opt_flag']} {r['dur_flag']}")
    return '\n'.join(out)

def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description='Benchmark trend & anomaly visualization')
    ap.add_argument('--dir', default=None, help='Artifacts directory (defaults to $G6_BENCHMARK_DUMP)')
    ap.add_argument('--limit', type=int, default=40, help='Max artifacts to include (most recent)')
    ap.add_argument('--compute-anomalies', action='store_true', help='Recompute anomalies if not annotated')
    ap.add_argument('--threshold', type=float, default=3.5, help='Robust z-score threshold for anomaly detection')
    ap.add_argument('--no-header', action='store_true', help='Omit header lines (raw mode)')
    args = ap.parse_args(argv)

    root_dir = args.dir or os.environ.get('G6_BENCHMARK_DUMP')  # type: ignore[name-defined]
    if not root_dir:
        print('ERROR: --dir not provided and G6_BENCHMARK_DUMP unset', file=sys.stderr)
        return 3
    root = pathlib.Path(root_dir)
    if not root.exists():
        print(f'ERROR: directory not found: {root}', file=sys.stderr)
        return 3

    arts = load_artifacts(root)
    if not arts:
        print('No artifacts found', file=sys.stderr)
        return 2
    # Take most recent N
    arts = arts[-args.limit:]
    # Extract series
    opts_series = [a.get('options_total') for a in arts]
    dur_series = [a.get('duration_s') for a in arts]

    # Determine anomaly flags
    if args.compute_anomalies:
        # Force recompute ignoring any embedded annotations (explicit user intent)
        opt_flags = recompute_anomalies([float(o or 0) for o in opts_series], args.threshold)
        dur_flags = recompute_anomalies([float(d or 0) for d in dur_series], args.threshold)
        # Heuristic fallback: if no anomaly detected but final point is a large spike vs prior history, flag it
        if not any(opt_flags) and len(opts_series) >= 3:
            try:
                last = float(opts_series[-1] or 0)
                prior = [float(v or 0) for v in opts_series[:-1]]
                base_max = max(prior) if prior else 0.0
                # Consider it anomalous if last exceeds prior max by both an absolute and relative margin
                if base_max > 0 and last >= base_max * 5 and (last - base_max) >= 100:
                    opt_flags[-1] = True
                    if os.environ.get('G6_BENCH_TREND_DEBUG'):
                        print(f"DEBUG heuristic opt spike last={last} base_max={base_max} -> flag", file=sys.stderr)
            except Exception:
                pass
        if os.environ.get('G6_BENCH_TREND_DEBUG'):
            print(f"DEBUG recompute forced opts_series={opts_series} opt_flags={opt_flags}", file=sys.stderr)
            print(f"DEBUG recompute forced dur_series={dur_series} dur_flags={dur_flags}", file=sys.stderr)
    else:
        opt_flags = [False]*len(arts)
        dur_flags = [False]*len(arts)
        for i,a in enumerate(arts):
            try:
                if a.get('anomalies',{}).get('options_total',{}).get('is_anomaly'):
                    opt_flags[i] = True
                if a.get('anomalies',{}).get('duration_s',{}).get('is_anomaly'):
                    dur_flags[i] = True
            except Exception:
                pass

    # Build rows
    opts_spark = sparkline([float(o or 0) for o in opts_series])
    dur_spark = sparkline([float(d or 0) for d in dur_series])

    rows = []
    for i,a in enumerate(arts):
        ts = a.get('timestamp','?')
        rows.append({
            'ts': ts,
            'opts': int(a.get('options_total') or 0),
            'dur': float(a.get('duration_s') or 0.0),
            'o_spark': opts_spark,
            'd_spark': dur_spark,
            'opt_flag': '!' if opt_flags[i] else '.',
            'dur_flag': '!' if dur_flags[i] else '.',
        })

    table = format_table(rows)
    if args.no_header:
        # Remove header lines (first two) for raw embedding
        table = '\n'.join(table.splitlines()[2:])
    # Bypass potential print gating by writing directly to original stdout
    _out = getattr(sys, '__stdout__', sys.stdout)
    try:
        _out.write(table + '\n')
    except UnicodeEncodeError:
        trans = str.maketrans({u: _ASCII_SPARK_CHARS[i] for i,u in enumerate(_SPARK_CHARS)})
        _out.write(table.translate(trans) + '\n')
    return 0

if __name__ == '__main__':  # pragma: no cover
    import os  # deferred import to minimize global namespace pollution if module reused
    sys.exit(main(sys.argv[1:]))
