#!/usr/bin/env python
"""Audit generated dashboards for inline histogram_quantile uses that should be replaced by recording rules.

Rules:
  * If a panel target expr contains `histogram_quantile(` with a 5m or 30m rate window on a *_bucket metric
    AND a corresponding recording rule (<base>:p95_5m, <base>:p95_30m, <base>:p95_ratio_5m_30m or p99 variant) exists
    THEN flag as violation (we prefer recorded series for consistency & lower query cost).
    * Allowlist: governance dashboard may keep one raw quantile per histogram for validation.
        Limit to at most 1 per metric & window set.

Exit codes:
  0 -> success (no violations)
  10 -> violations found
  2 -> setup error (missing dirs/files)

Future extension: detect raw ratio expressions dividing two histogram_quantile calls that have a ratio recording rule.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DASH_DIR = ROOT / "grafana" / "dashboards" / "generated"
RULES_GEN = ROOT / "prometheus_recording_rules_generated.yml"

# Regex to match histogram_quantile(0.95, sum by (le[,labels]*) (rate(metric_bucket[5m])))
# Use single quotes for the Python string to avoid escaping quotes inside the regex.
HQ_PATTERN = re.compile(r'histogram_quantile\s*\(\s*(0\.95|0\.99)\s*,[^)]*?rate\([^\[]+\[(5m|30m)\]\)\)\)')
BUCKET_EXTRACT = re.compile(r'rate\((?P<metric>[a-zA-Z0-9_:]+)_bucket\[(5m|30m)\]\)')

# Minimal YAML loader (avoid PyYAML dependency if not already present)
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def load_recording_rules() -> set[str]:
    recs: set[str] = set()
    if not RULES_GEN.exists() or not yaml:
        return recs
    data: dict[str, Any] = yaml.safe_load(RULES_GEN.read_text()) or {}
    for g in data.get("groups", []) or []:
        for r in g.get("rules", []) or []:
            name = r.get("record")
            if name:
                recs.add(name)
    return recs


def scan_dashboards(recording_rules: set[str]) -> list[dict]:
    if not DASH_DIR.exists():
        raise SystemExit(2)
    violations: list[dict] = []
    allow_gov_limit: dict[str, int] = {}  # metric -> count of raw quantiles allowed in governance
    for fp in DASH_DIR.glob("*.json"):
        data = json.loads(fp.read_text())
        slug = fp.stem
        panels = data.get("panels", [])
        for panel in panels:
            targets = panel.get("targets", [])
            for tgt in targets:
                expr = tgt.get("expr") or ""
                if "histogram_quantile" not in expr:
                    continue
                m = HQ_PATTERN.search(expr)
                if not m:
                    continue
                # extract base metric
                bmatch = BUCKET_EXTRACT.search(expr)
                if not bmatch:
                    continue
                base_metric = bmatch.group("metric")
                # window = m.group(2) if len(m.groups()) >= 2 else None
                # compute expected rule names to justify replacement
                expected = {f"{base_metric}:p95_5m", f"{base_metric}:p95_30m", f"{base_metric}:p95_ratio_5m_30m",
                            f"{base_metric}:p99_5m"}
                if expected & recording_rules:
                    # governance exception: allow one raw p95 AND one raw p99 per base metric (any window) total
                    if slug == "governance":
                        allow = allow_gov_limit.get(base_metric, 0)
                        if allow < 2:  # p95 + p99
                            allow_gov_limit[base_metric] = allow + 1
                            continue
                    violations.append({
                        "dashboard": slug,
                        "panel_title": panel.get("title"),
                        "expr": expr,
                        "suggest": f"Replace with recording rule: {base_metric}:p95_5m / :p95_30m etc.",
                    })
    return violations


def main(argv: list[str]) -> int:
    recs = load_recording_rules()
    violations = scan_dashboards(recs)
    if violations:
        print("Quantile audit violations (inline histogram_quantile where recording rule exists):")
        for v in violations:
            print(f"- {v['dashboard']} | {v['panel_title']}: {v['expr']} -> {v['suggest']}")
        return 10
    print("Quantile audit passed: no inline histogram_quantile panels requiring migration.")
    return 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
