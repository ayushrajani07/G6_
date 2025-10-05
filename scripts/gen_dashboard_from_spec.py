#!/usr/bin/env python3
"""Generate a Grafana dashboard JSON from the metrics spec.

Enhancements vs initial version:
    * Supports per-metric `panels` hints list in spec entries.
        Each hint item can define:
            - title: Panel title (required for hint usage)
            - promql: Expression (required)
            - kind: Arbitrary semantic tag (ignored by generator but kept as meta)
            - panel_type: Override Grafana panel type (default: stat for gauges/counters, timeseries otherwise)
            - span: Width (1-24); default 6; height fixed 5 for compact grid
            - unit: Grafana fieldConfig unit (optional)
    * Falls back to heuristic if no hints provided.
    * Emits a clean, deterministic panel ordering: families -> metrics -> panel hints.
"""
from __future__ import annotations
import argparse, json, yaml, os, sys, re, datetime, hashlib, pathlib
from pathlib import Path
from typing import Any, List, Dict

DEFAULT_OUT = 'grafana/dashboards/g6_generated_spec_dashboard.json'


def load_spec(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _heuristic_panel(metric: dict, panel_id: int, y: int, x: int) -> dict:
    name = metric['name']
    mtype = metric['type']
    if mtype == 'counter':
        expr = f'sum(rate({name}[5m]))'
        ptype = 'stat'
    elif mtype == 'gauge':
        expr = name
        ptype = 'stat'
    elif mtype == 'histogram':
        expr = f'sum by (le) (rate({name}_bucket[5m]))'
        ptype = 'timeseries'
    else:
        expr = name
        ptype = 'stat'
    panel = {
        'id': panel_id,
        'type': ptype,
        'title': name,
        'datasource': 'Prometheus',
        'gridPos': {'h': 5, 'w': 6, 'x': x, 'y': y},
        'targets': [{'expr': expr, 'refId': 'A'}],
    }
    if mtype == 'histogram':
        panel['targets'][0]['legendFormat'] = 'le={{le}}'
    return panel


def _hint_panels(metric: dict, panel_id: int, y: int, x: int) -> List[dict]:
    hints = metric.get('panels') or []
    out: List[dict] = []
    cur_x = x
    cur_y = y
    for hint in hints:
        title = hint.get('title')
        expr = hint.get('promql')
        if not title or not expr:
            continue  # skip invalid hint
        span = int(hint.get('span', 6) or 6)
        span = max(1, min(24, span))
        ptype = hint.get('panel_type')
        if not ptype:
            # derive default from metric type similar to heuristic
            mtype = metric.get('type')
            if mtype == 'histogram' and 'histogram_quantile' not in expr:
                ptype = 'timeseries'
            else:
                ptype = 'stat'
        panel = {
            'id': panel_id,
            'type': ptype,
            'title': title,
            'datasource': 'Prometheus',
            'gridPos': {'h': 5, 'w': span, 'x': cur_x, 'y': cur_y},
            'targets': [{'expr': expr, 'refId': 'A'}],
            'options': {},
            'fieldConfig': {'defaults': {}, 'overrides': []},
            'pluginVersion': '9.0.0',  # placeholder safe default
        }
        unit = hint.get('unit')
        if unit:
            panel['fieldConfig']['defaults']['unit'] = unit
        # include raw hint meta for traceability
        panel['g6_meta'] = {'kind': hint.get('kind'), 'base_metric': metric.get('name')}
        out.append(panel)
        panel_id += 1
        cur_x += span
        if cur_x >= 24:  # wrap
            cur_x = 0
            cur_y += 5
    return out


def _spec_hash() -> str | None:
    """Compute short hash of the canonical spec file.

    We intentionally hash the raw YAML bytes (first 16 hex chars of sha256)
    to stay consistent with gen_metrics.py and gen_prometheus_alerts.py.
    This avoids divergence if the generated metrics module is stale.
    """
    spec_path = pathlib.Path('metrics/spec/base.yml')
    try:
        raw = spec_path.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:16]
    except Exception:
        return None


def generate_dashboard(spec: dict) -> dict:
    fams = spec.get('families', {}) or {}
    panels = []
    y = 0
    panel_id = 1
    for fam_name, fam in fams.items():
        metrics = fam.get('metrics') or []
        if not metrics:
            continue
        # Row header
        panels.append({'type': 'row', 'title': f'Family: {fam_name}', 'gridPos': {'h': 1, 'w': 24, 'x': 0, 'y': y}})
        y += 1
        x = 0
        for m in metrics:
            hints = m.get('panels') or []
            if hints:
                hint_panels = _hint_panels(m, panel_id, y, x)
                if hint_panels:
                    panels.extend(hint_panels)
                    # update bookkeeping
                    panel_id = hint_panels[-1]['id'] + 1
                    last = hint_panels[-1]
                    x = last['gridPos']['x'] + last['gridPos']['w']
                    y = last['gridPos']['y']
                else:
                    panels.append(_heuristic_panel(m, panel_id, y, x)); panel_id += 1; x += 6
            else:
                panels.append(_heuristic_panel(m, panel_id, y, x)); panel_id += 1; x += 6
            if x >= 24:
                x = 0
                y += 5
        y += 5
    prov = {
        'schema': 'g6.dashboard.provenance.v0',
    # Use timezone-aware UTC (utcnow deprecated)
    'generated_at_utc': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),
        # spec_hash is computed from raw YAML bytes for deterministic consistency with other generators
        'spec_hash': _spec_hash(),
        'spec_path': 'metrics/spec/base.yml',
        'generator': 'gen_dashboard_from_spec.py',
        'families': len(fams),
        'panels': len(panels),
    }
    dash = {
        'uid': 'g6specauto',
        'title': 'G6 Spec Generated Dashboard',
        'schemaVersion': 39,
        'version': 1,
        'refresh': '30s',
        'tags': ['g6','generated','spec'],
        'timezone': 'browser',
        'time': {'from': 'now-6h', 'to': 'now'},
        'panels': panels,
        'annotations': {'list': []},
        'g6_provenance': prov,
    }
    return dash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', default='metrics/spec/base.yml')
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    spec = load_spec(args.spec)
    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        print(f'[gen-dashboard] Refusing to overwrite existing {out_path} (use --force).')
        return 1
    dash = generate_dashboard(spec)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dash, f, indent=2)
    print(f'[gen-dashboard] Wrote {out_path}')
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
