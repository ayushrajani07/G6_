#!/usr/bin/env python
"""Generate Grafana dashboard JSON seeds from the metrics spec.

Current scope:
- Option Chain Aggregated Metrics dashboard (if option_chain family exists)
- Governance / Cardinality dashboard (hash & guard metrics)

This intentionally keeps logic lightweight (no external deps beyond PyYAML if
available; falls back to stdlib parsing error if missing).

Future enhancements:
- Auto layout panel grid packing
- Panel kind -> visualization mapping table derived from spec
- Merge with alert/rule catalog for linking runbooks
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    print("ERROR: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / 'metrics' / 'spec' / 'base.yml'
OUT_DIR = ROOT / 'grafana' / 'dashboards'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Simple id generator
def _id_gen(start: int = 1) -> Iterator[int]:
    i = start
    while True:
        yield i
        i += 1


def build_option_chain_dashboard(spec: dict[str, Any]) -> dict[str, Any] | None:
    fam = cast(dict[str, Any], (spec.get('families') or {})).get('option_chain')
    if not fam:
        return None
    # Metrics map (reserved for future; not currently used)
    _metrics = {m['name']: m for m in (fam.get('metrics') or []) if isinstance(m, dict) and 'name' in m}
    g = _id_gen()
    panels: list[dict[str, Any]] = []
    # Stat singles
    for title, expr in [
        ("Total Open Interest", "sum(g6_option_open_interest)"),
        ("Total 24h Volume", "sum(g6_option_volume_24h)"),
        ("Active Contracts", "sum(g6_option_contracts_active)")]:
        panels.append({
            "type": "stat", "title": title, "id": next(g),
            "gridPos": {"h":3,"w":4,"x": (len(panels)%3)*4, "y": 0},
            "targets": [{"expr": expr}]
        })
    base_y = 3
    # Helper to pack rows of two wide timeseries/heatmap
    def add(expr: str, title: str, _kind: str, row: int, col: int, heat: bool = False) -> None:
        panels.append({
            "type": "heatmap" if heat else "timeseries",
            "title": title,
            "id": next(g),
            "gridPos": {"h":8, "w":12, "x": 12*col, "y": base_y + 8*row},
            "targets": [{"expr": expr}]
        })
    add("sum by (mny) (g6_option_open_interest)", "OI by Moneyness", 'oi_mny', 0, 0)
    add("sum by (dte) (g6_option_open_interest)", "OI by DTE", 'oi_dte', 0, 1)
    add("sum by (mny,dte) (g6_option_open_interest)", "OI Heatmap (Mny x DTE)", 'oi_heatmap', 1, 0, heat=True)
    add("sum by (mny,dte) (g6_option_volume_24h)", "24h Volume Heatmap", 'vol_heatmap', 1, 1, heat=True)
    add("sum by (mny) (g6_option_volume_24h)", "Volume by Moneyness", 'vol_mny', 2, 0)
    add("sum by (dte) (g6_option_volume_24h)", "Volume by DTE", 'vol_dte', 2, 1)
    add("sum by (mny) (g6_option_iv_mean) / count by (mny) (g6_option_iv_mean)", "Mean IV by Moneyness", 'iv_mny', 3, 0)
    add("sum by (dte) (g6_option_iv_mean) / count by (dte) (g6_option_iv_mean)", "Mean IV by DTE", 'iv_dte', 3, 1)
    add(
        "sum by (mny,dte) (g6_option_iv_mean) / clamp_min(sum by (mny,dte) (count_values(\"v\", g6_option_iv_mean)),1)",
        "Mean IV Heatmap",
        'iv_heatmap',
        4,
        0,
        heat=True,
    )
    add(
        "sum by (mny) (g6_option_spread_bps_mean) / count by (mny) (g6_option_spread_bps_mean)",
        "Mean Spread bps by Mny",
        'spread_mny',
        4,
        1,
    )
    add(
        "sum by (dte) (g6_option_spread_bps_mean) / count by (dte) (g6_option_spread_bps_mean)",
        "Mean Spread bps by DTE",
        'spread_dte',
        5,
        0,
    )
    add(
        (
            "sum by (mny,dte) (g6_option_spread_bps_mean) / clamp_min("
            "sum by (mny,dte) (count_values(\"v\", g6_option_spread_bps_mean)),1)"
        ),
        "Spread bps Heatmap",
        'spread_heatmap',
        5,
        1,
        heat=True,
    )
    add("sum(rate(g6_option_contracts_new_total[5m]))", "New Listings Rate (5m)", 'new_contracts_rate', 6, 0)
    add(
        "sum by (dte) (rate(g6_option_contracts_new_total[5m]))",
        "New Listings Rate by DTE (5m)",
        'new_contracts_dte_rate',
        6,
        1,
    )
    dash: dict[str, Any] = {
        "uid": "g6-opt-chain-agg",
        "title": "G6 Option Chain Aggregated",
        "description": "Aggregated option chain bucket metrics (moneyness x DTE).",
        "tags": ["g6","option_chain"],
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "panels": panels
    }
    return dash


def build_governance_dashboard(spec: dict[str, Any]) -> dict[str, Any]:
    """Dashboard for governance, hash, duplicate, cardinality guard, emission failures."""
    # metrics_interest reserved for future enrichment (kept for reference)
    g = _id_gen()
    panels: list[dict[str, Any]] = []
    y = 0
    # Small stats row
    for m in ['g6_cardinality_guard_offenders_total', 'g6_metric_duplicates_total', 'g6_emission_failure_once_total']:
        panels.append({
            "type": "stat", "title": m, "id": next(g),
            "gridPos": {"h":3,"w":4,"x": (len(panels)%12), "y": 0},
            "targets": [{"expr": m}]
        })
    y = 3
    panels.append({
        "type": "table", "title": "Spec Hash", "id": next(g),
        "gridPos": {"h":4,"w":6,"x":0,"y":y},
        "targets": [{"expr": "label_replace(g6_metrics_spec_hash_info, \"hash\", \"$1\", \"hash\", \"(.*)\")"}]
    })
    panels.append({
        "type": "table", "title": "Build/Config Hash", "id": next(g),
        "gridPos": {"h":4,"w":6,"x":6,"y":y},
        "targets": [{"expr": "label_replace(g6_build_config_hash_info, \"hash\", \"$1\", \"hash\", \"(.*)\")"}]
    })
    y += 4
    panels.append({
        "type": "timeseries", "title": "Cardinality Growth % (Top 10)", "id": next(g),
        "gridPos": {"h":8,"w":12,"x":0,"y":y},
        "targets": [{"expr": "topk(10, g6_cardinality_guard_growth_percent)"}]
    })
    panels.append({
        "type": "timeseries", "title": "Emission Failures Rate (10m)", "id": next(g),
        "gridPos": {"h":8,"w":12,"x":12,"y":y},
        "targets": [{"expr": "sum(rate(g6_emission_failures_total[10m]))"}]
    })
    y += 8
    panels.append({
        "type": "timeseries", "title": "Duplicate Registrations (5m)", "id": next(g),
        "gridPos": {"h":8,"w":12,"x":0,"y":y},
        "targets": [{"expr": "sum(rate(g6_metric_duplicates_total[5m]))"}]
    })
    dash: dict[str, Any] = {
        "uid": "g6-governance",
        "title": "G6 Metrics Governance",
        "description": (
            "Governance & observability health: spec/build hashes, duplicates, "
            "cardinality growth, emission failures."
        ),
        "tags": ["g6","governance"],
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-24h", "to": "now"},
        "panels": panels
    }
    return dash


def main() -> None:
    raw = yaml.safe_load(SPEC.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        print("ERROR: spec is not a mapping", file=sys.stderr)
        sys.exit(2)
    data = cast(dict[str, Any], raw)
    wrote: list[str] = []
    opt = build_option_chain_dashboard(data)
    if opt:
        path = OUT_DIR / 'g6_option_chain_agg.json'
        path.write_text(json.dumps(opt, indent=2), encoding='utf-8')
        wrote.append(path.name)
    gov = build_governance_dashboard(data)
    gp = OUT_DIR / 'g6_metrics_governance.json'
    gp.write_text(json.dumps(gov, indent=2), encoding='utf-8')
    wrote.append(gp.name)
    print("Generated dashboards:", ", ".join(wrote))

if __name__ == '__main__':
    main()
