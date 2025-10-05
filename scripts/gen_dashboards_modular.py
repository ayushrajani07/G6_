#!/usr/bin/env python
"""Modular Grafana dashboard generator (scaffold).

Phase 0 goals (scaffold):
  * Load canonical metrics spec (YAML + generated metadata) to discover families & metrics
  * Define a configurable mapping of spec families -> dashboard plans
  * Synthesize minimal placeholder dashboard JSON structures (valid enough for provisioning)
  * Compute spec content hash and embed into dashboard / manifest annotations
  * Support --dry-run (print plan summary) and --write (default) modes
  * Avoid committing to final panel schemas; placeholders mark where future synthesis rules apply

Future phases will enrich panel generation (rates, hist quantiles, label splits) and layout heuristics.

Exit non-zero if (a) unknown family referenced in plan, (b) duplicate dashboard slug, or (c) output drift detected under --verify.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML required for dashboard generation (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "metrics" / "spec" / "base.yml"
OUTPUT_DIR = ROOT / "grafana" / "dashboards" / "generated"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# Semantic panel signature helper (global) used for stable IDs & diff
def panel_signature(panel: Dict) -> str:
    t = panel.get("type")
    title = panel.get("title")
    raw_exprs = [tgt.get("expr") for tgt in panel.get("targets", []) if isinstance(tgt, dict)]
    exprs = sorted([e for e in raw_exprs if isinstance(e, str)])
    ds = panel.get("datasource", {}).get("type")
    unit = panel.get("fieldConfig", {}).get("defaults", {}).get("unit")
    return json.dumps({"type": t, "title": title, "exprs": exprs, "ds": ds, "unit": unit}, sort_keys=True)

# ----------------------------- Data Structures ----------------------------- #

@dataclass
class Metric:
    name: str
    kind: str  # counter|gauge|histogram
    labels: List[str]
    family: str
    panel_defs: List[dict] = field(default_factory=list)  # raw spec panel entries
    alerts: List[dict] = field(default_factory=list)

@dataclass
class DashboardPlan:
    slug: str
    title: str
    families: List[str]
    description: str = ""
    tags: List[str] = field(default_factory=list)

# Default plan mapping (can be externalized later)
DEFAULT_PLANS: List[DashboardPlan] = [
    DashboardPlan(slug="provider_ingestion", title="Provider / Ingestion", families=["provider", "provider_mode"], description="Provider success/error and mode mix"),
    DashboardPlan(slug="bus_stream", title="Bus & Stream", families=["bus", "stream"], description="Stream gating, bus throughput, conflicts"),
    DashboardPlan(slug="emission_pipeline", title="Emission Pipeline", families=["emission"], description="Emission batching / sinks metrics"),
    DashboardPlan(slug="panels_summary", title="Panels Summary", families=["panels", "stream"], description="Panel diff efficiency & state gating"),
    DashboardPlan(slug="column_store", title="Column Store", families=["column_store"], description="Column store refresh / errors"),
    DashboardPlan(slug="governance", title="Metrics Governance", families=["governance"], description="Governance invariants / catalog generation health"),
    DashboardPlan(slug="option_chain", title="Option Chain", families=["option_chain"], description="Option chain aggregates & IV health"),
    # New focused dashboards (Phase 7 enrichment)
    DashboardPlan(slug="panels_efficiency", title="Panels Efficiency", families=["panels"], description="Diff vs full efficiency & truncation health"),
    DashboardPlan(slug="lifecycle_storage", title="Lifecycle & Storage", families=["column_store", "emission"], description="Ingest latency, backlog, retries & emission batching"),
]

# ----------------------------- Spec Loading ----------------------------- #

def load_spec_metrics(spec_path: Path) -> List[Metric]:
    """Load metrics from spec, supporting the nested 'families' mapping layout.

    Expected structure:
    version: 1
    families:
      family_name:
        owner: path
        metrics:
          - name: ...
            type: counter|gauge|histogram
            labels: []
    """
    raw = yaml.safe_load(spec_path.read_text()) or {}
    fam_block = raw.get("families", {})
    metrics: List[Metric] = []
    for family, fdata in fam_block.items():
        entries = (fdata or {}).get("metrics", [])
        if not isinstance(entries, list):
            continue
        for m in entries:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            kind = m.get("type")
            labels = m.get("labels") or []
            panel_defs = m.get("panels") or []
            alerts = m.get("alerts") or []
            if not name or not kind:
                continue
            metrics.append(Metric(name=name, kind=kind, labels=labels, family=family, panel_defs=panel_defs, alerts=alerts))
    return metrics


def spec_hash_text(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]

# ----------------------------- Dashboard Synthesis ----------------------------- #

def synth_placeholder_panel(metric: Metric) -> Dict:
    """Fallback panel when no spec guidance present (should be rare after enrichment)."""
    expr = f"sum(rate({metric.name}[5m]))" if metric.kind == "counter" else metric.name
    return {
        "type": "timeseries",
        "title": f"{metric.name} (auto)",
        "targets": [{"expr": expr, "refId": "A"}],
        "datasource": {"type": "prometheus", "uid": "PROM"},
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
    }
    import json


def _convert_spec_panel(metric: Metric, idx: int, pdef: dict) -> Dict:
    title = pdef.get("title") or f"{metric.name} panel {idx}"  # fallback
    expr = pdef.get("promql") or f"/* missing promql for {metric.name}:{pdef.get('kind','?')} */"
    panel_type = pdef.get("panel_type") or "timeseries"
    unit = pdef.get("unit")
    return {
        "type": panel_type,
        "title": title,
        "targets": [{"expr": expr, "refId": "A"}],
        "datasource": {"type": "prometheus", "uid": "PROM"},
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": []},
    }


def _auto_extra_panels(metric: Metric) -> List[Dict]:
    """Synthesize default panels not explicitly present in spec.

    Rules (Phase 1):
      counter -> total rate (5m) if no spec panel uses rate on this metric
      histogram -> p95 / p99 quantiles if absent (assumes *_bucket naming convention)
      gauge with >0 labels -> topk by first label (heuristic) if missing panels
    """
    extras: List[Dict] = []
    existing_exprs = { (p.get("promql") or "").strip() for p in metric.panel_defs if isinstance(p, dict) }
    if metric.kind == "counter":
        base_rate = f"sum(rate({metric.name}[5m]))"
        if not any("rate(" in e and metric.name in e for e in existing_exprs):
            extras.append({
                "type": "timeseries",
                "title": f"{metric.name} Rate (5m auto)",
                "targets": [{"expr": base_rate, "refId": "A"}],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            })
    elif metric.kind == "histogram":
        # Expect *_bucket naming.
        bucket_metric = f"{metric.name}_bucket"
        p95 = f"histogram_quantile(0.95, sum by (le) (rate({bucket_metric}[5m])))"
        p99 = f"histogram_quantile(0.99, sum by (le) (rate({bucket_metric}[5m])))"
        if not any("histogram_quantile" in e and "0.95" in e and metric.name in e for e in existing_exprs):
            extras.append(_convert_spec_panel(metric, 0, {"title": f"{metric.name} p95 (5m auto)", "promql": p95, "unit": "ms" if metric.name.endswith("_ms") else None}))
        if not any("histogram_quantile" in e and "0.99" in e and metric.name in e for e in existing_exprs):
            extras.append(_convert_spec_panel(metric, 1, {"title": f"{metric.name} p99 (5m auto)", "promql": p99, "unit": "ms" if metric.name.endswith("_ms") else None}))
    elif metric.kind == "gauge" and metric.labels:
        # Provide a topk split panel if none exists referencing metric name.
        split_expr = f"topk(5, {metric.name})"
        if not any(metric.name in e for e in existing_exprs):
            extras.append({
                "type": "timeseries",
                "title": f"{metric.name} Top 5 (auto)",
                "targets": [{"expr": split_expr, "refId": "A"}],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            })

    # Label splitting heuristics (Phase 2): create rate/sum by individual label panels if safe.
    # We only apply if <=2 candidate labels (to avoid explosion) and label not already used in an existing expr.
    label_split_cap = 2
    if metric.labels and (metric.kind in {"counter", "gauge"}):
        for lbl in metric.labels[:label_split_cap]:
            if any(f"by ({lbl})" in e for e in existing_exprs):
                continue
            if metric.kind == "counter":
                expr = f"sum by ({lbl}) (rate({metric.name}[5m]))"
                title = f"{metric.name} Rate by {lbl} (5m auto)"
            else:  # gauge
                expr = f"sum by ({lbl}) ({metric.name})"
                title = f"{metric.name} by {lbl} (auto)"
            extras.append({
                "type": "timeseries",
                "title": title,
                "targets": [{"expr": expr, "refId": "A"}],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            })
    return extras


def _efficiency_ratio_panels(metrics: List[Metric]) -> List[Dict]:
    """Heuristic synthesis for efficiency ratio panels (Phase 7).

    Looks for diff bytes vs total rows/bytes style metrics to compute compression/efficiency.
    For now, specifically handles panel diff bytes efficiency:
      diff_bytes_total / clamp_min(sum diff_bytes_total,1) is trivial; instead compute rolling bytes per diff write.
    Also column store ingest bytes per row if both counters present.
    """
    panels: List[Dict] = []
    names = {m.name: m for m in metrics}
    # Panel diff efficiency: bytes per write (rate-based) and cumulative average (total bytes / total writes)
    if "g6_panel_diff_bytes_total" in names and "g6_panel_diff_writes_total" in names:
        panels.append({
            "type": "timeseries",
            "title": "Diff Bytes per Write (5m auto)",
            "targets": [{"expr": "(sum(rate(g6_panel_diff_bytes_total[5m])) / clamp_min(sum(rate(g6_panel_diff_writes_total[5m])),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
        })
        panels.append({
            "type": "timeseries",
            "title": "Avg Diff Bytes per Write (Cumulative auto)",
            "targets": [{"expr": "(sum(g6_panel_diff_bytes_total) / clamp_min(sum(g6_panel_diff_writes_total),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
        })
    # Column store bytes per row efficiency (compression opportunity indicator)
    if "g6_cs_ingest_bytes_total" in names and "g6_cs_ingest_rows_total" in names:
        panels.append({
            "type": "timeseries",
            "title": "CS Bytes per Row (5m auto)",
            "targets": [{"expr": "(sum(rate(g6_cs_ingest_bytes_total[5m])) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
        })
        panels.append({
            "type": "timeseries",
            "title": "CS Avg Bytes per Row (Cumulative auto)",
            "targets": [{"expr": "(sum(g6_cs_ingest_bytes_total) / clamp_min(sum(g6_cs_ingest_rows_total),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
        })
    # Backlog burn rate (minutes to drain) if backlog rows + rows ingest rate present
    if "g6_cs_ingest_backlog_rows" in names and "g6_cs_ingest_rows_total" in names:
        panels.append({
            "type": "timeseries",
            "title": "CS Backlog Drain ETA (mins auto)",
            "targets": [{"expr": "(sum(g6_cs_ingest_backlog_rows) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1)) / 60", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
            "fieldConfig": {"defaults": {"unit": "m"}, "overrides": []},
        })
    # Success ratio (1 - failures_rate/rows_rate) if failures and rows counters exist
    if "g6_cs_ingest_failures_total" in names and "g6_cs_ingest_rows_total" in names:
        panels.append({
            "type": "timeseries",
            "title": "CS Ingest Success Ratio (5m auto)",
            "targets": [{"expr": "1 - (clamp_min(sum(rate(g6_cs_ingest_failures_total[5m])),0) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
            "fieldConfig": {"defaults": {"unit": "percentunit"}, "overrides": []},
        })
    return panels


def layout_panels(panels: List[Dict]) -> None:
    """Assign grid positions in a simple row-major fashion (2 columns)."""
    col_w = 12
    h = 8
    for idx, p in enumerate(panels):
        row = idx // 2
        col = idx % 2
        p["gridPos"] = {"h": h, "w": col_w, "x": col * col_w, "y": row * h}


def synth_dashboard(plan: DashboardPlan, metrics: List[Metric], spec_hash: str) -> Dict:
    fam_set = set(plan.families)
    selected = [m for m in metrics if m.family in fam_set]

    panels: List[Dict] = []
    # Build enriched panels per metric (cap total to avoid explosion)
    for metric in selected:
        spec_panels = [_convert_spec_panel(metric, i, p) for i, p in enumerate(metric.panel_defs)] if metric.panel_defs else []
        auto_panels = _auto_extra_panels(metric)
        if not spec_panels and not auto_panels:
            spec_panels = [synth_placeholder_panel(metric)]
        for p in spec_panels + auto_panels:
            panels.append(p)
            if len(panels) >= 36:  # hard safety cap
                break
        if len(panels) >= 36:
            break

    # Phase 7: append cross-metric efficiency ratio panels for specific dashboards
    if plan.slug in {"panels_efficiency", "column_store", "lifecycle_storage"}:
        try:
            ratio_panels = _efficiency_ratio_panels(metrics)
            for rp in ratio_panels:
                if len(panels) >= 36:
                    break
                panels.append(rp)
        except Exception as e:  # pragma: no cover
            # Non-fatal; continue without ratio panels
            print(f"WARN: efficiency ratio synthesis failed for {plan.slug}: {e}", file=sys.stderr)

    # Alert surfacing panel (aggregated spec alerts for included metrics)
    alert_rows = []
    for metric in selected:
        for a in metric.alerts:
            alert_rows.append({
                "alert": a.get("alert"),
                "metric": metric.name,
                "severity": a.get("severity"),
                "summary": a.get("summary"),
                "expr": a.get("expr"),
            })
    if alert_rows:
        # Encode rows into a JSON datasource expression (Grafana can't natively plot arbitrary tables without a plugin; placeholder).
        # We synthesize a 'stateless' table panel with the expression embedded as a comment.
        expr = "/* ALERTS:\n" + "\n".join(
            f"{r['alert']}|{r['metric']}|{r['severity']}|{(r['summary'] or '')[:40]}|{(r['expr'] or '')[:60]}" for r in alert_rows
        ) + "\n*/"
        panels.insert(0, {
            "type": "table",
            "title": "Spec Alerts Overview",
            "targets": [{"expr": expr, "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 0},
            "options": {"showHeader": True},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "g6_meta": {"alerts_count": len(alert_rows)},
        })

    # Stable IDs: hash(slug + signature) -> first 8 hex as int, plus uuid prefix
    import hashlib as _hl
    for p in panels:
        sig = panel_signature(p)
        h = _hl.sha256((plan.slug + sig).encode()).hexdigest()
        p["id"] = int(h[:8], 16)
        meta = p.setdefault("g6_meta", {})
        meta["panel_uuid"] = h[:16]

    layout_panels(panels)
    placeholder = all("(auto)" in p.get("title", "") for p in panels if p.get("type") != "table")
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
        "g6_meta": {
            "spec_hash": spec_hash,
            "families": plan.families,
            "placeholder_panels": placeholder,
            "description": plan.description,
            "enriched": True,
            "alerts_panel": bool(alert_rows),
            "alerts_count": len(alert_rows),
        },
    }

# ----------------------------- Manifest ----------------------------- #

def build_manifest(spec_hash: str, dashboards: List[DashboardPlan]) -> Dict:
    return {
        "spec_hash": spec_hash,
        "count": len(dashboards),
        "dashboards": [
            {"slug": d.slug, "uid": f"g6-{d.slug}", "families": d.families} for d in dashboards
        ],
    }

# ----------------------------- Main CLI ----------------------------- #

def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate modular Grafana dashboards (scaffold)")
    p.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Output directory for generated dashboards")
    p.add_argument("--dry-run", action="store_true", help="Print plan summary and exit")
    p.add_argument("--verify", action="store_true", help="Fail if existing dashboards differ (drift guard)")
    p.add_argument("--plan", type=Path, help="Optional external plan YAML overriding default plans")
    return p.parse_args(argv)


def load_plans(path: Path | None) -> List[DashboardPlan]:
    if not path:
        return DEFAULT_PLANS
    data = yaml.safe_load(path.read_text())
    out: List[DashboardPlan] = []
    for item in data.get("dashboards", []):
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


def detect_drift(output_dir: Path, dashboards: Dict[str, Dict]) -> List[str]:
    drift: List[str] = []

    def panel_signature(panel: Dict) -> str:
        """Generate a semantic signature for a panel ignoring layout & ids.

        Elements included: type, title, sorted target exprs, datasource type, field unit.
        """
        t = panel.get("type")
        title = panel.get("title")
        raw_exprs = [tgt.get("expr") for tgt in panel.get("targets", []) if isinstance(tgt, dict)]
        exprs = sorted([e for e in raw_exprs if isinstance(e, str)])
        ds = panel.get("datasource", {}).get("type")
        unit = panel.get("fieldConfig", {}).get("defaults", {}).get("unit")
        return json.dumps({"type": t, "title": title, "exprs": exprs, "ds": ds, "unit": unit}, sort_keys=True)

    for slug, data in dashboards.items():
        fp = output_dir / f"{slug}.json"
        if not fp.exists():
            drift.append(f"missing:{slug}")
            continue
        try:
            existing = json.loads(fp.read_text())
        except Exception:  # pragma: no cover
            drift.append(f"unreadable:{slug}")
            continue
        # Spec hash check (strict)
        if existing.get("g6_meta", {}).get("spec_hash") != data.get("g6_meta", {}).get("spec_hash"):
            drift.append(f"hash:{slug}")

        # Semantic panel diff
        new_panels = data.get("panels", [])
        old_panels = existing.get("panels", [])
        new_map = {panel_signature(p): p for p in new_panels}
        old_map = {panel_signature(p): p for p in old_panels}
        new_sigs = set(new_map.keys())
        old_sigs = set(old_map.keys())
        raw_added = new_sigs - old_sigs
        raw_removed = old_sigs - new_sigs

        # Detect changed panels by title intersection: if a title exists in both
        # sets but signatures differ, classify as changed (increment count) and
        # remove one from added/removed classification.
        def title_of(sig: str, mp: Dict[str, Dict]) -> str:
            p = mp.get(sig) or {}
            return p.get("title", "")

        removed_by_title: Dict[str, List[str]] = {}
        for sig in raw_removed:
            removed_by_title.setdefault(title_of(sig, old_map), []).append(sig)
        added_by_title: Dict[str, List[str]] = {}
        for sig in raw_added:
            added_by_title.setdefault(title_of(sig, new_map), []).append(sig)

        changed_count = 0
        consumed_added: set[str] = set()
        consumed_removed: set[str] = set()
        for title, old_sig_list in removed_by_title.items():
            new_sig_list = added_by_title.get(title)
            if not new_sig_list:
                continue
            # At least one panel with same title removed and one added -> treat as changed pair(s)
            # Pair min(len(old), len(new)) as changed.
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
    return drift


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    if not SPEC_PATH.exists():
        print(f"ERROR: spec file missing: {SPEC_PATH}", file=sys.stderr)
        return 2

    metrics = load_spec_metrics(SPEC_PATH)
    families_present = {m.family for m in metrics}
    spec_hash = spec_hash_text([SPEC_PATH])
    plans = load_plans(args.plan)

    # Validate plan families
    unknown: Dict[str, List[str]] = {}
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

    # Synthesize
    dashboards: Dict[str, Dict] = {}
    for plan in plans:
        if plan.slug in dashboards:
            print(f"ERROR: duplicate dashboard slug: {plan.slug}", file=sys.stderr)
            return 4
        dashboards[plan.slug] = synth_dashboard(plan, metrics, spec_hash)

    # Drift detection (before writing) if --verify
    if args.verify:
        drift = detect_drift(args.output, dashboards)
        if drift:
            print("SEMANTIC DRIFT DETECTED:", ", ".join(drift), file=sys.stderr)
            return 6  # distinct exit code for semantic drift

    # Ensure output dir
    args.output.mkdir(parents=True, exist_ok=True)

    # Write dashboards
    for slug, data in dashboards.items():
        path = args.output / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True))

    # Write manifest
    manifest = build_manifest(spec_hash, plans)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    print(f"Generated {len(dashboards)} dashboards -> {args.output} (spec_hash={spec_hash})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
