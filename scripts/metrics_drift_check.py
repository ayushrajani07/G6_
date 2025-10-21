#!/usr/bin/env python3
"""Metrics Drift Check

Compares the authoritative spec (metrics/spec/base.yml) with currently exported
Prometheus metric family names from a live /metrics endpoint to detect:
- Spec metrics missing in runtime output
- Extra runtime metrics not declared in spec

Exit codes:
 0 - No drift
 1 - Drift detected (differences printed)
 2 - Runtime fetch error or parsing failure

Usage:
  python scripts/metrics_drift_check.py --endpoint http://localhost:9108/metrics

Environment overrides:
  G6_METRICS_ENDPOINT  - endpoint URL (if --endpoint omitted)
  G6_METRICS_STRICT    - if set truthy, treat ANY extra runtime metrics as failure

Notes:
  - Ignores standard prometheus_client internal metrics by default unless --include-internals used.
  - Spec parsing is shallow (only names); regenerate code first for consistency.
"""
from __future__ import annotations

import argparse  # type: ignore[import-untyped]
import hashlib
import os
import re
import sys
import urllib.error
import urllib.request
from re import Match
from typing import Any

import yaml

INTERNAL_PREFIXES = (
    'python_gc_', 'process_', 'python_info', 'promhttp_', 'node_', '__', 'platform_',
)

METRIC_NAME_RE = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)({.*})?\s')


def load_spec(path: str) -> dict[str, Any]:
    with open(path, encoding='utf-8') as f:
        spec: Any = yaml.safe_load(f)
    return spec if isinstance(spec, dict) else {}


def load_spec_names(path: str) -> set[str]:
    with open(path, encoding='utf-8') as f:
        spec = yaml.safe_load(f)
    families = spec.get('families', {}) if isinstance(spec, dict) else {}
    names: set[str] = set()
    for fam in families.values():
        if not isinstance(fam, dict):
            continue
        for m in fam.get('metrics', []) or []:
            if isinstance(m, dict) and 'name' in m:
                names.add(m['name'])
    return names


def fetch_metrics(endpoint: str) -> str:
    req = urllib.request.Request(endpoint, headers={'Accept': 'text/plain'})
    with urllib.request.urlopen(req, timeout=5) as resp:  # nosec - internal trusted
        body_bytes = resp.read()
    body_text: str = body_bytes.decode('utf-8', 'replace')
    return body_text


def parse_metric_names(text: str, include_internals: bool) -> set[str]:
    out: set[str] = set()
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        m = METRIC_NAME_RE.match(line)
        if not m:
            continue
        name = m.group('name')
        # Skip samples with _created suffix etc. treat base family only
        if name.endswith('_created') or name.endswith('_total') and name[:-6] + '_total' != name:
            pass
        if not include_internals and name.startswith(INTERNAL_PREFIXES):
            continue
        out.add(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--endpoint', help='Metrics endpoint URL (default env G6_METRICS_ENDPOINT or http://localhost:9108/metrics)')
    ap.add_argument('--spec', default='metrics/spec/base.yml')
    ap.add_argument('--include-internals', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--check-hash', action='store_true', help='Also validate g6_metrics_spec_hash_info hash label matches local spec hash')
    args = ap.parse_args()

    endpoint = args.endpoint or os.getenv('G6_METRICS_ENDPOINT', 'http://localhost:9108/metrics')

    try:
        spec_obj = load_spec(args.spec)
        spec_names = load_spec_names(args.spec)
    except Exception as e:
        print(f'[drift] Failed to load spec: {e}', file=sys.stderr)
        return 2

    try:
        raw = fetch_metrics(endpoint)
    except Exception as e:
        print(f'[drift] Fetch error endpoint={endpoint} err={e}', file=sys.stderr)
        return 2

    runtime_names = parse_metric_names(raw, args.include_internals)

    missing = sorted(spec_names - runtime_names)
    extra = sorted(runtime_names - spec_names)

    strict = os.getenv('G6_METRICS_STRICT', '').lower() in ('1','true','yes','on')

    if args.verbose:
        print(f'Spec metrics: {len(spec_names)} Runtime metrics: {len(runtime_names)}')
    if missing:
        print('[drift] Missing metrics (in spec, not in runtime):')
        for name in missing:
            print('  -', name)
    if extra and strict:
        print('[drift] Extra runtime metrics (not declared in spec):')
        for name in extra:
            print('  +', name)

    hash_mismatch = False
    if args.check_hash:
        # Compute local hash (mirror generator: first 16 hex chars of sha256 raw file bytes)
        try:
            raw_local = open(args.spec, 'rb').read()
            local_hash = hashlib.sha256(raw_local).hexdigest()[:16]
            # Extract runtime hash label from metric sample line like: g6_metrics_spec_hash_info{hash="abcd"} 1
            runtime_hash: str | None = None
            for line in raw.splitlines():
                if line.startswith('g6_metrics_spec_hash_info{'):
                    m: Match[str] | None = re.search(r'hash="([0-9a-f]+)"', line)
                    if m is not None:
                        runtime_hash = m.group(1)
                        break
            if runtime_hash is None:
                print('[drift] Spec hash metric not found in runtime export', file=sys.stderr)
                hash_mismatch = True
            elif runtime_hash != local_hash:
                print(f'[drift] Spec hash mismatch local={local_hash} runtime={runtime_hash}', file=sys.stderr)
                hash_mismatch = True
            elif args.verbose:
                print(f'[drift] Spec hash match {local_hash}')
        except Exception as e:
            print(f'[drift] Hash check error: {e}', file=sys.stderr)
            hash_mismatch = True

    if missing or (strict and extra) or hash_mismatch:
        return 1
    print('[drift] OK (no drift)')
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
