#!/usr/bin/env python3
"""Generate Prometheus alert rules from metrics spec alert hints.

Reads metrics/spec/base.yml for any metric entries containing an `alerts:` list.
Each alert hint item supports keys:
  alert (str, required)   - Alert name
  expr (str, required)    - PromQL expression
  for  (str, optional)    - For duration
  severity (str, optional default=warning)
  summary (str, optional) - Annotation summary
  description (str, optional) - Annotation description (multiline OK)
  labels (dict, optional) - Extra static labels to include

Output YAML groups alerts by metric family name plus suffix `.generated`.
Does not overwrite existing curated alert files; separate output path default: prometheus/g6_generated_alerts.yml

Usage:
  python scripts/gen_prometheus_alerts.py --out prometheus/g6_generated_alerts.yml

Exit codes:
 0 success, file written
 1 spec load error
 2 no alerts found (still writes empty structure unless --strict-empty)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import pathlib
import sys
from typing import Any

import yaml

SPEC_DEFAULT = 'metrics/spec/base.yml'
DEFAULT_OUT = 'prometheus/g6_generated_alerts.yml'


def load_spec(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_groups(spec: dict) -> list[dict[str, Any]]:
    families = spec.get('families', {}) or {}
    groups: list[dict[str, Any]] = []
    for fam_name, fam in families.items():
        metrics = fam.get('metrics') or []
        fam_rules: list[dict[str, Any]] = []
        for m in metrics:
            alerts = m.get('alerts') or []
            for a in alerts:
                name = a.get('alert')
                expr = a.get('expr')
                if not name or not expr:
                    continue
                rule: dict[str, Any] = {
                    'alert': name,
                    'expr': expr.strip(),
                }
                if 'for' in a:
                    rule['for'] = a['for']
                labels = {'team': 'g6', 'severity': a.get('severity','warning')}
                extra_labels = a.get('labels') or {}
                labels.update(extra_labels)
                rule['labels'] = labels
                annotations: dict[str, Any] = {}
                if a.get('summary'): annotations['summary'] = a['summary']
                if a.get('description'): annotations['description'] = a['description']
                if annotations: rule['annotations'] = annotations
                fam_rules.append(rule)
        if fam_rules:
            groups.append({'name': f'{fam_name}.generated', 'interval': '30s', 'rules': fam_rules})
    return groups


def compute_spec_hash(spec_path: str) -> str | None:
    try:
        raw = pathlib.Path(spec_path).read_bytes()
        return hashlib.sha256(raw).hexdigest()[:16]
    except Exception:
        return None


def write_alerts(out_path: str, groups: list[dict[str, Any]], spec_path: str) -> None:
    prov = {
        'schema': 'g6.alerts.provenance.v0',
    'generated_at_utc': dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),
        'spec_path': spec_path,
        'spec_hash': compute_spec_hash(spec_path),
        'generator': 'gen_prometheus_alerts.py',
        'groups': len(groups),
        'rules': sum(len(g['rules']) for g in groups),
    }
    wrapper = {'x_g6_provenance': prov, 'groups': groups}
    with open(out_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(wrapper, f, sort_keys=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', default=SPEC_DEFAULT)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--strict-empty', action='store_true', help='Exit non-zero if no alerts found')
    args = ap.parse_args()
    try:
        spec = load_spec(args.spec)
    except Exception as e:
        print(f'[alerts-gen] Failed to load spec: {e}', file=sys.stderr)
        return 1

    groups = build_groups(spec)
    if not groups and args.strict_empty:
        print('[alerts-gen] No alerts discovered in spec (strict-empty).', file=sys.stderr)
        return 2

    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    write_alerts(args.out, groups, args.spec)
    print(f'[alerts-gen] Wrote {args.out} groups={len(groups)} rules={sum(len(g["rules"]) for g in groups)}')
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
