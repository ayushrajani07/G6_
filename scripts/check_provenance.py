#!/usr/bin/env python3
"""Validate embedded provenance in generated artifacts.

Checks:
  - Grafana dashboard JSON contains g6_provenance.spec_hash matching current spec hash.
  - Generated alerts YAML contains x_g6_provenance.spec_hash matching spec hash.

Exit codes:
 0 OK
 1 Mismatch
 2 Read / parse error

Usage:
  python scripts/check_provenance.py \
      --spec metrics/spec/base.yml \
      --dashboard grafana/dashboards/g6_spec_panels_dashboard.json \
      --alerts prometheus/g6_generated_alerts.yml
"""
from __future__ import annotations

import argparse  # type: ignore[import-untyped]
import hashlib
import json
import pathlib
import sys
from typing import Any

import yaml

DEF_SPEC = 'metrics/spec/base.yml'
DEF_DASH = 'grafana/dashboards/g6_spec_panels_dashboard.json'
DEF_ALERTS = 'prometheus/g6_generated_alerts.yml'


def short_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def load_spec_hash(path: str) -> str:
    raw = pathlib.Path(path).read_bytes()
    return short_hash(raw)


def check_dashboard(path: str, expected: str) -> str | None:
    p = pathlib.Path(path)
    if not p.exists():
        return f'Dashboard missing: {path}'
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        return f'Dashboard parse error: {e}'
    got = (data.get('g6_provenance') or {}).get('spec_hash')
    if not got:
        return 'Dashboard missing provenance spec_hash'
    if got != expected:
        return f'Dashboard spec_hash mismatch expected={expected} got={got}'
    return None


def check_alerts(path: str, expected: str) -> str | None:
    p = pathlib.Path(path)
    if not p.exists():
        return f'Alerts file missing: {path}'
    try:
        data: Any = yaml.safe_load(p.read_text(encoding='utf-8'))  # type: ignore[no-redef]
    except Exception as e:
        return f'Alerts parse error: {e}'
    prov = (data or {}).get('x_g6_provenance') or {}
    got = prov.get('spec_hash')
    if not got:
        return 'Alerts missing provenance spec_hash'
    if got != expected:
        return f'Alerts spec_hash mismatch expected={expected} got={got}'
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', default=DEF_SPEC)
    ap.add_argument('--dashboard', default=DEF_DASH)
    ap.add_argument('--alerts', default=DEF_ALERTS)
    args = ap.parse_args()

    try:
        spec_hash = load_spec_hash(args.spec)
    except Exception as e:
        print(f'[prov-check] Spec load error: {e}', file=sys.stderr)
        return 2

    errors = []
    for label, fn, path in [
        ('dashboard', check_dashboard, args.dashboard),
        ('alerts', check_alerts, args.alerts),
    ]:
        err = fn(path, spec_hash)
        if err:
            print(f'[prov-check] {label}: {err}', file=sys.stderr)
            errors.append(err)
    if errors:
        return 1
    print('[prov-check] OK (provenance hashes match)')
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
