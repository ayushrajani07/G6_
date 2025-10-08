#!/usr/bin/env python
"""Validate that every spec-defined panel promql appears in at least one generated dashboard panel.

Rules:
  * Load metrics spec YAML and collect each panel's promql (skip empty / comment-only).
  * Normalize expressions: strip, collapse internal whitespace, remove surrounding comment markers and trailing semicolons.
  * Load all dashboards JSON in grafana/dashboards/generated and collect target exprs normalized.
  * A spec panel is covered if its normalized promql exactly matches a dashboard expr OR if the dashboard expr equals the spec promql after whitespace collapse.
  * Multi-line YAML literals are normalized the same way.

Exit Codes:
  0 -> all spec panel expressions covered
  11 -> uncovered spec panel expressions found
  2 -> setup error (spec or dashboards dir missing)

Options:
  --allow-partial: treat a spec panel as covered if its base metric name appears in any dashboard expression (best-effort fallback)
  --list-missing: print each missing panel expression with context

Intended use: CI gate that ensures generator evolution doesn't silently drop spec-intended panels.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Set

try:
    import yaml  # type: ignore
except ImportError:
    print("PyYAML required for spec coverage validation", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "metrics" / "spec" / "base.yml"
DASH_DIR = ROOT / "grafana" / "dashboards" / "generated"

WHITESPACE_RE = re.compile(r"\s+")

@dataclass
class SpecPanel:
    family: str
    metric: str
    kind: str
    raw_expr: str
    norm_expr: str
    title: str


def normalize_expr(expr: str) -> str:
    if expr is None:
        return ""
    # Remove leading/trailing whitespace and inline comment markers at ends
    cleaned = expr.strip()
    # Collapse multi-line YAML literal indentation
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    # Drop trailing semicolon
    if cleaned.endswith(';'):
        cleaned = cleaned[:-1]
    return cleaned


def load_spec_panels() -> List[SpecPanel]:
    if not SPEC_PATH.exists():
        print(f"Spec missing: {SPEC_PATH}", file=sys.stderr)
        sys.exit(2)
    raw = yaml.safe_load(SPEC_PATH.read_text()) or {}
    out: List[SpecPanel] = []
    for fam, fdata in (raw.get("families", {}) or {}).items():
        for m in (fdata or {}).get("metrics", []) or []:
            if not isinstance(m, dict):
                continue
            metric_name = m.get("name")
            if not metric_name:
                continue
            panels = m.get("panels") or []
            for p in panels:
                expr = p.get("promql")
                if not expr:
                    continue
                norm = normalize_expr(expr)
                if not norm:
                    continue
                out.append(SpecPanel(family=fam, metric=str(metric_name), kind=p.get("kind",""), raw_expr=expr, norm_expr=norm, title=p.get("title","")))
    return out


def load_dashboard_exprs() -> Set[str]:
    if not DASH_DIR.exists():
        print(f"Dashboards dir missing: {DASH_DIR}", file=sys.stderr)
        sys.exit(2)
    exprs: Set[str] = set()
    for fp in DASH_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text())
        except Exception:
            continue
        for panel in data.get("panels", []) or []:
            for tgt in panel.get("targets", []) or []:
                expr = tgt.get("expr")
                if not isinstance(expr, str):
                    continue
                norm = normalize_expr(expr)
                if norm:
                    exprs.add(norm)
    return exprs


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate coverage of spec panel definitions in generated dashboards")
    ap.add_argument("--allow-partial", action="store_true", help="Treat spec panel as covered if metric name appears in any dashboard expression")
    ap.add_argument("--list-missing", action="store_true", help="Print missing spec panel expressions")
    args = ap.parse_args(argv)

    spec_panels = load_spec_panels()
    dash_exprs = load_dashboard_exprs()

    covered = 0
    missing: List[SpecPanel] = []

    for sp in spec_panels:
        if sp.norm_expr in dash_exprs:
            covered += 1
            continue
        if args.allow_partial:
            # partial coverage: look for metric name token in any expr
            if any(sp.metric in e for e in dash_exprs):
                covered += 1
                continue
        missing.append(sp)

    if missing:
        print(f"Spec panel coverage FAILED: {covered}/{len(spec_panels)} covered; missing={len(missing)}", file=sys.stderr)
        if args.list_missing:
            for sp in missing:
                print(f"- {sp.family}.{sp.metric} ({sp.kind}) title='{sp.title}': {sp.norm_expr}")
        return 11

    print(f"Spec panel coverage OK: {covered}/{len(spec_panels)} covered.")
    return 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
