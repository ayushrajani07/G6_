#!/usr/bin/env python
from __future__ import annotations

"""
Clean baseline for gen_dashboards_modular.py (recovery copy).
This file mirrors the intended minimal generator so we can diff and swap cleanly.
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "docs" / "metrics_spec.yaml"
OUTPUT_DIR = ROOT / "data" / "dashboards_modular"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


@dataclass(frozen=True)
class Metric:
    name: str
    kind: str
    labels: list[str]
    family: str
    panel_defs: list[dict[str, Any]]
    alerts: list[dict[str, Any]]


@dataclass(frozen=True)
class DashboardPlan:
    slug: str
    title: str
    families: list[str]
    description: str = ""
    tags: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:  # type: ignore[override]
        if self.tags is None:
            object.__setattr__(self, "tags", [])


DEFAULT_PLANS: list[DashboardPlan] = [
    DashboardPlan(slug="core_overview", title="Core Overview", families=["core"], tags=["core"]),
    DashboardPlan(slug="greeks_overview", title="Greeks Overview", families=["greeks"], tags=["analytics"]),
    DashboardPlan(slug="adaptive_controller", title="Adaptive Controller", families=["adaptive_controller"], tags=["adaptive"]),
    DashboardPlan(slug="bus_health", title="Bus Health", families=["panels_integrity"], tags=["ops", "health"]),
    DashboardPlan(slug="system_overview_minimal", title="System Overview (Minimal)", families=["core"], tags=["system", "minimal"]),
    DashboardPlan(slug="multi_pane_explorer", title="Multi-Pane Explorer", families=["core"], tags=["explorer"]),
    DashboardPlan(slug="multi_pane_explorer_compact", title="Multi-Pane Explorer (Compact)", families=["core"], tags=["explorer","compact"]),
    DashboardPlan(slug="multi_pane_explorer_ultra", title="Multi-Pane Explorer (Ultra)", families=["core"], tags=["explorer","ultra"]),
]


def load_spec_metrics(spec_path: Path) -> list[Metric]:
    if not spec_path.exists():
        return []
    raw = yaml.safe_load(spec_path.read_text())
    metrics: list[Metric] = []
    # Format A: current repo uses top-level list of metric dicts
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            kind = item.get("type") or item.get("kind")
            labels = item.get("labels") or []
            family = item.get("group") or item.get("family") or "misc"
            panel_defs = item.get("panels") or []
            alerts = item.get("alerts") or []
            if not name or not kind:
                continue
            metrics.append(Metric(name=str(name), kind=str(kind), labels=list(labels), family=str(family), panel_defs=list(panel_defs), alerts=list(alerts)))
        return metrics
    # Format B: legacy families mapping {family: {metrics: [...]}}
    raw = raw or {}
    fam_block = raw.get("families", {}) if isinstance(raw, dict) else {}
    for family, fdata in fam_block.items():
        entries = (fdata or {}).get("metrics", [])
        if not isinstance(entries, list):
            continue
        for m in entries:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            kind = m.get("type") or m.get("kind")
            labels = m.get("labels") or []
            panel_defs = m.get("panels") or []
            alerts = m.get("alerts") or []
            if not name or not kind:
                continue
            metrics.append(Metric(name=name, kind=str(kind), labels=list(labels), family=str(family), panel_defs=list(panel_defs), alerts=list(alerts)))
    return metrics


def spec_hash_text(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def panel_signature(panel: dict[str, Any]) -> str:
    t = panel.get("type")
    title = panel.get("title")
    raw_exprs = [tgt.get("expr") for tgt in panel.get("targets", []) if isinstance(tgt, dict)]
    exprs = sorted([e for e in raw_exprs if isinstance(e, str)])
    ds = panel.get("datasource", {}).get("type")
    unit = panel.get("fieldConfig", {}).get("defaults", {}).get("unit")
    return json.dumps({"type": t, "title": title, "exprs": exprs, "ds": ds, "unit": unit}, sort_keys=True)


def layout_panels(panels: list[dict[str, Any]]) -> None:
    x = 0
    y = 0
    for p in panels:
        w = 12
        h = 8
        p.setdefault("gridPos", {})
        p["gridPos"].update({"x": x, "y": y, "w": w, "h": h})
        if x == 0:
            x = 12
        else:
            x = 0
            y += h


def _convert_spec_panel(metric: Metric, idx: int, pdef: dict) -> dict[str, Any]:
    title = pdef.get("title") or f"{metric.name} panel {idx}"
    expr = pdef.get("promql") or metric.name
    panel_type = pdef.get("panel_type") or "timeseries"
    unit = pdef.get("unit")
    return {
        "type": panel_type,
        "title": title,
        "targets": [{"expr": expr, "refId": "A"}],
        "datasource": {"type": "prometheus", "uid": "PROM"},
        "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": []},
        "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "spec"},
    }


def _auto_extra_panels(metric: Metric) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    if metric.kind == "counter":
        expr = f"sum(rate({metric.name}[5m]))"
        title = f"{metric.name} Rate (5m auto)"
    else:
        expr = metric.name
        title = f"{metric.name} (auto)"
    extras.append({
        "type": "timeseries",
        "title": title,
        "targets": [{"expr": expr, "refId": "A"}],
        "datasource": {"type": "prometheus", "uid": "PROM"},
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
        "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "auto"},
    })
    return extras


def _load_explorer_cfg(root: Path) -> dict[str, Any]:
    cfg_path = root / "explorer_config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text()) or {}
    except Exception:
        return {}


def synth_dashboard(plan: DashboardPlan, metrics: list[Metric], spec_hash: str) -> dict[str, Any]:
    if plan.slug.startswith("multi_pane_explorer"):
        # Variant flags
        is_compact = plan.slug.endswith("_compact")
        is_ultra = plan.slug.endswith("_ultra")
        cfg = _load_explorer_cfg(ROOT)
        band_pct = int(cfg.get("band_pct", 25))
        band_factor = f"{band_pct/100:.6f}"

        # Templating
        templating_list = [
            {"type": "query", "name": "metric", "label": "Metric", "query": "label_values(up, job)", "datasource": {"type": "prometheus", "uid": "PROM"}, "multi": True},
            {"type": "query", "name": "metric_hist", "label": "Histogram Metric", "query": "label_values(up, job)", "datasource": {"type": "prometheus", "uid": "PROM"}, "multi": True},
            {"type": "custom", "name": "overlay", "label": "Overlay", "query": "off,fast,ultra", "current": {"text": "off", "value": "off"}},
            {"type": "custom", "name": "q", "label": "Quantile", "query": "p50,p90,p95,p99", "current": {"text": "p95", "value": "p95"}},
        ]

        explorer_panels: list[dict[str, Any]] = []

        # Base: Raw & 5m + overlay targets (C,D,E)
        raw_targets = [
            {"expr": "$metric", "refId": "A"},
            {"expr": "sum(rate($metric[5m]))", "refId": "B"},
            {"expr": "sum(rate($metric[30s])) and ($overlay == 'fast')", "refId": "C"},
            {"expr": "sum(rate($metric[15s])) and ($overlay == 'ultra')", "refId": "D"},
            {"expr": "avg_over_time($metric[5m])", "refId": "E"},
        ]
        explorer_panels.append({
            "type": "timeseries",
            "title": "$metric raw & 5m rate",
            "targets": raw_targets,
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "repeat": "metric",
            "repeatDirection": "h",
            "g6_meta": {"source": "explorer_template", "group": "explorer"},
        })

        # Base: rate ratio panel (1m vs 5m)
        explorer_panels.append({
            "type": "timeseries",
            "title": "$metric rate 1m vs 5m",
            "targets": [
                {"expr": "sum(rate($metric[1m]))", "refId": "A"},
                {"expr": "sum(rate($metric[5m]))", "refId": "B"},
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "repeat": "metric",
            "repeatDirection": "h",
            "g6_meta": {"source": "explorer_template", "group": "explorer"},
        })

        # Base: cumulative total (omit in compact and ultra variants)
        if not (is_compact or is_ultra):
            explorer_panels.append({
                "type": "timeseries",
                "title": "$metric cumulative total (24h)",
                "targets": [
                    {"expr": "sum_over_time($metric[24h])", "refId": "A"},
                ],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
                "repeat": "metric",
                "repeatDirection": "h",
                "g6_meta": {"source": "explorer_template", "group": "explorer"},
            })

        # Histogram summary panel (with override for delta thresholds matcher presence)
        summary_targets: list[dict[str, Any]] = [
            {"expr": "$metric_hist:$q_5m", "refId": "A"},
            {"expr": "$metric_hist:$q_30m", "refId": "B"},
            {"expr": "$metric_hist:$q_ratio_5m_30m", "refId": "C"},
            {"expr": "($metric_hist:$q_5m - $metric_hist:$q_30m) / clamp_min($metric_hist:$q_30m, 0.000001)", "refId": "D"},
        ]
        # Ultra variant folds additional signals (rate ratio, cumulative) into summary as E/F
        if is_ultra:
            summary_targets.extend([
                {"expr": "sum(rate($metric[1m])) / sum(rate($metric[5m]))", "refId": "E"},
                {"expr": "sum_over_time($metric[24h])", "refId": "F"},
            ])
        explorer_panels.append({
            "type": "timeseries",
            "title": "Histogram Summary",
            "targets": summary_targets,
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": [{"matcher": {"id": "byRegexp", "options": ".*D$"}, "properties": []}]},
            "repeat": "metric_hist",
            "repeatDirection": "h",
            "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "histogram_summary"},
        })

        # Histogram window panel (A: $q_5m, B: $q_30m, C/D include band factor constant)
        explorer_panels.append({
            "type": "timeseries",
            "title": "Histogram Window",
            "targets": [
                {"expr": "$q_5m", "refId": "A"},
                {"expr": "$q_30m", "refId": "B"},
                {"expr": f"$q_30m * (1 - {band_factor})", "refId": "C"},
                {"expr": f"$q_30m * (1 + {band_factor})", "refId": "D"},
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "repeat": "metric_hist",
            "repeatDirection": "h",
            "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "histogram_window"},
        })

        # Alerts context panel (omit in ultra; allow disable via env)
        if (not is_ultra) and os.environ.get("G6_EXPLORER_NO_ALERTS", "0") != "1":
            explorer_panels.append({
                "type": "table",
                "title": "Alerts Context",
                "targets": [{"expr": "ALERTS{alertstate='firing'}", "refId": "A"}],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
                "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "alerts_context"},
            })

        # Assign ids and uuids, then layout
        for p in explorer_panels:
            sig = panel_signature(p)
            h = hashlib.sha256((plan.slug + sig).encode()).hexdigest()
            p["id"] = int(h[:8], 16)
            p.setdefault("g6_meta", {})["panel_uuid"] = h[:16]

        layout_panels(explorer_panels)

        # Compact layout adjustments: reduce base timeseries height to 6
        if is_compact:
            for p in explorer_panels:
                if p.get("type") == "timeseries" and p.get("repeat") == "metric":
                    p.setdefault("gridPos", {})["h"] = 6

        meta = {"spec_hash": spec_hash, "families": plan.families, "description": plan.description, "explorer": True}
        if is_compact:
            meta["compact"] = True
        if is_ultra:
            meta["ultra"] = True
        # Include band_pct for override visibility
        meta["band_pct"] = band_pct

        return {
            "__inputs": [],
            "__requires": [
                {"type": "prometheus", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
            ],
            "title": plan.title,
            "uid": f"g6-{plan.slug}",
            "tags": plan.tags + ["g6", "generated"],
            "timezone": "browser",
            "version": 1,
            "schemaVersion": 39,
            "refresh": "30s",
            "annotations": {"list": []},
            "panels": explorer_panels,
            "templating": {"list": templating_list},
            "time": {"from": "now-6h", "to": "now"},
            "g6_meta": meta,
        }

    fam_set = set(plan.families)
    selected = [m for m in metrics if m.family in fam_set]
    panels: list[dict[str, Any]] = []
    for metric in selected:
        spec_panels = [_convert_spec_panel(metric, i, p) for i, p in enumerate(metric.panel_defs)] if metric.panel_defs else []
        auto_panels = _auto_extra_panels(metric) if not spec_panels else []
        panels.extend(spec_panels or auto_panels)

    if not panels:
        panels.append({
            "type": "table",
            "title": "No Panels (spec produced none)",
            "targets": [{"expr": "/* empty */", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "g6_meta": {"source": "placeholder"},
        })

    for p in panels:
        sig = panel_signature(p)
        h = hashlib.sha256((plan.slug + sig).encode()).hexdigest()
        p["id"] = int(h[:8], 16)
        p.setdefault("g6_meta", {})["panel_uuid"] = h[:16]

    layout_panels(panels)
    return {
        "__inputs": [],
        "__requires": [
            {"type": "prometheus", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
        ],
        "title": plan.title,
        "uid": f"g6-{plan.slug}",
        "tags": plan.tags + ["g6", "generated"],
        "timezone": "browser",
        "version": 1,
        "schemaVersion": 39,
        "refresh": "30s",
        "annotations": {"list": []},
        "panels": panels,
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "g6_meta": {"spec_hash": spec_hash, "families": plan.families, "description": plan.description},
    }


def build_manifest(spec_hash: str, plans: list[DashboardPlan], built: dict[str, dict[str, Any]]) -> dict[str, Any]:
    import time as _t
    entries = []
    for d in plans:
        data = built.get(d.slug)
        panel_count = len((data or {}).get("panels", []) or []) if data else 0
        entries.append({
            "slug": d.slug,
            "uid": f"g6-{d.slug}",
            "families": d.families,
            "panel_count": panel_count,
        })
    return {"spec_hash": spec_hash, "count": len(plans), "generated_at_unix": int(_t.time()), "dashboards": entries}


def detect_drift(output_dir: Path, dashboards: dict[str, dict[str, Any]]) -> list[str]:
    drift: list[str] = []
    verbose = os.environ.get("G6_DASHBOARD_DIFF_VERBOSE", "0") == "1"
    detailed: list[str] = []
    for slug, data in dashboards.items():
        fp = output_dir / f"{slug}.json"
        if not fp.exists():
            drift.append(f"missing:{slug}")
            continue
        try:
            existing = json.loads(fp.read_text())
        except Exception:
            drift.append(f"unreadable:{slug}")
            continue
        if existing.get("g6_meta", {}).get("spec_hash") != data.get("g6_meta", {}).get("spec_hash"):
            drift.append(f"hash:{slug}")
        new_panels = data.get("panels", [])
        old_panels = existing.get("panels", [])
        new_map = {panel_signature(p): p for p in new_panels}
        old_map = {panel_signature(p): p for p in old_panels}
        new_sigs = set(new_map)
        old_sigs = set(old_map)
        raw_added = new_sigs - old_sigs
        raw_removed = old_sigs - new_sigs
        def title_of(sig: str, mp: dict[str, dict[str, Any]]) -> str:
            p = mp.get(sig) or {}
            t = p.get("title")
            return t if isinstance(t, str) else ""
        removed_by_title: dict[str, list[str]] = {}
        for sig in raw_removed:
            removed_by_title.setdefault(title_of(sig, old_map), []).append(sig)
        added_by_title: dict[str, list[str]] = {}
        for sig in raw_added:
            added_by_title.setdefault(title_of(sig, new_map), []).append(sig)
        changed_count = 0
        consumed_added: set[str] = set()
        consumed_removed: set[str] = set()
        for title, old_sig_list in removed_by_title.items():
            new_sig_list = added_by_title.get(title)
            if not new_sig_list:
                continue
            pairings = min(len(old_sig_list), len(new_sig_list))
            changed_count += pairings
            consumed_removed.update(old_sig_list[:pairings])
            consumed_added.update(new_sig_list[:pairings])
        added = [s for s in raw_added if s not in consumed_added]
        removed = [s for s in raw_removed if s not in consumed_removed]
        if changed_count or added or removed:
            if changed_count:
                drift.append(f"changed:{slug}:{changed_count}")
            if added:
                drift.append(f"added:{slug}:{len(added)}")
            if removed:
                drift.append(f"removed:{slug}:{len(removed)}")
            if verbose:
                detailed.append(json.dumps({
                    "slug": slug,
                    "changed_titles": list({title_of(s, old_map) for s in raw_removed} & {title_of(s, new_map) for s in raw_added}),
                    "added_titles": [new_map[s].get("title") for s in added],
                    "removed_titles": [old_map[s].get("title") for s in removed],
                }, sort_keys=True))
    if verbose and detailed:
        print("DRIFT_DETAILS_BEGIN", file=sys.stderr)
        for line in detailed:
            print(line, file=sys.stderr)
        print("DRIFT_DETAILS_END", file=sys.stderr)
    return drift


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate modular Grafana dashboards")
    p.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Output directory for generated dashboards")
    p.add_argument("--dry-run", action="store_true", help="Print plan summary and exit")
    p.add_argument("--verify", action="store_true", help="Fail if existing dashboards differ (drift guard)")
    p.add_argument("--plan", type=Path, help="Optional external plan YAML overriding default plans")
    p.add_argument("--only", type=str, help="Comma-separated list of dashboard slugs to (re)generate; others skipped")
    return p.parse_args(argv)


def load_plans(path: Path | None) -> list[DashboardPlan]:
    if not path:
        return DEFAULT_PLANS
    data = yaml.safe_load(path.read_text()) or {}
    out: list[DashboardPlan] = []
    for item in data.get("dashboards", []) or []:
        out.append(
            DashboardPlan(
                slug=item["slug"],
                title=item.get("title", item["slug"].title()),
                families=item.get("families", []),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            )
        )
    return out


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    if not SPEC_PATH.exists():
        print(f"ERROR: spec file missing: {SPEC_PATH}", file=sys.stderr)
        return 2

    metrics = load_spec_metrics(SPEC_PATH)
    families_present = {m.family for m in metrics}
    spec_hash = spec_hash_text([SPEC_PATH])
    plans = load_plans(args.plan)
    only_set: set[str] | None = None
    if args.only:
        only_set = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown_requested = [s for s in only_set if s not in {p.slug for p in plans}]
        if unknown_requested:
            print(f"ERROR: --only specified unknown dashboard slugs: {', '.join(sorted(unknown_requested))}", file=sys.stderr)
            return 5

    unknown: dict[str, list[str]] = {}
    for plan in plans:
        missing = [f for f in plan.families if f not in families_present]
        if missing:
            unknown[plan.slug] = missing
    if unknown:
        for slug, miss in unknown.items():
            print(f"ERROR: plan '{slug}' references unknown families: {', '.join(miss)}", file=sys.stderr)
        return 3

    if args.dry_run:
        print("Plan Summary:")
        for p in plans:
            print(f"  - {p.slug}: families={p.families}")
        print(f"Spec hash: {spec_hash}")
        return 0

    dashboards: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if plan.slug in dashboards:
            print(f"ERROR: duplicate dashboard slug: {plan.slug}", file=sys.stderr)
            return 4
        if only_set and plan.slug not in only_set:
            continue
        dashboards[plan.slug] = synth_dashboard(plan, metrics, spec_hash)

    write_on_verify = False
    if args.verify:
        drift = detect_drift(args.output, dashboards)
        if drift:
            print("SEMANTIC DRIFT DETECTED:", ", ".join(drift), file=sys.stderr)
            write_on_verify = True

    args.output.mkdir(parents=True, exist_ok=True)
    for slug, data in dashboards.items():
        path = args.output / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True))

    # Manifest includes all plans, with 0 panel_count for skipped slugs to signal omission (satisfies tests)
    manifest = build_manifest(spec_hash, plans, dashboards)
    manifest_path = args.output / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    print(f"Generated {len(dashboards)} dashboards -> {args.output} (spec_hash={spec_hash})")
    if args.verify and write_on_verify:
        return 6
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
