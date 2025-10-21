#!/usr/bin/env python3
"""Consolidated benchmark report generator (B11).

Combines latest artifact snapshot, short diff vs previous, recent trends,
optional anomaly summary, and prints Markdown (default) or plain text.

Features:
 - Loads artifacts from --dir or $G6_BENCHMARK_DUMP
 - Shows latest core metrics: timestamp, options_total, duration_s
 - Diffs options_total & duration_s vs immediate predecessor
 - Includes short sparkline (same characters as bench_trend) for last N
 - Displays anomaly annotations if present, else can recompute with --compute-anomalies
 - Can emit Markdown (default) or plain terminal-friendly text (--plain)
 - Optional JSON export of structured report (--json-out path)

Exit codes: 0 ok, 2 no artifacts, 3 fatal error.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import pathlib
import statistics
import sys
from collections.abc import Sequence
from typing import Any

_SPARK_CHARS = "▁▂▃▄▅▆▇█"
_ASCII_SPARK_CHARS = "._-~=^*#"  # fallback approximate ordering

try:  # pragma: no cover
    from src.bench.anomaly import detect_anomalies as _detect_anomalies  # type: ignore
except Exception:  # pragma: no cover
    _detect_anomalies = None  # type: ignore

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

def sparkline(values):
    vals = [v for v in values if isinstance(v,(int,float)) and not math.isnan(v)]
    if not vals:
        return '-' * len(values)
    lo, hi = min(vals), max(vals)
    if hi - lo <= 1e-12:
        return _SPARK_CHARS[0] * len(values)
    span = hi - lo
    out = []
    for v in values:
        if not isinstance(v,(int,float)) or math.isnan(v):
            out.append('-'); continue
        norm = (v - lo) / span
        idx = min(len(_SPARK_CHARS)-1, max(0, int(round(norm*(len(_SPARK_CHARS)-1)))))
        out.append(_SPARK_CHARS[idx])
    return ''.join(out)

def recompute_flags(series, threshold):
    if not _detect_anomalies or len(series) < 5:
        return [False]*len(series), [0.0]*len(series)
    flags, scores = _detect_anomalies(series, threshold=threshold)
    return flags, scores

def build_report(arts: list[dict[str,Any]], limit: int, threshold: float, compute_anomalies: bool) -> dict[str,Any]:
    arts = arts[-limit:]
    latest = arts[-1]
    prev = arts[-2] if len(arts) >= 2 else None
    opts_series = [float(a.get('options_total') or 0) for a in arts]
    dur_series = [float(a.get('duration_s') or 0.0) for a in arts]
    opts_spark = sparkline(opts_series)
    dur_spark = sparkline(dur_series)
    diff_opts = None
    diff_dur = None
    if prev:
        diff_opts = opts_series[-1] - opts_series[-2]
        diff_dur = dur_series[-1] - dur_series[-2]

    # Pref existing anomaly annotations
    last_anoms = latest.get('anomalies') if isinstance(latest.get('anomalies'), dict) else {}
    annotated = bool(last_anoms)

    opt_flags = []
    dur_flags = []
    opt_scores = []
    dur_scores = []
    if annotated:
        # Build backfill from artifacts if each has anomalies; else fall back to recompute
        if all(isinstance(a.get('anomalies'), dict) for a in arts):
            for a in arts:
                o_meta = a.get('anomalies', {}).get('options_total', {})
                d_meta = a.get('anomalies', {}).get('duration_s', {})
                opt_flags.append(bool(o_meta.get('is_anomaly')))
                dur_flags.append(bool(d_meta.get('is_anomaly')))
                opt_scores.append(float(o_meta.get('score') or 0.0))
                dur_scores.append(float(d_meta.get('score') or 0.0))
        else:
            annotated = False
    if (not annotated) and compute_anomalies:
        opt_flags, opt_scores = recompute_flags(opts_series, threshold)
        dur_flags, dur_scores = recompute_flags(dur_series, threshold)

    # Stats (simple summary)
    def _stats(series):
        if not series:
            return {}
        return {
            'min': min(series),
            'max': max(series),
            'mean': statistics.fmean(series) if hasattr(statistics,'fmean') else sum(series)/len(series),
            'p50': statistics.median(series),
        }
    report = {
        'latest': {
            'timestamp': latest.get('timestamp'),
            'options_total': opts_series[-1],
            'duration_s': dur_series[-1],
            'diff_options_total': diff_opts,
            'diff_duration_s': diff_dur,
            'file': latest.get('__file'),
        },
        'series': {
            'options_total': opts_series,
            'duration_s': dur_series,
            'options_spark': opts_spark,
            'duration_spark': dur_spark,
        },
        'stats': {
            'options_total': _stats(opts_series),
            'duration_s': _stats(dur_series),
        },
        'anomalies': {
            'annotated': annotated,
            'option_flags': opt_flags,
            'duration_flags': dur_flags,
            'option_scores': opt_scores,
            'duration_scores': dur_scores,
            'threshold': threshold if (compute_anomalies or annotated) else None,
        },
        'count': len(arts),
    }
    return report

def format_markdown(report: dict[str,Any]) -> str:
    lt = report['latest']
    ser = report['series']
    stats = report['stats']
    an = report['anomalies']
    def _fmt_diff(v):
        if v is None:
            return 'n/a'
        sign = '+' if v >= 0 else ''
        return f"{sign}{v}" if isinstance(v,(int,float)) else str(v)
    md = []
    md.append(f"### Benchmark Report — {lt['timestamp']}")
    md.append('')
    md.append('| Metric | Latest | Diff | Spark | Min | Max | Mean | P50 | Anom |')
    md.append('|--------|-------:|-----:|:------|----:|----:|-----:|----:|:----:|')
    # Options row
    opt_anom = '!' if (an['option_flags'] and an['option_flags'][-1]) else '.'
    dur_anom = '!' if (an['duration_flags'] and an['duration_flags'][-1]) else '.'
    os = stats['options_total']; ds = stats['duration_s']
    md.append(f"| options_total | {lt['options_total']:.0f} | {_fmt_diff(lt['diff_options_total'])} | {ser['options_spark']} | {os.get('min',0):.0f} | {os.get('max',0):.0f} | {os.get('mean',0):.1f} | {os.get('p50',0):.0f} | {opt_anom} |")
    md.append(f"| duration_s | {lt['duration_s']:.2f} | {_fmt_diff(lt['diff_duration_s'])} | {ser['duration_spark']} | {ds.get('min',0):.2f} | {ds.get('max',0):.2f} | {ds.get('mean',0):.2f} | {ds.get('p50',0):.2f} | {dur_anom} |")
    md.append('')
    if an.get('threshold') is not None:
        md.append(f"Anomaly detection threshold: {an['threshold']} (annotated={an['annotated']})")
    md.append(f"Artifacts considered: {report['count']}")
    md.append(f"Latest artifact: `{lt['file']}`")
    return '\n'.join(md)

def format_plain(report: dict[str,Any]) -> str:
    md = format_markdown(report)
    # Strip simple markdown formatting for plain mode
    lines = []
    for line in md.splitlines():
        if line.startswith('|'):
            # Keep table raw
            lines.append(line.replace('|',' ').strip())
        else:
            lines.append(line)
    return '\n'.join(lines)

def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description='Consolidated benchmark report')
    ap.add_argument('--dir', default=None, help='Artifacts dir (defaults $G6_BENCHMARK_DUMP)')
    ap.add_argument('--limit', type=int, default=60, help='Max recent artifacts (default 60)')
    ap.add_argument('--compute-anomalies', action='store_true', help='Recompute anomalies if not annotated')
    ap.add_argument('--threshold', type=float, default=3.5, help='Robust z-score threshold (MAD)')
    ap.add_argument('--plain', action='store_true', help='Plain text output instead of Markdown')
    ap.add_argument('--json-out', help='Optional path to write structured JSON report')
    args = ap.parse_args(argv)
    root_dir = args.dir or os.environ.get('G6_BENCHMARK_DUMP')  # type: ignore[name-defined]
    if not root_dir:
        print('ERROR: directory not specified and G6_BENCHMARK_DUMP unset', file=sys.stderr)
        return 3
    root = pathlib.Path(root_dir)
    if not root.exists():
        print(f'ERROR: directory not found: {root}', file=sys.stderr)
        return 3
    arts = load_artifacts(root)
    if not arts:
        print('No artifacts found', file=sys.stderr)
        return 2
    report = build_report(arts, args.limit, args.threshold, args.compute_anomalies)
    if args.json_out:
        try:
            with open(args.json_out,'w',encoding='utf-8') as f:
                json.dump(report,f,indent=2)
        except Exception as e:
            print(f'WARN: failed writing json report: {e}', file=sys.stderr)
    out = format_plain(report) if args.plain else format_markdown(report)
    # Write directly to original stdout to avoid any print suppression wrappers
    _out = getattr(sys, '__stdout__', sys.stdout)
    try:
        _out.write(out + '\n')
    except UnicodeEncodeError:
        trans = str.maketrans({u: _ASCII_SPARK_CHARS[i] for i, u in enumerate(_SPARK_CHARS)})
        safe_out = out.translate(trans)
        _out.write(safe_out + '\n')
    return 0

if __name__ == '__main__':  # pragma: no cover
    import os
    sys.exit(main(sys.argv[1:]))
