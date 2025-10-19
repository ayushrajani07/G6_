#!/usr/bin/env python
"""
Lint Grafana dashboard PromQL expressions using Prometheus promtool.

Behavior:
- Scans generated dashboards under grafana/dashboards/generated and collects all target.expr strings.
- Writes a temporary recording rules file with one rule per expression and runs `promtool check rules` on it.
- Skips non-expressions (empty, comment blocks starting with /*) and de-duplicates expressions.

Exit codes:
    0  -> OK (either lint passed or promtool not found and not required)
    12 -> Lint failed or promtool required but not found

Options:
    --require-promtool  Fail if promtool is not installed or not found in PATH
    --dash-dir PATH     Override dashboards directory (default: grafana/dashboards/generated)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DASH_DIR = ROOT / "grafana" / "dashboards" / "generated"


def _sanitize_templated_expr(expr: str) -> str:
    """Attempt to convert Grafana-templated PromQL into valid PromQL for parsing.

    Strategy:
    - Replace Grafana built-in time vars with fixed durations/numbers.
    - Replace custom variables ($metric, $metric_hist, $q) with concrete placeholders.
    - Neutralize overlay toggles like ($overlay == 'fast') by replacing with 0.
    - Normalize recording rule suffixes like :$q_5m -> :p95_5m.
    This aims for syntactic validity; semantics/data presence are not required for promtool check.
    """
    s = expr
    # Normalize common recording rule suffix patterns first
    s = s.replace(":$q_5m", ":p95_5m")
    s = s.replace(":$q_30m", ":p95_30m")
    s = s.replace(":$q_ratio_5m_30m", ":p95_ratio_5m_30m")
    # Built-in Grafana time variables
    replacements = {
        "$__interval_ms": "60000",
        "$__interval": "1m",
        "$__range_s": "21600",
        "$__range": "6h",
        "$__rate_interval": "5m",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    # Overlay toggles -> 0 constant
    # e.g., ($overlay == 'fast') or ($overlay == "ultra")
    import re as _re
    s = _re.sub(r"\(\s*\$overlay\s*==\s*'[^']*'\s*\)", "0", s)
    s = _re.sub(r'\(\s*\$overlay\s*==\s*\"[^\"]*\"\s*\)', "0", s)
    s = s.replace("$overlay", "0")
    # Collapse scalar boolean combos like (0 or 0) or (0 and 0) to 0
    s = _re.sub(r"\(\s*0\s*or\s*0\s*\)", "0", s, flags=_re.IGNORECASE)
    s = _re.sub(r"\(\s*0\s*and\s*0\s*\)", "0", s, flags=_re.IGNORECASE)
    # Replace metric template vars with concrete names
    s = s.replace("$metric_hist", "g6_bus_publish_latency_ms")
    s = s.replace("$metric", "up")
    s = s.replace("$q", "p95")
    return s


def collect_promql_exprs(
    dash_dir: Path,
    include_templated: bool = False,
    sanitize_templated: bool = False,
) -> list[str]:
    exprs: list[str] = []
    if not dash_dir.exists():
        return exprs
    for fp in sorted(dash_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for panel in data.get("panels", []) or []:
            for tgt in panel.get("targets", []) or []:
                if not isinstance(tgt, dict):
                    continue
                expr = tgt.get("expr")
                if isinstance(expr, str):
                    raw = expr.strip()
                    if not raw:
                        continue
                    if raw.startswith("/*"):  # skip placeholder alert blocks or comments
                        continue
                    # Grafana-templated expressions contain variables like $metric or $__interval.
                    if "$" in raw:
                        if sanitize_templated:
                            exprs.append(_sanitize_templated_expr(raw))
                        elif include_templated:
                            exprs.append(raw)
                        else:
                            continue
                    else:
                        exprs.append(raw)
    # De-duplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for e in exprs:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def write_temp_rules(exprs: list[str]) -> Path:
    # Build a minimal recording rules YAML content
    lines: list[str] = []
    lines.append("groups:")
    lines.append("- name: g6_dashboard_exprs")
    lines.append("  interval: 5m")
    lines.append("  rules:")
    for i, e in enumerate(exprs, start=1):
        # valid Prometheus metric name pattern for 'record'
        record = f"g6_dash_check_{i:04d}"
        lines.append(f"  - record: {record}")
        # Use literal block style to avoid quoting issues
        lines.append("    expr: |-")
        lines.extend([f"      {line}" for line in e.splitlines()])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".yml", prefix="g6_dash_promql_")
    tmp.write("\n".join(lines).encode("utf-8"))
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def run_promtool_check(rules_file: Path, promtool: str) -> int:
    cmd = [promtool, "check", "rules", str(rules_file)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(proc.stdout)
    return proc.returncode


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Lint Grafana dashboard PromQL with promtool")
    ap.add_argument(
        "--require-promtool",
        action="store_true",
        help="Fail if promtool is not found",
    )
    ap.add_argument(
        "--dash-dir",
        type=str,
        default=str(DEFAULT_DASH_DIR),
        help="Dashboards dir (default: grafana/dashboards/generated)",
    )
    ap.add_argument(
        "--promtool",
        type=str,
        help="Path to promtool executable (overrides PATH lookup)",
    )
    ap.add_argument(
        "--include-templated",
        action="store_true",
        help="Include Grafana-templated expressions (may fail promtool parsing)",
    )
    ap.add_argument(
        "--sanitize-templated",
        action="store_true",
        help=(
            "Include templated expressions after sanitizing variables to fixed placeholders"
        ),
    )
    args = ap.parse_args(argv)

    promtool_path = args.promtool or shutil.which("promtool")
    if not promtool_path:
        msg = "promtool not found in PATH; skipping lint"
        if args.require_promtool:
            print("ERROR:", msg, file=sys.stderr)
            return 12
        else:
            print(msg)
            return 0

    dash_dir = Path(args.dash_dir)
    exprs = collect_promql_exprs(
        dash_dir,
        include_templated=args.include_templated or args.sanitize_templated,
        sanitize_templated=args.sanitize_templated,
    )
    if not exprs:
        print("No dashboard PromQL expressions found; nothing to lint")
        return 0

    rules_file = write_temp_rules(exprs)
    try:
        code = run_promtool_check(rules_file, promtool_path)
        if code != 0:
            print(f"PromQL lint failed with exit code {code}")
            return 12
        print(f"PromQL lint OK: {len(exprs)} expressions validated")
        return 0
    finally:
        try:
            os.unlink(rules_file)
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
