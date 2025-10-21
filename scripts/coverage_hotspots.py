#!/usr/bin/env python3
"""Coverage Hotspots Analyzer.

Parses a Cobertura-style XML coverage report (produced by coverage.py via
```
coverage xml
```
 or pytest --cov + `coverage xml`), ranks modules by *risk* and prints a concise table.

Risk heuristic (initial simple model):
  risk_score = uncovered_lines * (log(total_lines + 1))
This biases toward larger files with large uncovered regions without letting huge
files with modest gaps dominate solely due to size.

Features:
- Rank by risk (default) or by uncovered count.
- Filter by path prefix (e.g., src/) and exclusion regexes (tests, migrations, generated code).
- Optional JSON output for tooling ingestion.
- Supports --top N limit.
- Highlights prospective quick wins (files with coverage < threshold AND total_lines <= small cap).
- Baseline diff: provide previous hotspots JSON via --baseline to compute per-file risk deltas.

Exit Codes:
 0 success
 2 no modules after filtering
 3 parse error / bad input
 5 baseline file load error / invalid JSON structure

 Planned future enhancements (some implemented, some pending):
 - Git churn weighting (recently modified files get multiplier).
 - Complexity weighting via radon (cyclomatic complexity * uncovered lines).
 - Historical trend diff (compare with previous XML baseline) (partially covered by --baseline risk delta).

Usage examples:
  python scripts/coverage_hotspots.py --xml coverage.xml --prefix src/ --top 20
  python scripts/coverage_hotspots.py --xml coverage.xml --json --min-lines 20 --max-file-lines 800
  coverage xml && python scripts/coverage_hotspots.py -p src/ -e 'generated|_deprecated' -t 30
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class ModuleCov:
    name: str
    lines_total: int
    lines_covered: int
    lines_uncovered: int
    coverage_pct: float
    risk: float

def parse_cobertura(xml_path: str, *, prefix: str | None=None, exclude: Sequence[str]=()) -> list[ModuleCov]:
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        raise RuntimeError(f"failed parsing coverage XML: {e}") from e
    root = tree.getroot()
    modules: list[ModuleCov] = []
    # Cobertura: <packages><package><classes><class filename="..." line-rate="...">
    for cls in root.findall('.//class'):
        filename = cls.get('filename') or ''
        if prefix and not filename.startswith(prefix):
            continue
        skip = False
        for pat in exclude:
            if pat and re.search(pat, filename):
                skip = True
                break
        if skip:
            continue
        # Aggregate via lines list (line elements contain hits) if available; fallback to attributes
        lines = cls.findall('.//line')
        covered = 0
        missed = 0
        if lines:
            for ln in lines:
                try:
                    hits = int(ln.get('hits') or '0')
                except ValueError:
                    hits = 0
                if hits > 0:
                    covered += 1
                else:
                    missed += 1
            total = covered + missed
        else:
            # Fallback: derive from line-rate if present (rough)
            try:
                rate = float(cls.get('line-rate') or '0')
            except ValueError:
                rate = 0.0
            # Heuristic: skip if no explicit lines (probably synthetic)
            if rate <= 0:
                continue
            total = int(rate * 1000)  # arbitrary scaling; not ideal
            covered = int(total * rate)
            missed = total - covered
        if total == 0:
            continue
        pct = (covered / total) * 100.0
        risk = missed * math.log(total + 1)
        modules.append(ModuleCov(filename, total, covered, missed, pct, risk))
    return modules

def format_table(mods: list[ModuleCov], *, top: int, quick_win_max_lines: int, quick_win_threshold: float,
                 baseline: dict[str, float] | None = None) -> str:
    has_baseline = baseline is not None
    head_cols = [f"{'Rank':>4}", f"{'File':<55}", f"{'Tot':>5}", f"{'Miss':>5}", f"{'Cov%':>6}", f"{'Risk':>8}"]
    if has_baseline:
        head_cols.append(f"{'ΔRisk':>8}")
    head_cols.append(f"{'QuickWin':>8}")
    head = '  '.join(head_cols)
    lines = [head, '-'*len(head)]
    for i,m in enumerate(mods[:top], start=1):
        quick = (m.coverage_pct < quick_win_threshold and m.lines_total <= quick_win_max_lines)
        flag = 'Y' if quick else ''
        row = [f"{i:>4}", f"{m.name[:55]:<55}", f"{m.lines_total:>5}", f"{m.lines_uncovered:>5}", f"{m.coverage_pct:>6.1f}", f"{m.risk:>8.1f}"]
        if has_baseline:
            base_risk = baseline.get(m.name) if baseline else None
            if base_risk is not None:
                delta = m.risk - base_risk
                row.append(f"{delta:>8.1f}")
            else:
                row.append(f"{'-':>8}")
        row.append(f"{flag:>8}")
        lines.append('  '.join(row))
    return '\n'.join(lines)

def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description='Analyze coverage hotspots from Cobertura XML')
    ap.add_argument('--xml', default='coverage.xml', help='Path to coverage XML (default coverage.xml)')
    ap.add_argument('-p','--prefix', default='src/', help='Only include files starting with this prefix (default src/)')
    ap.add_argument('-e','--exclude', action='append', default=[], help='Regex pattern to exclude (can repeat)')
    ap.add_argument('--top', type=int, default=25, help='Show top N modules (default 25)')
    ap.add_argument('--sort', choices=['risk','miss'], default='risk', help='Primary sort key (risk or miss)')
    ap.add_argument('--min-lines', type=int, default=10, help='Ignore modules smaller than this line count (default 10)')
    ap.add_argument('--max-file-lines', type=int, default=5000, help='Ignore extremely large auto-generated modules above this line count (default 5000)')
    ap.add_argument('--quick-win-threshold', type=float, default=65.0, help='Coverage %% below which a file is considered for quick win flag (default 65)')
    ap.add_argument('--quick-win-max-lines', type=int, default=220, help='Maximum total lines for quick win candidates (default 220)')
    ap.add_argument('--json', action='store_true', help='Emit JSON instead of table')
    ap.add_argument('--baseline', help='Path to previous hotspots JSON (from --json output) to compute risk deltas')
    ap.add_argument('--fail-under', type=float, default=None, help='If set, exit with code 4 if any module below this coverage %% (stricter gating than global fail_under)')
    args = ap.parse_args(argv)

    modules = parse_cobertura(args.xml, prefix=args.prefix, exclude=args.exclude)
    if not modules:
        print('No modules after prefix/exclude filtering', file=sys.stderr)
        return 2
    # Size filtering
    modules = [m for m in modules if m.lines_total >= args.min_lines and m.lines_total <= args.max_file_lines]
    if not modules:
        print('No modules after size filtering', file=sys.stderr)
        return 2
    # Sorting
    if args.sort == 'risk':
        modules.sort(key=lambda m: (-m.risk, m.coverage_pct, m.lines_total))
    else:
        modules.sort(key=lambda m: (-m.lines_uncovered, m.coverage_pct, m.lines_total))

    # Load baseline if requested (best-effort; on failure exit code 5)
    baseline_map: dict[str, float] | None = None
    if args.baseline:
        try:
            with open(args.baseline, encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, dict) and 'modules' in data and isinstance(data['modules'], list):
                baseline_map = {}
                for entry in data['modules']:
                    if isinstance(entry, dict):
                        fname = entry.get('file')
                        br = entry.get('risk')
                        if isinstance(fname, str) and isinstance(br, (int, float)):
                            baseline_map[fname] = float(br)
            else:
                print('Invalid baseline JSON structure (missing modules list)', file=sys.stderr)
                return 5
        except FileNotFoundError:
            print(f'Baseline file not found: {args.baseline}', file=sys.stderr)
            return 5
        except json.JSONDecodeError as e:
            print(f'Failed to parse baseline JSON: {e}', file=sys.stderr)
            return 5
        except Exception as e:  # pragma: no cover (unexpected)
            print(f'Unexpected baseline load error: {e}', file=sys.stderr)
            return 5

    if args.json:
        out: list[dict[str,Any]] = []
        for m in modules[:args.top]:
            base_risk = baseline_map.get(m.name) if baseline_map else None
            risk_delta = None
            if base_risk is not None:
                risk_delta = round(m.risk - base_risk, 2)
            out.append({
                'file': m.name,
                'lines_total': m.lines_total,
                'lines_uncovered': m.lines_uncovered,
                'coverage_pct': round(m.coverage_pct,2),
                'risk': round(m.risk,2),
                'quick_win': (m.coverage_pct < args.quick_win_threshold and m.lines_total <= args.quick_win_max_lines),
                **({'baseline_risk': round(base_risk,2), 'risk_delta': risk_delta} if base_risk is not None else {})
            })
        payload = { 'modules': out, 'total_considered': len(modules) }
        print(json.dumps(payload, indent=2))
    else:
        table = format_table(modules, top=args.top, quick_win_max_lines=args.quick_win_max_lines, quick_win_threshold=args.quick_win_threshold, baseline=baseline_map)
        print(table)
    if args.fail_under is not None:
        low = [m for m in modules if m.coverage_pct < args.fail_under]
        if low:
            return 4
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
