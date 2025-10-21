#!/usr/bin/env python
"""Generate suggested Prometheus recording rules from metrics spec.

Heuristics (Phase 1):
    * Counters: create 5m rate and total rate aggregations when labels present.
    * Histograms: create p95 and p99 quantiles if not already covered by existing rules file.
    * Labeled gauges: create topk(5) summary if labels.
    * Always tag job: g6_platform

Outputs a YAML groups block ready to merge or diff.

Modes:
    default (write): writes/overwrites the output file if new suggestions exist.
    --check: generates in-memory and compares with existing file; exits non‑zero (8) if drift.

Exit Codes:
    0 success / up-to-date
    2 spec missing / setup error
    8 drift detected under --check (file content would change)

Future phases: detect existing rules to avoid duplication; build join rules for ratios (e.g., bytes savings) based on panel hints.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "metrics" / "spec" / "base.yml"
OUTPUT_PATH = ROOT / "prometheus_recording_rules_generated.yml"
EXISTING_RULES = ROOT / "prometheus_rules.yml"

class Metric:
    def __init__(self, name: str, kind: str, labels: list[str], family: str) -> None:
        self.name = name
        self.kind = kind
        self.labels = labels
        self.family = family


def load_spec() -> list[Metric]:
    raw = yaml.safe_load(SPEC_PATH.read_text()) or {}
    out: list[Metric] = []
    families: dict[str, Any] = (raw.get("families", {}) or {})
    for fam, data in families.items():
        metrics_list = (data or {}).get("metrics", []) or []
        for m in metrics_list:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            kind = m.get("type")
            labels = m.get("labels") or []
            if name and kind:
                out.append(Metric(str(name), str(kind), list(labels), str(fam)))
    return out


def hash_spec_text(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def existing_record_names() -> set[str]:
    if not EXISTING_RULES.exists():
        return set()
    data = yaml.safe_load(EXISTING_RULES.read_text()) or {}
    names: set[str] = set()
    groups = data.get("groups", []) or []
    for g in groups:
        for r in g.get("rules", []) or []:
            rec = r.get("record")
            if rec:
                names.add(str(rec))
    return names


def synth_rules(metrics: list[Metric], existing: set[str]) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for m in metrics:
        # Counters → rate
        if m.kind == "counter":
            if m.labels:
                rec_base = f"{m.name}:rate_5m"
                if rec_base not in existing:
                    rules.append({
                        "record": rec_base,
                        "expr": f"sum(rate({m.name}[5m])) by ({','.join(m.labels)})",
                        "labels": {"job": "g6_platform"},
                    })
            rec_total = f"{m.name}:total_rate_5m"
            if rec_total not in existing:
                rules.append({
                    "record": rec_total,
                    "expr": f"sum(rate({m.name}[5m]))",
                    "labels": {"job": "g6_platform"},
                })
        # Histograms → quantiles
        if m.kind == "histogram":
            bucket = f"{m.name}_bucket"
            for q in (0.95, 0.99):
                rec = f"{m.name}:p{int(q*100)}_5m"
                if rec in existing:
                    continue
                expr = f"histogram_quantile({q}, sum(rate({bucket}[5m])) by (le))"
                rules.append({
                    "record": rec,
                    "expr": expr,
                    "labels": {"job": "g6_platform"},
                })
            # Additional multi-window p95 & ratio (Phase 7 optimization) only for p95
            # Adds 30m p95 and a 5m/30m ratio rule to reduce repeated dashboard recalculation.
            p95_5m = f"{m.name}:p95_5m"
            p95_30m = f"{m.name}:p95_30m"
            ratio_rec = f"{m.name}:p95_ratio_5m_30m"
            # Only generate if histogram previously had p95 (implicitly) and not already existing
            if m.kind == "histogram":
                if p95_5m not in existing:
                    rules.append({
                        "record": p95_5m,
                        "expr": f"histogram_quantile(0.95, sum(rate({bucket}[5m])) by (le))",
                        "labels": {"job": "g6_platform"},
                    })
                if p95_30m not in existing:
                    rules.append({
                        "record": p95_30m,
                        "expr": f"histogram_quantile(0.95, sum(rate({bucket}[30m])) by (le))",
                        "labels": {"job": "g6_platform"},
                    })
                if ratio_rec not in existing:
                    # Protect denominator with clamp_min to avoid div by zero.
                    rules.append({
                        "record": ratio_rec,
                        "expr": f"{p95_5m} / clamp_min({p95_30m}, 0.001)",
                        "labels": {"job": "g6_platform"},
                    })
            # Per-label (bus) latency quantiles & ratio for bus publish histogram (dimension-preserving)
            if m.name == "g6_bus_publish_latency_ms" and "bus" in m.labels:
                # 5m p95 by bus
                rec_bus_5m = f"{m.name}:p95_5m_by_bus"
                if rec_bus_5m not in existing:
                    rules.append({
                        "record": rec_bus_5m,
                        "expr": f"histogram_quantile(0.95, sum(rate({bucket}[5m])) by (le,bus))",
                        "labels": {"job": "g6_platform"},
                    })
                # 30m p95 by bus
                rec_bus_30m = f"{m.name}:p95_30m_by_bus"
                if rec_bus_30m not in existing:
                    rules.append({
                        "record": rec_bus_30m,
                        "expr": f"histogram_quantile(0.95, sum(rate({bucket}[30m])) by (le,bus))",
                        "labels": {"job": "g6_platform"},
                    })
                # Ratio by bus
                rec_bus_ratio = f"{m.name}:p95_ratio_5m_30m_by_bus"
                if rec_bus_ratio not in existing:
                    rules.append({
                        "record": rec_bus_ratio,
                        "expr": f"{rec_bus_5m} / clamp_min({rec_bus_30m}, 0.001)",
                        "labels": {"job": "g6_platform"},
                    })
        # Gauges with labels → topk summary
        if m.kind == "gauge" and m.labels:
            rec = f"{m.name}:top5"
            if rec not in existing:
                rules.append({
                    "record": rec,
                    "expr": f"topk(5, {m.name})",
                    "labels": {"job": "g6_platform"},
                })
        # Derived backlog efficiency rules (column store): only if backlog gauge & rows counter present in spec
        # We emit them once when we encounter the backlog metric name.
        if m.name == "g6_cs_ingest_backlog_rows":
            # Precondition check for rows counter existing in spec
            has_rows_counter = any(mx.name == "g6_cs_ingest_rows_total" for mx in metrics)
            if has_rows_counter:
                eta_record = "g6_cs_ingest_backlog_rows:eta_minutes"
                burn_record = "g6_cs_ingest_backlog_rows:burn_rows_per_s"
                if eta_record not in existing:
                    rules.append({
                        "record": eta_record,
                        "expr": "(sum(g6_cs_ingest_backlog_rows) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1)) / 60",
                        "labels": {"job": "g6_platform"},
                    })
                if burn_record not in existing:
                    # Positive burn when backlog decreasing (offset 5m – current)/300; clamp at 0
                    rules.append({
                        "record": burn_record,
                        "expr": "clamp_min((sum(g6_cs_ingest_backlog_rows offset 5m) - sum(g6_cs_ingest_backlog_rows)) / 300, 0)",
                        "labels": {"job": "g6_platform"},
                    })
    if not rules:
        return {}
    return {
        "groups": [
            {
                "name": "g6_synth_generated.rules",
                "interval": "30s",
                "rules": rules,
            }
        ]
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate recording rule suggestions")
    ap.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output path for generated recording rules YAML")
    ap.add_argument("--check", action="store_true", help="Do not write; fail (exit 8) if output file content would change")
    args = ap.parse_args(argv)
    if not SPEC_PATH.exists():
        print(f"Spec missing: {SPEC_PATH}", file=sys.stderr)
        return 2
    metrics = load_spec()
    existing = existing_record_names()
    doc = synth_rules(metrics, existing)
    if not doc:
        # Nothing new to propose – treat as up-to-date.
        if args.check:
            # If file exists but we have no suggestions, consider it up-to-date regardless of content.
            print("No new recording rules to suggest (check mode).")
        else:
            print("No new recording rules to suggest.")
        return 0

    new_text = yaml.safe_dump(doc, sort_keys=True)
    if args.check:
        if not args.output.exists():
            print(f"Recording rules drift: {args.output} missing (would create).", file=sys.stderr)
            return 8
        current = args.output.read_text()
        if current.strip() != new_text.strip():
            print("Recording rules drift detected (run without --check to update).", file=sys.stderr)
            return 8
        print("Recording rules up-to-date (check mode).")
        return 0

    # Write mode
    args.output.write_text(new_text)
    print(f"Wrote suggested recording rules -> {args.output}")
    return 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
