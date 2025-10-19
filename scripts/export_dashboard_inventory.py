#!/usr/bin/env python
"""Export dashboard panel inventory for governance / audits.

Reads generated dashboards in grafana/dashboards/generated and emits either CSV or JSONL with fields:
slug,title,metric,source,panel_uuid

Usage:
  python scripts/export_dashboard_inventory.py --out panels.csv --format csv
  python scripts/export_dashboard_inventory.py --format jsonl > panels.jsonl
  python scripts/export_dashboard_inventory.py --filter-source spec,auto_rate

Exit codes:
 0 success
 2 invalid format
 3 no dashboards found
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DASH_DIR = ROOT / "grafana" / "dashboards" / "generated"

FIELDS = ["slug", "title", "metric", "source", "panel_uuid"]

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export dashboard panel inventory")
    p.add_argument("--dir", type=Path, default=DASH_DIR, help="Directory containing generated dashboards")
    p.add_argument("--out", type=Path, help="Output file (omit for stdout)")
    p.add_argument("--format", choices=["csv", "jsonl"], default="csv", help="Output format")
    p.add_argument(
        "--filter-source",
        type=str,
        help="Comma separated list of source values to include (others skipped)",
    )
    return p.parse_args(argv)

def iter_dashboards(path: Path) -> Iterator[dict[str, Any]]:
    for fp in sorted(path.glob("*.json")):
        if fp.name == "manifest.json":
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        slug = fp.stem
        panels = data.get("panels", []) or []
        for p in panels:
            if not isinstance(p, dict):
                continue
            meta = p.get("g6_meta") or {}
            if not isinstance(meta, dict):
                meta = {}
            row: dict[str, Any] = {
                "slug": slug,
                "title": p.get("title"),
                "metric": meta.get("metric"),
                "source": meta.get("source"),
                "panel_uuid": meta.get("panel_uuid"),
            }
            yield row

def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.dir.exists():
        print(f"ERROR: dashboard directory missing: {args.dir}", file=sys.stderr)
        return 3
    rows = list(iter_dashboards(args.dir))
    if not rows:
        print("ERROR: no panels found", file=sys.stderr)
        return 3
    allowed_sources: set[str] | None = None
    if args.filter_source:
        allowed_sources = {s.strip() for s in args.filter_source.split(',') if s.strip()}
        rows = [r for r in rows if r.get('source') in allowed_sources]
    if args.format == "csv":
        out_fh = open(args.out, 'w', newline='', encoding='utf-8') if args.out else sys.stdout
        close_needed = out_fh is not sys.stdout
        try:
            w = csv.DictWriter(out_fh, fieldnames=FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        finally:
            if close_needed:
                out_fh.close()
        return 0
    elif args.format == "jsonl":
        out_fh = open(args.out, 'w', encoding='utf-8') if args.out else sys.stdout
        close_needed = out_fh is not sys.stdout
        try:
            for r in rows:
                out_fh.write(json.dumps(r, sort_keys=True) + "\n")
        finally:
            if close_needed:
                out_fh.close()
        return 0
    else:
        print("ERROR: invalid format", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
