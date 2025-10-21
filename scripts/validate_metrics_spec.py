#!/usr/bin/env python
"""Validate metrics YAML spec for required structure & basic invariants.

Checks:
- Top-level 'families' exists.
- Each family has 'metrics' list.
- Each metric has: name, type, help, cardinality_budget.
- Labels list present (can be empty) for non-histogram types; histogram bucket list required if type==histogram.
- Panel hints (panels) optional; warn if missing (except gauges allowed to skip) unless explicitly marked no_panel.
- name prefix 'g6_' enforced.
- Duplicate metric names rejected.
- Cardinality budgets are positive integers.
- No unknown top-level keys in a metric (soft warn).

Exit codes:
 0 success
 2 validation error(s) found

Usage:
  python scripts/validate_metrics_spec.py [path/to/base.yml]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore

RE_METRIC = re.compile(r'^g6_[a-z0-9_]+$')
RE_PANEL_KIND = re.compile(r'^[a-z0-9_]+$')
RE_ALERT_NAME = re.compile(r'^[A-Z][A-Za-z0-9]+$')

REQUIRED_KEYS = {"name","type","help","cardinality_budget"}
ALLOWED_KEYS = REQUIRED_KEYS | {"labels","buckets","panels","alerts","unit","note","no_panel"}

SEVERITY_ORDER = ["info","warning","critical","error"]

def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)

def warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)

def load_spec(path: Path) -> dict[str, Any]:
    try:
        data: Any = yaml.safe_load(path.read_text())
        return cast(dict[str, Any], data)
    except Exception as e:
        fail(f"Failed to load spec YAML: {e}")
        sys.exit(2)

def validate_metric(m: dict, seen: set[str], family: str, errors: list[str]) -> None:
    missing = REQUIRED_KEYS - m.keys()
    if missing:
        errors.append(f"{family}:{m.get('name','<unknown>')} missing keys {missing}")
    name = m.get('name')
    if name:
        if not RE_METRIC.match(name):
            errors.append(f"{name} invalid metric name (must start g6_ lowercase snake)")
        if name in seen:
            errors.append(f"Duplicate metric name: {name}")
        else:
            seen.add(name)
    cbud = m.get('cardinality_budget')
    if cbud is None or not isinstance(cbud,(int,)) or cbud <= 0:
        errors.append(f"{name} invalid cardinality_budget {cbud}")
    mtype = m.get('type')
    if mtype == 'histogram':
        if 'buckets' not in m or not isinstance(m['buckets'], list) or not m['buckets']:
            errors.append(f"{name} histogram missing buckets list")
    # labels
    labels = m.get('labels')
    if labels is None:
        errors.append(f"{name} missing labels list (can be empty list)")
    elif not isinstance(labels, list):
        errors.append(f"{name} labels must be list")
    # panels
    if not m.get('no_panel'):
        if 'panels' not in m:
            # allow gauge without panels but warn
            if mtype != 'gauge':
                warn(f"{name} has no panels (consider adding at least one hint)")
        else:
            if not isinstance(m['panels'], list):
                errors.append(f"{name} panels must be list")
            else:
                for p in m['panels']:
                    if not isinstance(p, dict):
                        errors.append(f"{name} panel entry not dict: {p}")
                        continue
                    k = p.get('kind')
                    if not k or not RE_PANEL_KIND.match(k):
                        errors.append(f"{name} panel kind invalid: {k}")
                    # promql presence
                    if 'promql' not in p:
                        errors.append(f"{name} panel kind {k} missing promql")
    # alerts
    for a in m.get('alerts',[]) or []:
        if not isinstance(a, dict):
            errors.append(f"{name} alert entry not dict: {a}")
            continue
        nm = a.get('alert')
        if not nm or not RE_ALERT_NAME.match(nm):
            errors.append(f"{name} alert has invalid name {nm}")
        expr = a.get('expr')
        if not expr or not isinstance(expr, str):
            errors.append(f"{name} alert {nm} missing expr")
        sev = a.get('severity')
        if sev and sev not in ("info","warning","critical","error"):
            warn(f"{name} alert {nm} has non-standard severity {sev}")
    # extra keys
    for k in m.keys():
        if k not in ALLOWED_KEYS:
            warn(f"{name} unknown key {k}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?', default='metrics/spec/base.yml')
    args = ap.parse_args()
    spec_path = Path(args.path)
    data = load_spec(spec_path)
    if not isinstance(data, dict) or 'families' not in data:
        fail("Spec missing top-level 'families'")
        return 2
    fams = data['families']
    if not isinstance(fams, dict):
        fail("'families' must be mapping")
        return sys.exit(2)
    errors: list[str] = []
    seen: set[str] = set()
    for fam_name, fam in fams.items():
        if not isinstance(fam, dict):
            errors.append(f"Family {fam_name} not mapping")
            continue
        metrics = fam.get('metrics')
        if not isinstance(metrics, list):
            errors.append(f"Family {fam_name} metrics missing or not list")
            continue
        for m in metrics:
            if not isinstance(m, dict):
                errors.append(f"Family {fam_name} metric entry not dict: {m}")
                continue
            validate_metric(m, seen, fam_name, errors)
    if errors:
        for e in errors:
            fail(e)
        print(f"Validation FAILED: {len(errors)} error(s)")
        return 2
    print(f"Validation OK: {len(seen)} metrics")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
