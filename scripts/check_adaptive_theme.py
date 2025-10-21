#!/usr/bin/env python
"""Quick manual verification script for /adaptive/theme endpoint.

Usage (ensure G6_CATALOG_HTTP=1 process running):
  python scripts/check_adaptive_theme.py [--host 127.0.0.1] [--port 9315]

Prints palette, active counts and recent ratios (if present).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any, cast


def fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=2.5) as r:  # nosec: simple internal fetch
        obj: Any = json.loads(r.read().decode('utf-8'))
    if isinstance(obj, dict):
        return cast(dict[str, Any], obj)
    return cast(dict[str, Any], {})

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=9315)
    args = p.parse_args()
    url = f'http://{args.host}:{args.port}/adaptive/theme'
    try:
        data = fetch(url)
    except Exception as e:
        print(f'ERROR fetching {url}: {e}', file=sys.stderr)
        return 2
    palette = data.get('palette', {})
    counts = data.get('active_counts', {})
    trend = data.get('trend', {}) or {}
    snapshots = trend.get('snapshots') or []
    last = snapshots[-1] if snapshots else {}
    print('Palette :', palette)
    print('Counts  :', counts)
    if last:
        print('Last Trend Snapshot:', {k: last.get(k) for k in ('info','warn','critical','warn_ratio','critical_ratio')})
    else:
        print('Trend   : (no snapshots)')
    smooth_env = data.get('smoothing_env', {})
    if smooth_env.get('smooth') in ('1','true','yes','on'):
        print('Smoothing: ON window=', smooth_env.get('trend_window'), 'crit>=', smooth_env.get('critical_ratio'), 'warn>=', smooth_env.get('warn_ratio'))
    else:
        print('Smoothing: OFF')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
