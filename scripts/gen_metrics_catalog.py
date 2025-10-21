#!/usr/bin/env python3
"""Generate enriched metrics catalog from declarative specs.

Adds cardinality guidance, example queries, and group gating env variable mapping.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DOCS = ROOT / 'docs'
DOCS.mkdir(exist_ok=True)
OUT = DOCS / 'METRICS_CATALOG.md'

try:
    from src.metrics.spec import GROUPED_METRIC_SPECS, METRIC_SPECS  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"Failed to import specs: {e}", file=sys.stderr)
    sys.exit(1)

all_specs = list(METRIC_SPECS) + list(GROUPED_METRIC_SPECS)

GROUP_GATING_ENVS = {
    'analytics_vol_surface': ['G6_ENABLE_METRIC_GROUPS','G6_VOL_SURFACE','G6_VOL_SURFACE_PER_EXPIRY'],
    'analytics_risk_agg': ['G6_ENABLE_METRIC_GROUPS','G6_RISK_AGG'],
    'adaptive_controller': ['G6_ENABLE_METRIC_GROUPS','G6_ADAPTIVE_CONTROLLER'],
    'panel_diff': ['G6_ENABLE_METRIC_GROUPS'],
    'panels_integrity': ['G6_ENABLE_METRIC_GROUPS'],
    'greeks': ['G6_ENABLE_METRIC_GROUPS'],
    'sse_ingest': ['G6_ENABLE_METRIC_GROUPS','G6_SSE_INGEST'],
}

def cardinality_hint(label_count: int) -> str:
    if label_count == 0:
        return 'low'
    if label_count == 1:
        return 'low-moderate'
    if label_count == 2:
        return 'moderate'
    if label_count == 3:
        return 'high'
    return 'very_high'

def build_example_query(name: str, metric_type: str, labels: list[str]) -> str:
    if metric_type == 'Counter':
        return f'rate({name}[5m])'
    if metric_type == 'Gauge':
        if labels:
            return f'avg by ({labels[0]}) ({name})'
        return f'avg({name})'
    if metric_type == 'Summary':
        return f'quantile(0.9, {name}_sum / {name}_count)'
    if metric_type == 'Histogram':
        return f'rate({name}_bucket[5m])'
    return name

rows = []
for spec in all_specs:
    metric_type = getattr(spec.kind, '__name__', str(spec.kind))
    lab_list = list(spec.labels) if spec.labels else []
    group_obj = getattr(spec, 'group', None)
    group = getattr(group_obj, 'value', '') if group_obj else ''
    rows.append({
        'attr': spec.attr,
        'name': spec.name,
        'type': metric_type,
        'group': group,
        'labels': ','.join(lab_list),
        'card': cardinality_hint(len(lab_list)),
        'example': build_example_query(spec.name, metric_type, lab_list),
        'desc': spec.doc.strip(),
        'conditional': 'Y' if spec.predicate else 'N'
    })

rows.sort(key=lambda r: (r['group'] or '~', r['name']))

group_section_lines = []
for grp in sorted({r['group'] for r in rows if r['group']}):
    envs = GROUP_GATING_ENVS.get(grp, [])
    group_section_lines.append(f'- **{grp}**: {", ".join(envs) if envs else "(none)"}')

header = (
    '# G6 Metrics Catalog\n\n'
    'Auto-generated from declarative specification (`spec.py`). Do not edit manually.\n\n'
    f'Generated: {os.environ.get("G6_CATALOG_TS","(runtime)")}\n\n'
    '## Group Gating Environment Variables\n\n' + '\n'.join(group_section_lines) + '\n\n'
)

col_names = ['Attr','Prom Name','Type','Group','Labels','Cardinality','Example Query','Description','Conditional']
lines = [' | '.join(col_names), ' | '.join(['---']*len(col_names))]
for r in rows:
    desc = r['desc'].replace('|','\\|')
    example = r['example'].replace('|','\\|')
    lines.append(
        f"{r['attr']} | {r['name']} | {r['type']} | {r['group']} | {r['labels']} | {r['card']} | "
        f"{example} | {desc} | {r['conditional']}"
    )

content = header + '\n'.join(lines) + '\n'
OUT.write_text(content, encoding='utf-8')
print(f"Wrote {OUT} ({len(rows)} metrics)")
