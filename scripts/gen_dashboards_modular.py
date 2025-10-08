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
    DashboardPlan(slug="system_overview", title="System Overview", families=["system"], description="System-level success & latency gauges"),
    # New focused dashboards (Phase 7 enrichment)
    DashboardPlan(slug="panels_efficiency", title="Panels Efficiency", families=["panels"], description="Diff vs full efficiency & truncation health"),
    DashboardPlan(slug="lifecycle_storage", title="Lifecycle & Storage", families=["column_store", "emission"], description="Ingest latency, backlog, retries & emission batching"),
    # Added Phase A enhancement: consolidated health view (bus + system + governance) for rapid triage.
    DashboardPlan(slug="health_core", title="Core Health", families=["system", "bus", "governance"], description="High-signal health indicators for core subsystems"),
    # Phase D: additional focused health dashboards.
    DashboardPlan(slug="bus_health", title="Bus Health", families=["bus"], description="Bus publish latency & throughput health"),
    DashboardPlan(slug="system_overview_minimal", title="System Overview (Minimal)", families=["system"], description="Compact system success & latency snapshot", tags=["minimal"]),
    # Exploratory dashboard (Phase: explorer initial). Special synthesis (templated multi-pane) not tied to single family enumeration.
    DashboardPlan(slug="multi_pane_explorer", title="Multi-Pane Explorer", families=["system"], description="Ad-hoc single-metric multi-window exploration panels", tags=["explorer", "experimental"]),
    DashboardPlan(slug="multi_pane_explorer_compact", title="Multi-Pane Explorer (Compact)", families=["system"], description="Compact variant of multi-pane explorer (reduced height, no cumulative panel)", tags=["explorer", "experimental", "compact"]),
    DashboardPlan(slug="multi_pane_explorer_ultra", title="Multi-Pane Explorer (Ultra)", families=["system"], description="Ultra compact variant (ratio & cumulative folded into summary).", tags=["explorer", "experimental", "ultra"]),
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
        "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "placeholder"},
    }


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
        "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "spec"},
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
                "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "auto_rate"},
            })
    elif metric.kind == "histogram":
        # Prefer recording rule series (added Phase 7) instead of inline histogram_quantile to reduce query cost.
        # Fallback logic: we still generate the panel even if rule not yet loaded; Grafana will show "no data" until Prometheus loads rules.
        p95_rec = f"{metric.name}:p95_5m"
        p99_rec = f"{metric.name}:p99_5m"
        if not any(metric.name in e and ":p95_" in e for e in existing_exprs):
            p = _convert_spec_panel(metric, 0, {"title": f"{metric.name} p95 (5m auto)", "promql": p95_rec, "unit": "ms" if metric.name.endswith("_ms") else None})
            p.setdefault("g6_meta", {}).update({"source": "auto_hist_quantile"})
            extras.append(p)
        if not any(metric.name in e and ":p99_" in e for e in existing_exprs):
            p = _convert_spec_panel(metric, 1, {"title": f"{metric.name} p99 (5m auto)", "promql": p99_rec, "unit": "ms" if metric.name.endswith("_ms") else None})
            p.setdefault("g6_meta", {}).update({"source": "auto_hist_quantile"})
            extras.append(p)
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
                "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "auto_topk"},
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
                "g6_meta": {"metric": metric.name, "family": metric.family, "kind": metric.kind, "source": "auto_label_split", "split_label": lbl},
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
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
        panels.append({
            "type": "timeseries",
            "title": "Avg Diff Bytes per Write (Cumulative auto)",
            "targets": [{"expr": "(sum(g6_panel_diff_bytes_total) / clamp_min(sum(g6_panel_diff_writes_total),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
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
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
        panels.append({
            "type": "timeseries",
            "title": "CS Avg Bytes per Row (Cumulative auto)",
            "targets": [{"expr": "(sum(g6_cs_ingest_bytes_total) / clamp_min(sum(g6_cs_ingest_rows_total),1))", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
            "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
    # Backlog burn rate (minutes to drain) if backlog rows + rows ingest rate present
    if "g6_cs_ingest_backlog_rows" in names and "g6_cs_ingest_rows_total" in names:
        panels.append({
            "type": "timeseries",
            "title": "CS Backlog Drain ETA (mins auto)",
            "targets": [{"expr": "g6_cs_ingest_backlog_rows:eta_minutes", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
            "fieldConfig": {"defaults": {"unit": "m"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
        # Backlog burn rate: positive value when backlog decreasing. Uses delta/backlog over 5m divided by 300s to approximate rows/s change.
        # If backlog is absent or growing (delta >= 0) this will produce 0 via max().
        panels.append({
            "type": "timeseries",
            "title": "CS Backlog Burn Rate (rows/s auto)",
            "targets": [{
                "expr": "g6_cs_ingest_backlog_rows:burn_rows_per_s",
                "refId": "A"
            }],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
            "fieldConfig": {"defaults": {"unit": "rows"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
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
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
    # Multi-window latency comparison: ingest latency histogram & bus publish latency
    if "g6_cs_ingest_latency_ms" in names:
        panels.append({
            "type": "timeseries",
            "title": "CS Ingest p95 5m vs 30m (auto)",
            "targets": [
                {"expr": "g6_cs_ingest_latency_ms:p95_5m", "refId": "A"},
                {"expr": "g6_cs_ingest_latency_ms:p95_30m", "refId": "B"}
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 24},
            "fieldConfig": {"defaults": {"unit": "ms"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
        panels.append({
            "type": "timeseries",
            "title": "CS Ingest p95 Ratio (5m/30m auto)",
            "targets": [{"expr": "g6_cs_ingest_latency_ms:p95_ratio_5m_30m", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 24},
            "fieldConfig": {"defaults": {"unit": "ratio"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
    if "g6_bus_publish_latency_ms" in names:
        panels.append({
            "type": "timeseries",
            "title": "Bus Publish p95 5m vs 30m (auto)",
            "targets": [
                {"expr": "g6_bus_publish_latency_ms:p95_5m_by_bus", "refId": "A"},
                {"expr": "g6_bus_publish_latency_ms:p95_30m_by_bus", "refId": "B"}
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 32},
            "fieldConfig": {"defaults": {"unit": "ms"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
        panels.append({
            "type": "timeseries",
            "title": "Bus Publish p95 Ratio (5m/30m auto)",
            "targets": [{"expr": "g6_bus_publish_latency_ms:p95_ratio_5m_30m_by_bus", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 32},
            "fieldConfig": {"defaults": {"unit": "ratio"}, "overrides": []},
            "g6_meta": {"group": "efficiency", "source": "cross_metric"},
        })
    # Desired ordering key map (title prefix -> rank)
    order_rank = {
        "Diff Bytes per Write": 10,
        "Avg Diff Bytes per Write": 11,
        "CS Bytes per Row": 20,
        "CS Avg Bytes per Row": 21,
        "CS Backlog Drain ETA": 30,
        "CS Backlog Burn Rate": 31,
        "CS Ingest Success Ratio": 40,
        "CS Ingest p95 5m vs 30m": 50,
        "CS Ingest p95 Ratio": 51,
        "Bus Publish p95 5m vs 30m": 60,
        "Bus Publish p95 Ratio": 61,
    }
    def rank(p: Dict) -> int:
        title = p.get("title", "")
        for prefix, r in order_rank.items():
            if title.startswith(prefix):
                return r
        return 999
    panels.sort(key=rank)
    return panels


def layout_panels(panels: List[Dict]) -> None:
    """Adaptive layout with grouping.

    Strategy:
    1. Wide table panels (width>=24 or titles 'Spec Alerts Overview'/'Recording Rule Usage Summary') pinned at top in insertion order.
    2. Core panels (no g6_meta.group or group!=efficiency) laid out next (2-column grid).
    3. Efficiency group panels (g6_meta.group == 'efficiency') appended at bottom (2-column grid).
    This preserves semantic ordering while visually clustering related efficiency diagnostics.
    """
    wide_titles = {"Spec Alerts Overview", "Recording Rule Usage Summary", "Efficiency & Latency Diagnostics"}
    wide: List[Dict] = []
    core: List[Dict] = []
    eff: List[Dict] = []
    for p in panels:
        title = p.get("title")
        grp = p.get("g6_meta", {}).get("group") if isinstance(p.get("g6_meta"), dict) else None
        if title in wide_titles or (p.get("type") == "table" and p.get("gridPos", {}).get("w", 0) >= 24):
            wide.append(p)
        elif grp == "efficiency":
            eff.append(p)
        else:
            core.append(p)

    # Reassemble preserving relative order inside each bucket
    ordered = wide + core + eff

    # Apply grid positions (skip wide which we set to full width at top stacking)
    y_cursor = 0
    dense = os.environ.get("G6_DASHBOARD_DENSE", "0") == "1"
    for p in wide:
        default_h = p.get("gridPos", {}).get("h", 8)
        if dense and p.get("title") in {"Spec Alerts Overview", "Recording Rule Usage Summary"}:
            default_h = max(6, min(default_h, 8))
        p["gridPos"] = {"h": default_h, "w": 24, "x": 0, "y": y_cursor}
        y_cursor += p["gridPos"]["h"]

    def place_grid(items: List[Dict], start_y: int) -> int:
        base_h = 8
        col_w = 12
        for idx, panel in enumerate(items):
            row = idx // 2
            col = idx % 2
            # Compact ratio panels & success ratio in dense mode
            h = base_h
            if dense:
                title = panel.get("title", "")
                if "Ratio" in title or "Success Ratio" in title:
                    h = 6
            panel["gridPos"] = {"h": h, "w": col_w, "x": col * col_w, "y": start_y + row * base_h}
        rows = (len(items) + 1) // 2
        return start_y + rows * base_h

    y_cursor = place_grid(core, y_cursor)
    y_cursor = place_grid(eff, y_cursor)

    # Replace original list order in place
    panels[:] = ordered


from typing import Optional, Dict as _Dict
import os as _os


def _parse_delta_env() -> Optional[dict]:
    """Parse env var G6_EXPLORER_DELTA_THRESH.

    Formats accepted:
      JSON object: {"negative_red": -0.25, "negative_yellow": -0.07, "positive_yellow": 0.07, "positive_red": 0.25}
      CSV (4 numbers): neg_red,neg_yellow,pos_yellow,pos_red  e.g. "-0.2,-0.05,0.05,0.2"
    Returns dict or None if unset/invalid.
    """
    raw = _os.environ.get("G6_EXPLORER_DELTA_THRESH")
    if not raw:
        return None
    raw = raw.strip()
    # Try JSON
    if raw.startswith("{"):
        try:
            import json as _json
            data = _json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    # Try CSV
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 4:
        try:
            nr, ny, py, pr = [float(p) for p in parts]
            return {"negative_red": nr, "negative_yellow": ny, "positive_yellow": py, "positive_red": pr}
        except Exception:
            return None
    return None


def _delta_threshold_steps(config: Optional[_Dict[str, float]] = None):
    """Return Grafana threshold steps for delta percent column.

    Config schema (all optional):
      negative_red: float (default -0.20)
      negative_yellow: float (default -0.05)
      positive_yellow: float (default 0.05)
      positive_red: float (default 0.20)
    We map a symmetric band: red <= neg_red, yellow between neg_red..neg_yellow,
    green between neg_yellow..pos_yellow, yellow between pos_yellow..pos_red, red > pos_red.
    Grafana requires ascending order steps.
    """
    cfg = config or _parse_delta_env() or {}
    neg_red = cfg.get("negative_red", -0.20)
    neg_yellow = cfg.get("negative_yellow", -0.05)
    pos_yellow = cfg.get("positive_yellow", 0.05)
    pos_red = cfg.get("positive_red", 0.20)
    # Ensure ordering sanity; if misconfigured fall back to defaults recursively
    if not (neg_red < neg_yellow < 0 < pos_yellow < pos_red):
        if config:  # fallback once
            return _delta_threshold_steps()
    return [
        {"color": "red", "value": -999},
        {"color": "red", "value": neg_red},
        {"color": "yellow", "value": neg_yellow},
        {"color": "green", "value": pos_yellow},
        {"color": "yellow", "value": pos_red},
        {"color": "red", "value": pos_red + 1e-9},  # tiny epsilon to capture > pos_red
    ]


def synth_dashboard(plan: DashboardPlan, metrics: List[Metric], spec_hash: str) -> Dict:
    # Special-case: multi-pane explorer variants (templated generic panels). Return early.
    if plan.slug in {"multi_pane_explorer", "multi_pane_explorer_compact", "multi_pane_explorer_ultra"}:
        # Optional config file precedence (explorer_config.json) for overrides
        cfg_path = Path(__file__).resolve().parent.parent / "explorer_config.json"
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text()) or {}
            except Exception:
                cfg = {}
        # band_pct precedence: config > env > default 20
        band_pct = cfg.get("band_pct")
        if band_pct is None:
            try:
                band_pct = float(_os.environ.get("G6_EXPLORER_BAND_PCT", "20"))
            except ValueError:
                band_pct = 20.0
        # Clamp band percentage
        band_pct = max(1.0, min(90.0, band_pct))
        band_factor = band_pct / 100.0
        # Build a custom list variable of governed metric names (capped for safety)
        metric_names = sorted({m.name for m in metrics})
        metric_kind_map = {m.name: m.kind for m in metrics}
        # Quantile availability detection: collect recording rule style names suffixes like :p95_5m
        rec_name_set = set(metric_names)
        quantile_candidates = ["p50", "p90", "p95", "p99"]
        available_quants = []
        # Heuristic: if any histogram metric base name + :<q>_5m exists in rec set, include q option
        hist_bases = [n for n,k in metric_kind_map.items() if k == "histogram"]
        for q in quantile_candidates:
            suffix = f":{q}_5m"
            if any((hb + suffix) in rec_name_set for hb in hist_bases):
                available_quants.append(q)
        if not available_quants:
            available_quants = ["p95"]  # fallback default
        # Ensure default selected quantile is p95 if present else first
        default_q = "p95" if "p95" in available_quants else available_quants[0]
        METRIC_CAP = 150
        capped = metric_names[:METRIC_CAP]
        hist_names = [n for n in capped if metric_kind_map.get(n) == "histogram"]
        templating_list = [
            {
                "type": "custom",
                "name": "metric",
                "label": "Metric",
                "query": ",".join(capped),
                "options": [
                    {"text": n, "value": n, "selected": i == 0} for i, n in enumerate(capped)
                ],
                "current": {"text": (capped[0] if capped else ""), "value": (capped[0] if capped else "")},
                # Multi-select enabled: Grafana will repeat base panels per selected value (we add repeat attr below)
                "includeAll": False,
                "multi": True,
            },
            {
                "type": "custom",
                "name": "metric_hist",
                "label": "Histogram Metric",
                "query": ",".join(hist_names),
                "options": [
                    {"text": n, "value": n, "selected": False} for n in hist_names
                ],
                "current": {"text": (hist_names[0] if hist_names else ""), "value": (hist_names[0] if hist_names else "")},
                "includeAll": False,
                "multi": True,
            },
            {
                # Toggle to enable/disable fast overlay (e.g., near-real-time short window query). Values: off|on
                "type": "custom",
                "name": "overlay",
                "label": "Overlay",
                "query": "off,fast,ultra",
                "options": [
                    {"text": "off", "value": "off", "selected": True},
                    {"text": "fast", "value": "fast", "selected": False},
                    {"text": "ultra", "value": "ultra", "selected": False},
                ],
                "current": {"text": "off", "value": "off"},
                "includeAll": False,
                "multi": False,
            }
        ,
            {
                # Quantile selector for histogram panels (applies to pXX recording rules)
                "type": "custom",
                "name": "q",
                "label": "Quantile",
                "query": ",".join(available_quants),
                "options": [
                    {"text": q, "value": q, "selected": (q == default_q)} for q in available_quants
                ],
                "current": {"text": default_q, "value": default_q},
                "includeAll": False,
                "multi": False,
            }
        ]
        base_panels: List[Dict] = [
            {
                "type": "timeseries",
                "title": "$metric raw & 5m rate",
                "targets": [
                    {"expr": "$metric", "refId": "A"},
                    {"expr": "sum(rate($metric[5m]))", "refId": "B"},
                    # Conditional overlays:
                    # fast  -> 30s rate
                    # ultra -> 15s rate + smoothed moving average of 30s rate over 2m
                    {"expr": "(($overlay == 'fast') or ($overlay == 'ultra')) * sum(rate($metric[30s]))", "refId": "C"},
                    {"expr": "($overlay == 'ultra') * sum(rate($metric[15s]))", "refId": "D"},
                    {"expr": "($overlay == 'ultra') * avg_over_time(sum(rate($metric[30s]))[2m:30s])", "refId": "E"},
                ],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": [
                    {
                        "matcher": {"id": "byRefId", "options": "C"},
                        "properties": [
                            {"id": "color", "value": {"mode": "fixed", "fixedColor": "semi-dark-yellow"}},
                            {"id": "custom.lineWidth", "value": 2},
                            {"id": "custom.lineStyle", "value": {"dash": [6,3], "fill": "dash"}},
                        ]
                    },
                    {
                        "matcher": {"id": "byRefId", "options": "D"},
                        "properties": [
                            {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}},
                            {"id": "custom.lineWidth", "value": 1},
                            {"id": "custom.lineStyle", "value": {"dash": [2,2], "fill": "dash"}},
                        ]
                    },
                    {
                        "matcher": {"id": "byRefId", "options": "E"},
                        "properties": [
                            {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}},
                            {"id": "custom.lineWidth", "value": 3},
                        ]
                    }
                ]},
                "g6_meta": {"source": "explorer_template", "group": "explorer"},
                "repeat": "metric",
                "repeatDirection": "h",
            },
            {
                "type": "timeseries",
                "title": "$metric rate 1m vs 5m",
                "targets": [
                    {"expr": "sum(rate($metric[1m]))", "refId": "A"},
                    {"expr": "sum(rate($metric[5m]))", "refId": "B"},
                ],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
                "g6_meta": {"source": "explorer_template", "group": "explorer"},
                "repeat": "metric",
                "repeatDirection": "h",
            },
        ]
        ratio_panel = {
            "type": "timeseries",
            "title": "$metric rate ratio 5m/30m",
            "targets": [
                {"expr": "(sum(rate($metric[5m])) / clamp_min(sum(rate($metric[30m])),1))", "refId": "A"},
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
            "fieldConfig": {"defaults": {"unit": "ratio"}, "overrides": []},
            "g6_meta": {"source": "explorer_template", "group": "explorer"},
            "repeat": "metric",
            "repeatDirection": "h",
        }
        cumulative_panel = {
            "type": "timeseries",
            "title": "$metric cumulative total",
            "targets": [
                {"expr": "sum($metric)", "refId": "A"},
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "g6_meta": {"source": "explorer_template", "group": "explorer"},
            "repeat": "metric",
            "repeatDirection": "h",
        }
        # Original (non-compact) keeps cumulative; compact removes it and tightens heights later.
        if plan.slug == "multi_pane_explorer":
            base_panels.extend([ratio_panel, cumulative_panel])
        elif plan.slug == "multi_pane_explorer_compact":
            # compact: drop cumulative, keep ratio; shrink heights
            for bp in base_panels:
                bp["gridPos"]["h"] = 6
            ratio_panel["gridPos"]["h"] = 6
            ratio_panel["gridPos"]["y"] = 6
            base_panels.append(ratio_panel)
        else:  # ultra: drop ratio & cumulative; shrink raw panels further
            for bp in base_panels:
                bp["gridPos"]["h"] = 5
        panels: List[Dict] = base_panels
        # Quantile summary table (single template, repeats over histogram metrics) showing last 5m, last 30m and ratio
        summary_targets = [
            {"expr": "$metric_hist:$q_5m", "refId": "A"},
            {"expr": "$metric_hist:$q_30m", "refId": "B"},
            {"expr": "$metric_hist:$q_ratio_5m_30m", "refId": "C"},
            {"expr": "(($metric_hist:$q_5m - $metric_hist:$q_30m) / clamp_min($metric_hist:$q_30m, 0.001))", "refId": "D"},
        ]
        # Ultra variant folds generic rate ratio & cumulative columns in summary for histogram metrics (approximation)
        if plan.slug == "multi_pane_explorer_ultra":
            summary_targets.append({"expr": "(sum(rate($metric_hist[5m])) / clamp_min(sum(rate($metric_hist[30m])),1))", "refId": "E"})
            summary_targets.append({"expr": "sum($metric_hist)", "refId": "F"})
        summary_panel = {
            "type": "table",
            "title": "$metric_hist $q summary (5m vs 30m)",
            "targets": summary_targets,
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 6, "w": 24, "x": 0, "y": (
                16 if plan.slug == "multi_pane_explorer" else (
                    12 if plan.slug == "multi_pane_explorer_compact" else 5)
            )},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": [
                {
                    "matcher": {"id": "byRefId", "options": "C"},
                    "properties": [
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                            {"color": "green", "value": 0},
                            {"color": "green", "value": 0.8},
                            {"color": "yellow", "value": 1.2},
                            {"color": "red", "value": 1.2000001}
                        ]}},
                        {"id": "unit", "value": "ratio"}
                    ]
                },
                {
                    "matcher": {"id": "byRefId", "options": "D"},
                    "properties": [
                        {"id": "unit", "value": "percentunit"},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": _delta_threshold_steps()}},
                    ]
                },
                {
                    "matcher": {"id": "byRefId", "options": "E"},
                    "properties": [
                        {"id": "unit", "value": "ratio"}
                    ]
                },
                {
                    "matcher": {"id": "byRefId", "options": "F"},
                    "properties": [
                        {"id": "unit", "value": "short"}
                    ]
                },
            ]},
            "options": {"showHeader": True},
            "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "histogram_summary"},
            "repeat": "metric_hist",
            "repeatDirection": "h",
        }
        # Compact variant: add regex-based matcher for any delta-like refIds ending in 'D' to assert override presence
        if plan.slug == "multi_pane_explorer_compact":
            try:
                overrides_list = summary_panel["fieldConfig"]["overrides"]
                # Only add if not already present
                if not any(o.get("matcher",{}).get("options") == ".*D$" for o in overrides_list):
                    overrides_list.append({
                        "matcher": {"id": "byRegexp", "options": ".*D$"},
                        "properties": [
                            {"id": "thresholds", "value": {"mode": "absolute", "steps": _delta_threshold_steps()}},
                            {"id": "unit", "value": "percentunit"}
                        ]
                    })
            except Exception:
                pass
        panels.append(summary_panel)
        # Histogram window comparison panel with anomaly band (only meaningful for histogram metrics)
        panels.append({
            "type": "timeseries",
            "title": "$metric_hist $q 5m vs 30m",
            "targets": [
                {"expr": "$metric_hist:$q_5m", "refId": "A"},
                {"expr": "$metric_hist:$q_30m", "refId": "B"},
                {"expr": f"($metric_hist:$q_30m) * (1 - {band_factor:.6f})", "refId": "C"},
                {"expr": f"($metric_hist:$q_30m) * (1 + {band_factor:.6f})", "refId": "D"},
            ],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": (
                8 if plan.slug == "multi_pane_explorer" else (
                    6 if plan.slug == "multi_pane_explorer_compact" else 11)
                ), "w": 24, "x": 0, "y": (
                    22 if plan.slug == "multi_pane_explorer" else (
                        18 if plan.slug == "multi_pane_explorer_compact" else 11)
                )},
            "fieldConfig": {"defaults": {"unit": "ms"}, "overrides": [
                {"matcher": {"id": "byRefId", "options": "C"}, "properties": [
                    {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}},
                    {"id": "custom.lineStyle", "value": {"dash": [4,4], "fill": "dash"}},
                    {"id": "custom.lineWidth", "value": 1},
                ]},
                {"matcher": {"id": "byRefId", "options": "D"}, "properties": [
                    {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}},
                    {"id": "custom.lineStyle", "value": {"dash": [4,4], "fill": "dash"}},
                    {"id": "custom.lineWidth", "value": 1},
                ]},
            ]},
            "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "histogram_window"},
            "repeat": "metric_hist",
            "repeatDirection": "h",
        })
        # Histogram-aware additional panels (already appended above)
        import hashlib as _hl  # consistent with rest of file
        for p in panels:
            sig = panel_signature(p)
            h = _hl.sha256((plan.slug + sig).encode()).hexdigest()
            p["id"] = int(h[:8], 16)
            meta = p.setdefault("g6_meta", {})
            meta["panel_uuid"] = h[:16]
        # Optional inventory diff quick view: if two snapshot files present in data/ folder
        try:
            _root = Path(__file__).resolve().parent.parent
            snap_new = _root / "data" / "inventory_current.json"
            snap_old = _root / "data" / "inventory_previous.json"
            if snap_new.exists() and snap_old.exists():
                import json as _json
                cur = set(_json.loads(snap_new.read_text()).get("metrics", []))
                prev = set(_json.loads(snap_old.read_text()).get("metrics", []))
                added = sorted(cur - prev)[:50]
                removed = sorted(prev - cur)[:50]
                rows = []
                for a in added:
                    rows.append({"metric": a, "change": "+"})
                for r in removed:
                    rows.append({"metric": r, "change": "-"})
                panels.append({
                    "type": "table",
                    "title": "Inventory Diff (latest vs previous)",
                    "targets": [
                        {"expr": "/* INVENTORY_DIFF */", "refId": "A"},
                    ],
                    "gridPos": {"h": 6, "w": 24, "x": 0, "y": (panels[-1]["gridPos"]["y"] + panels[-1]["gridPos"]["h"])},
                    "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
                    "options": {"showHeader": True},
                    "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "inventory_diff", "added_count": len(added), "removed_count": len(removed)},
                    "transformations": [
                        {"id": "rows", "options": {"rows": rows}}
                    ],
                })
        except Exception:  # pragma: no cover
            pass
        # Alert context integration (optional). Uses Prometheus ALERTS metric; simple filter by alertstate=firing.
        # Ultra variant keeps footprint minimal: skip alerts context panel entirely
        if plan.slug != "multi_pane_explorer_ultra" and not _os.environ.get("G6_EXPLORER_NO_ALERTS"):
            alerts_panel = {
                "type": "table",
                "title": "Active Alerts (firing)",
                "targets": [
                    {"expr": "ALERTS{alertstate='firing'}", "refId": "A"},
                ],
                "datasource": {"type": "prometheus", "uid": "PROM"},
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": (panels[-1]["gridPos"]["y"] + panels[-1]["gridPos"]["h"])} ,
                "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
                "options": {"showHeader": True},
                "g6_meta": {"source": "explorer_template", "group": "explorer", "explorer_kind": "alerts_context"},
            }
            sig = panel_signature(alerts_panel)
            import hashlib as _hl
            h = _hl.sha256((plan.slug + sig).encode()).hexdigest()
            alerts_panel["id"] = int(h[:8], 16)
            alerts_panel["g6_meta"]["panel_uuid"] = h[:16]
            panels.append(alerts_panel)
        # Skip global layout pass for explorer variants; we maintain explicit compact coordinates.
        if plan.slug == "multi_pane_explorer":
            layout_panels(panels)
        generator_version = (
            "phaseDEF-1u" if plan.slug == "multi_pane_explorer_ultra" else (
                "phaseDEF-1c" if plan.slug == "multi_pane_explorer_compact" else "phaseDEF-1")
        )
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
            "templating": {"list": templating_list},
            "time": {"from": "now-6h", "to": "now"},
            "g6_meta": {
                "spec_hash": spec_hash,
                "families": plan.families,
                "placeholder_panels": False,
                "description": plan.description,
                "enriched": True,
                "alerts_panel": False,
                "alerts_count": 0,
                "generator_version": generator_version,
                "explorer": True,
                "metric_kinds": metric_kind_map,
                "compact": (plan.slug == "multi_pane_explorer_compact"),
                "ultra": (plan.slug == "multi_pane_explorer_ultra"),
                "band_pct": band_pct,
            },
        }

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
            # Ensure baseline metadata present (some auto helper returns may already set)
            meta = p.setdefault("g6_meta", {})
            meta.setdefault("metric", metric.name)
            meta.setdefault("family", metric.family)
            meta.setdefault("kind", metric.kind)
            meta.setdefault("source", meta.get("source", "unspecified"))
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

    # Per-group caps (core vs efficiency) applied just before layout. We tag efficiency via g6_meta.group.
    core_panels: List[Dict] = []
    eff_panels: List[Dict] = []
    for p in panels:
        grp = p.get("g6_meta", {}).get("group") if isinstance(p.get("g6_meta"), dict) else None
        if grp == "efficiency":
            eff_panels.append(p)
        else:
            core_panels.append(p)
    # Caps
    CORE_CAP = 24
    EFF_CAP = 12
    truncated = False
    if len(core_panels) > CORE_CAP:
        core_panels = core_panels[:CORE_CAP]
        truncated = True
    if len(eff_panels) > EFF_CAP:
        eff_panels = eff_panels[:EFF_CAP]
        truncated = True
    if truncated:
        print(f"INFO: applied per-group caps core={len(core_panels)} eff={len(eff_panels)} (dashboard={plan.slug})", file=sys.stderr)
    panels = core_panels + eff_panels

    # Insert efficiency header if efficiency panels exist
    if eff_panels:
        header_panel = {
            "type": "table",
            "title": "Efficiency & Latency Diagnostics",
            "targets": [{"expr": "/* GROUP:EFFICIENCY_DIAGNOSTICS */", "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 4, "w": 24, "x": 0, "y": 0},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "g6_meta": {"group_header": True, "group": "efficiency"},
        }
        panels.append(header_panel)

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
            "g6_meta": {"alerts_count": len(alert_rows), "source": "alerts_aggregate"},
        })

    # Stable IDs: hash(slug + signature) -> first 8 hex as int, plus uuid prefix
    import hashlib as _hl
    # Governance rule usage summary (insert before ID assignment so it also gets stable id)
    if plan.slug == "governance":
        # Compute counts excluding existing alerts panel (type table with title 'Spec Alerts Overview') and any prospective summary panel
        rule_ref_patterns = (":p95_", ":p99_", ":p95_ratio_", ":p99_ratio_")
        inline_pattern = "histogram_quantile("
        non_summary_panels = [p for p in panels if not (p.get("title") in {"Spec Alerts Overview", "Recording Rule Usage Summary"})]
        total = sum(1 for p in non_summary_panels if p.get("type") != "table")
        rule_panels = 0
        inline_panels = 0
        for p in non_summary_panels:
            exprs = []
            for t in p.get("targets", []) or []:
                e = t.get("expr")
                if isinstance(e, str):
                    exprs.append(e)
            joined = "\n".join(exprs)
            if any(tok in joined for tok in rule_ref_patterns):
                rule_panels += 1
            if inline_pattern in joined:
                inline_panels += 1
        migrated_denom = rule_panels + inline_panels if (rule_panels + inline_panels) else 1
        migrated_pct = round((rule_panels / migrated_denom) * 100, 1)
        summary_lines = [
            "GOVERNANCE_RULE_USAGE",  # header tag
            f"total_panels={total}",
            f"recording_rule_panels={rule_panels}",
            f"inline_quantile_panels={inline_panels}",
            f"migrated_percent={migrated_pct}",
        ]
        summary_expr = "/*\n" + "\n".join(summary_lines) + "\n*/"
        summary_panel = {
            "type": "table",
            "title": "Recording Rule Usage Summary",
            "targets": [{"expr": summary_expr, "refId": "A"}],
            "datasource": {"type": "prometheus", "uid": "PROM"},
            "gridPos": {"h": 6, "w": 24, "x": 0, "y": 0},
            "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
            "g6_meta": {"rule_usage": True, "migrated_percent": migrated_pct, "source": "governance_summary"},
        }
        # Insert after alerts overview if present, else at start
        insert_index = 1 if panels and panels[0].get("title") == "Spec Alerts Overview" else 0
        panels.insert(insert_index, summary_panel)

    for p in panels:
        sig = panel_signature(p)
        h = _hl.sha256((plan.slug + sig).encode()).hexdigest()
        p["id"] = int(h[:8], 16)
        meta = p.setdefault("g6_meta", {})
        meta["panel_uuid"] = h[:16]

    layout_panels(panels)
    placeholder = all("(auto)" in p.get("title", "") for p in panels if p.get("type") != "table")
    generator_version = "phaseDEF-1"  # bumped after D/E/F enhancements (metadata enrichment & new plans)
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
            "generator_version": generator_version,
        },
    }

# ----------------------------- Manifest ----------------------------- #

def build_manifest(spec_hash: str, dashboards: List[DashboardPlan], built: Dict[str, Dict]) -> Dict:
    import time as _t
    entries = []
    for d in dashboards:
        data = built.get(d.slug, {})
        panel_count = len(data.get("panels", []) or [])
        entries.append({
            "slug": d.slug,
            "uid": f"g6-{d.slug}",
            "families": d.families,
            "panel_count": panel_count,
        })
    return {
        "spec_hash": spec_hash,
        "count": len(dashboards),
        "generated_at_unix": int(_t.time()),
        "dashboards": entries,
    }

# ----------------------------- Main CLI ----------------------------- #

def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate modular Grafana dashboards (scaffold)")
    p.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Output directory for generated dashboards")
    p.add_argument("--dry-run", action="store_true", help="Print plan summary and exit")
    p.add_argument("--verify", action="store_true", help="Fail if existing dashboards differ (drift guard)")
    p.add_argument("--plan", type=Path, help="Optional external plan YAML overriding default plans")
    p.add_argument("--only", type=str, help="Comma-separated list of dashboard slugs to (re)generate; others skipped (still validated for unknown families).")
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
    verbose = os.environ.get("G6_DASHBOARD_DIFF_VERBOSE", "0") == "1"
    detailed: List[str] = []  # optional extended lines printed separately

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
            if verbose:
                # Collect human readable titles
                added_titles = [old_map[sig].get("title") for sig in []]  # placeholder (none)
                added_titles = [new_map[sig].get("title") for sig in added]
                removed_titles = [old_map[sig].get("title") for sig in removed]
                changed_titles = []
                # Re-derive changed titles (those paired earlier)
                for title, old_sig_list in removed_by_title.items():
                    new_sig_list = added_by_title.get(title)
                    if not new_sig_list:
                        continue
                    pairings = min(len(old_sig_list), len(new_sig_list))
                    if pairings:
                        changed_titles.append(title)
                detailed.append(json.dumps({
                    "slug": slug,
                    "changed_titles": changed_titles,
                    "added_titles": added_titles,
                    "removed_titles": removed_titles,
                }, sort_keys=True))
    if verbose and detailed:
        print("DRIFT_DETAILS_BEGIN", file=sys.stderr)
        for line in detailed:
            print(line, file=sys.stderr)
        print("DRIFT_DETAILS_END", file=sys.stderr)
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
    only_set: set[str] | None = None
    if args.only:
        only_set = {s.strip() for s in args.only.split(",") if s.strip()}
        # Validate explicitly requested slugs exist in plan list
        unknown_requested = [s for s in only_set if s not in {p.slug for p in plans}]
        if unknown_requested:
            print(f"ERROR: --only specified unknown dashboard slugs: {', '.join(sorted(unknown_requested))}", file=sys.stderr)
            return 5

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
        if only_set and plan.slug not in only_set:
            continue  # skip generation for non-selected slug
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
    # Manifest always includes all plans with panel counts (0 if skipped under --only)
    manifest = build_manifest(spec_hash, plans, dashboards)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    print(f"Generated {len(dashboards)} dashboards -> {args.output} (spec_hash={spec_hash})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
