#!/usr/bin/env python3
"""Generate metrics documentation from the MetricsRegistry.

Usage:
  python scripts/gen_metrics_docs.py > docs/metrics_generated.md

Environment Variables:
  G6_DISABLE_METRIC_GROUPS - honored during registry creation (same semantics as runtime).

This script imports the metrics registry in-process so it should be run in an
isolated environment / fresh process to avoid duplicate registration noise.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

# Ensure repository root on path when executed directly.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.metrics import MetricsRegistry, get_metrics  # facade import

EXCLUDE_PREFIXES = { 'process_', 'python_', 'promhttp_' }

# Heuristic mapping of metric object type to a short kind label.
KIND_MAP = {
    'Counter': 'counter',
    'Gauge': 'gauge',
    'Histogram': 'histogram',
    'Summary': 'summary'
}

def iter_metric_objects(reg: MetricsRegistry) -> Iterable[tuple[str, Any]]:
    for attr, value in reg.__dict__.items():
        # Skip internal helpers or private attrs
        if attr.startswith('_'):
            continue
        # Only consider objects with a '_name' attribute (prometheus_client metric families)
        name = getattr(value, '_name', None)
        if not name:
            continue
        if any(name.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        yield attr, value


def format_labels(mobj: object) -> list[str]:
    # prometheus_client stores label names on ._labelnames (tuple)
    labs = getattr(mobj, '_labelnames', ()) or ()
    # Ensure it's a list and filter out internal 'quantile' for Summaries (not a label)
    return [l for l in list(labs) if l not in ('quantile',)]


def discover_groups(reg: MetricsRegistry) -> dict[str, str]:
    """Return mapping attr->group.

    Preference order:
    1. Explicit registry._metric_groups mapping (populated by tagging helper).
    2. Name-based heuristic fallback (legacy inference for older groups).
    """
    groups: dict[str, str] = {}
    explicit = getattr(reg, '_metric_groups', None)
    if isinstance(explicit, dict):
        # Copy explicit groups (already attr names)
        groups.update(explicit)
    # Heuristic fill for any attr missing a group (backward compatibility)
    for attr, mobj in iter_metric_objects(reg):
        if attr in groups:
            continue
        name = getattr(mobj, '_name', '')
        if name.startswith('g6_vol_surface_'):
            groups[attr] = 'analytics_vol_surface'
        elif name.startswith('g6_risk_agg_'):
            groups[attr] = 'analytics_risk_agg'
    return groups


def main() -> None:
    reg = get_metrics()
    if reg is None:
        print('No MetricsRegistry instance available')
        return
    groups_map = discover_groups(reg)
    rows: list[dict[str, Any]] = []
    for attr, mobj in sorted(iter_metric_objects(reg), key=lambda x: getattr(x[1], '_name', '')):
        name = mobj._name  # type: ignore[attr-defined]
        help_text = getattr(mobj, '_documentation', '') or ''
        mtype = KIND_MAP.get(mobj.__class__.__name__, mobj.__class__.__name__)
        labels = format_labels(mobj)
        group = groups_map.get(attr) or ''
        rows.append({
            'name': name,
            'type': mtype,
            'attr': attr,
            'help': help_text,
            'labels': labels,
            'group': group,
        })

    # Emit markdown
    print('# G6 Metrics (Auto-Generated)\n')
    # Use timezone-aware UTC timestamp (avoid deprecated utcnow usage).
    print(f'Generated: {datetime.now(UTC).isoformat()}')
    print('\nEnvironment Based Controls:')
    print('- G6_DISABLE_METRIC_GROUPS: Comma separated list of groups to skip during registration (e.g. "analytics_vol_surface,analytics_risk_agg").')
    print('- G6_ENABLE_METRIC_GROUPS: Optional allow-list restricting registration only to listed groups. If set, groups not in the list are skipped. Precedence: disable wins when both lists mention the same group.')
    print('\nGroups Present In This Build:')
    present_groups = sorted({r['group'] for r in rows if r['group']})
    for g in present_groups:
        print(f'- {g}')
    print('\n## Metrics\n')
    for r in rows:
        label_part = ', '.join(r['labels']) if r['labels'] else 'none'
        group_part = r['group'] or '-'
        print(f"### {r['name']}\n")
        print(f'* Type: {r['type']}')
        print(f'* Attribute: {r['attr']}')
        print(f'* Group: {group_part}')
        print(f'* Labels: {label_part}')
        if r['help']:
            print(f'* Help: {r['help']}')
        print('')

if __name__ == '__main__':
    main()
