#!/usr/bin/env python
"""Generate RULES_CATALOG.md summarizing Prometheus recording & alert rules.

Parses prometheus_rules.yml and prometheus_alerts.yml (top-level keys assumed Prometheus format).
Computes a stable content hash per rule expression for drift detection.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
RULE_FILES = [ROOT / 'prometheus_rules.yml', ROOT / 'prometheus_alerts.yml']
OUT = ROOT / 'docs' / 'RULES_CATALOG.md'

# No module-level state needed


def rule_hash(expr: str) -> str:
    return hashlib.sha256(expr.encode('utf-8')).hexdigest()[:12]


def load_groups() -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for f in RULE_FILES:
        if not f.exists():
            continue
        data: dict[str, Any] = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
        groups.extend({
            'source': f.name,
            'name': g.get('name'),
            'interval': g.get('interval'),
            'rules': g.get('rules', []),
        } for g in data.get('groups', []))
    return groups


def main() -> None:
    groups = load_groups()
    ts = dt.datetime.now(dt.UTC).isoformat(timespec='seconds').replace('+00:00','Z')
    lines = ["# Prometheus Rules & Alerts Catalog", f"Generated: {ts}", ""]
    for g in groups:
        lines.append(f"## Group: {g['name']} ({g['source']})")
        if g.get('interval'):
            lines.append(f"Interval: `{g['interval']}`\n")
        for r in g['rules']:
            record = r.get('record')
            alert = r.get('alert')
            expr = (r.get('expr') or '').strip()
            rh = rule_hash(expr) if expr else 'NA'
            if record:
                lines.append(f"### Recording: {record}")
            elif alert:
                lines.append(f"### Alert: {alert}")
            else:
                lines.append("### Rule (untyped)")
            lines.append("````promql")
            lines.append(expr)
            lines.append("````")
            if alert:
                sev = r.get('labels', {}).get('severity', 'n/a')
                lines.append(f"Severity: `{sev}`  ")
            if r.get('for'):
                lines.append(f"For: `{r['for']}`  ")
            lines.append(f"Hash: `{rh}`\n")
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Wrote {OUT}")

if __name__ == '__main__':
    main()
