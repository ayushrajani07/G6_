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
from typing import Dict, List

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "metrics" / "spec" / "base.yml"
OUTPUT_PATH = ROOT / "prometheus_recording_rules_generated.yml"
EXISTING_RULES = ROOT / "prometheus_rules.yml"

class Metric:
    def __init__(self, name: str, kind: str, labels: List[str], family: str):
        self.name = name
        self.kind = kind
        self.labels = labels
        self.family = family


def load_spec() -> List[Metric]:
    raw = yaml.safe_load(SPEC_PATH.read_text()) or {}
    out: List[Metric] = []
    for fam, data in (raw.get("families", {}) or {}).items():
        for m in (data or {}).get("metrics", []) or []:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            kind = m.get("type")
            labels = m.get("labels") or []
            if name and kind:
                out.append(Metric(name, kind, labels, fam))
    return out


def hash_spec_text(paths: List[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def existing_record_names() -> set:
    if not EXISTING_RULES.exists():
        return set()
    data = yaml.safe_load(EXISTING_RULES.read_text()) or {}
    names = set()
    for g in data.get("groups", []) or []:
        for r in g.get("rules", []) or []:
            rec = r.get("record")
            if rec:
                names.add(rec)
    return names


def synth_rules(metrics: List[Metric], existing: set) -> Dict:
    rules: List[Dict] = []
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
        # Gauges with labels → topk summary
        if m.kind == "gauge" and m.labels:
            rec = f"{m.name}:top5"
            if rec not in existing:
                rules.append({
                    "record": rec,
                    "expr": f"topk(5, {m.name})",
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


def main(argv: List[str]) -> int:
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
