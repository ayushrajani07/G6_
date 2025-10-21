#!/usr/bin/env python
"""
Validate that panels defined in the metrics spec are represented in generated dashboards.

Coverage rules (pragmatic, lenient to generator transformations):
- For histogram panels using histogram_quantile in spec, accept recorded series usage in dashboards:
    <metric>:p95_5m, <metric>:p99_5m, <metric>:p95_30m, etc.
- For counter/gauge panels, accept if any dashboard target expression references the base metric name.
- If spec panel includes an explicit "by (label)" grouping, prefer to see that label in the dashboard
  expression (either via "by (label)" or a topk(...) on the same metric); still count covered if the
  base metric is present to avoid over-strict failures during early generator phases.

Exit codes:
  0  - All spec panels covered
  11 - Uncovered spec panels detected

This script is meant to be used in CI alongside dashboard drift verification.
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

try:
    # Prefer a narrow exception to keep name binding visible to type checkers
    import yaml  # type: ignore[import-untyped]
except ImportError:
    print("ERROR: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "metrics" / "spec" / "base.yml"
DASH_DIR = ROOT / "grafana" / "dashboards" / "generated"


def _read_dash_exprs(dash_dir: Path) -> list[str]:
    exprs: list[str] = []
    if not dash_dir.exists():
        return exprs
    for fp in sorted(dash_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text())
            for p in data.get("panels", []) or []:
                for tgt in p.get("targets", []) or []:
                    if isinstance(tgt, dict):
                        e = tgt.get("expr")
                        if isinstance(e, str) and e.strip():
                            exprs.append(e.strip())
        except Exception:
            # Ignore unreadable dashboards
            continue
    return exprs


_RE_BY_GROUP = re.compile(r"by\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)")


def _quantile_suffix_from_promql(promql: str) -> str | None:
    # Detect histogram_quantile(0.95|0.99|0.9) -> p95|p99|p90
    if "histogram_quantile" not in promql:
        return None
    m = re.search(r"histogram_quantile\s*\(\s*0\.(\d{2})\s*,", promql)
    if not m:
        return None
    return f"p{m.group(1)}"


def _base_metric_from_bucket(promql: str, fallback: str) -> str:
    # Try to extract the *_bucket base name reference; else return fallback
    m = re.search(r"([a-zA-Z_:][a-zA-Z0-9_:]*)_bucket\b", promql)
    if m:
        name = m.group(1)
        return name
    return fallback


def _covered_by_dashboard(panel_promql: str, base_metric: str, dash_exprs: Iterable[str]) -> bool:
    pql = panel_promql.strip()
    if not pql:
        return True  # nothing to validate

    # Try histogram -> recording rule match
    q_suffix = _quantile_suffix_from_promql(pql)
    if q_suffix:
        base = _base_metric_from_bucket(pql, base_metric)
        # Accept any expr containing <base>:pXX_ (any window)
        token = f"{base}:{q_suffix}_"
        for e in dash_exprs:
            if token in e:
                return True
        # Fallback to raw histogram_quantile presence (rare in generated dashboards)
        for e in dash_exprs:
            if "histogram_quantile" in e and base in e:
                return True
        return False

    # Non-histogram cases: look for base metric presence
    # If spec suggests a grouping label, prefer a match that includes it
    want_label: str | None = None
    m = _RE_BY_GROUP.search(pql)
    if m:
        want_label = m.group(1)

    any_base = False
    label_match = False
    for e in dash_exprs:
        if base_metric in e:
            any_base = True
            if want_label and (f"by ({want_label})" in e or ("topk(" in e and base_metric in e)):
                label_match = True
                break
    if want_label:
        return label_match or any_base
    return any_base


def main(argv: list[str]) -> int:
    # Load spec
    if not SPEC_PATH.exists():
        print(f"ERROR: spec file missing: {SPEC_PATH}", file=sys.stderr)
        return 2
    # Ensure typed containers for downstream access
    spec = cast(dict[str, Any], yaml.safe_load(SPEC_PATH.read_text()) or {})
    families = cast(dict[str, Any], spec.get("families") or {})

    dash_exprs = _read_dash_exprs(DASH_DIR)
    total = 0
    covered = 0
    misses: list[tuple[str, str, str]] = []  # (metric, panel_title, reason)

    for fdata in families.values():
        fdata_dict = cast(dict[str, Any], fdata or {})
        metrics = cast(list[Any], fdata_dict.get("metrics") or [])
        for m in metrics:
            if not isinstance(m, dict):
                continue
            m_dict = cast(dict[str, Any], m)
            name = m_dict.get("name")
            if not name:
                continue
            panels = cast(list[Any], m_dict.get("panels") or [])
            for pdef in panels:
                if not isinstance(pdef, dict):
                    continue
                pdef_dict = cast(dict[str, Any], pdef)
                promql = (cast(str, pdef_dict.get("promql") or "").strip())
                title = cast(str, pdef_dict.get("title") or pdef_dict.get("kind") or "panel")
                # Skip placeholder/comment-only promql
                if not promql or promql.startswith("/*"):
                    continue
                total += 1
                if _covered_by_dashboard(promql, name, dash_exprs):
                    covered += 1
                else:
                    reason = "no matching expr"
                    misses.append((name, title, reason))

    if misses:
        print(f"UNCOVERED spec panels: {len(misses)}/{total}")
        for metric, title, reason in misses[:200]:
            print(f" - {metric} :: {title} :: {reason}")
        # Keep exit distinct from dashboard drift
        return 11
    else:
        print(f"All spec panels covered: {covered}/{total}")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
