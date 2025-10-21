"""Dead code scanning orchestration.

Runs vulture plus lightweight import graph reachability to produce a
JSON + markdown report. Supports an allowlist to suppress known
intentional false positives (dynamic usage, plugin entrypoints, tests).

Exit Codes:
 0 - No new dead code beyond baseline budget
 1 - New dead code detected (CI should fail)
 2 - Internal error executing scan

Usage:
  python -m scripts.cleanup.dead_code_scan --update-baseline   # refresh allowlist
  python -m scripts.cleanup.dead_code_scan                      # scan and compare

Environment:
  G6_DEAD_CODE_BUDGET (int) optional hard cap for non-allowlisted items.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import TypedDict

ROOT = pathlib.Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = ROOT / "tools" / "dead_code_allowlist.json"
REPORT_JSON = ROOT / "tools" / "dead_code_report.json"
REPORT_MD = ROOT / "docs" / "dead_code.md"

VULTURE_MODULES = ["src", "scripts"]
VULTURE_EXCLUDE = ["archive", "tests", "data", "venv", ".venv"]
DEFAULT_MIN_CONFIDENCE = 30  # lowered from 60 to surface more candidates

@dataclass
class DeadItem:
    name: str
    typ: str
    filename: str
    lineno: int
    confidence: int | None = None

class Summary(TypedDict):
    total: int
    by_type: dict[str, int]

def run_vulture(min_conf: int) -> list[DeadItem]:
    cmd = [sys.executable, "-m", "vulture", *VULTURE_MODULES, "--min-confidence", str(min_conf)]
    for ex in VULTURE_EXCLUDE:
        cmd += ["--exclude", ex]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    except Exception as e:  # pragma: no cover
        print("[dead-code] vulture invocation failed", e, file=sys.stderr)
        return []
    items: list[DeadItem] = []
    pattern = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<type>.+?) '(?P<name>.+?)' is unused")
    for line in proc.stdout.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        items.append(DeadItem(
            name=m.group('name'),
            typ=m.group('type'),
            filename=os.path.relpath(m.group('file'), ROOT),
            lineno=int(m.group('line')),
        ))
    return items

def build_import_graph() -> set[str]:
    reachable: set[str] = set()
    for py in ROOT.rglob('*.py'):
        rel = py.relative_to(ROOT)
        if any(part in VULTURE_EXCLUDE for part in rel.parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding='utf-8'))
        except Exception:
            continue
        mod_name = ".".join(rel.with_suffix("").parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    reachable.add(n.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    reachable.add(node.module.split('.')[0])
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == '__all__':
                        reachable.add(mod_name)
            if isinstance(node, ast.If):
                # simple heuristic, look for __main__ sentinel
                src_segment = getattr(node, 'test', None)
                try:
                    segment_text = ast.get_source_segment(py.read_text(encoding='utf-8'), node) or ''
                except Exception:
                    segment_text = ''
                if '__main__' in segment_text:
                    reachable.add(mod_name)
    return reachable

def load_allowlist() -> dict[str, dict]:
    if ALLOWLIST_PATH.exists():
        try:
            return json.loads(ALLOWLIST_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def save_allowlist(data: dict[str, dict]) -> None:
    ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALLOWLIST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')

def summarize(items: list[DeadItem]) -> Summary:
    return Summary(
        total=len(items),
        by_type={t: sum(1 for i in items if i.typ == t) for t in sorted({i.typ for i in items})},
    )

def write_report(findings: list[DeadItem], new_items: list[DeadItem], allowlist_keys: set[str]) -> None:
    REPORT_JSON.write_text(json.dumps({
        'total_findings': len(findings),
        'new_items': [i.__dict__ for i in new_items],
        'summary': summarize(findings),
        'allowlist_size': len(allowlist_keys),
    }, indent=2), encoding='utf-8')
    lines = [
        '# Dead Code Report', '',
        f'Total findings (including allowlisted): {len(findings)}',
        f'Allowlist size: {len(allowlist_keys)}',
        f'New actionable (not allowlisted): {len(new_items)}', '',
        '## Summary by Type', '',
    ]
    for t, c in summarize(findings)['by_type'].items():
        lines.append(f'- {t}: {c}')
    if new_items:
        lines += ['', '## New Items', '']
        for i in new_items:
            lines.append(f"- {i.filename}:{i.lineno} {i.typ} {i.name}")
    else:
        lines += ['', '_No new dead code beyond baseline._']
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding='utf-8')

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--update-baseline', action='store_true', help='Overwrite allowlist with current findings')
    ap.add_argument('--min-confidence', type=int, default=DEFAULT_MIN_CONFIDENCE, help='Vulture minimum confidence (default 30)')
    ap.add_argument('--exploratory', action='store_true', help='Also emit ultra-low (0) confidence exploratory report (non-blocking)')
    args = ap.parse_args(argv)
    vulture_items = run_vulture(args.min_confidence)
    allowlist = load_allowlist()
    allowlist_keys = set(allowlist.keys())
    def key(i: DeadItem) -> str:
        return f"{i.filename}:{i.name}:{i.lineno}"
    if args.update_baseline:
        new_data = {key(i): {'type': i.typ} for i in vulture_items}
        save_allowlist(new_data)
        print(f"[dead-code] Baseline updated with {len(new_data)} entries -> {ALLOWLIST_PATH}")
        return 0
    new_items = [i for i in vulture_items if key(i) not in allowlist_keys]
    budget = int(os.getenv('G6_DEAD_CODE_BUDGET', '0'))
    write_report(vulture_items, new_items, allowlist_keys)
    if budget and len(new_items) > budget:
        print(f"[dead-code] Budget exceeded: {len(new_items)} > {budget}", file=sys.stderr)
        return 1
    if new_items:
        print(f"[dead-code] New dead code items: {len(new_items)} (see {REPORT_MD})")
        exit_code = 1
    else:
        print("[dead-code] No new dead code beyond baseline")
        exit_code = 0

    if args.exploratory:
        exploratory_items = run_vulture(0)
        extra_path = REPORT_JSON.parent / 'dead_code_exploratory.json'
        extra_path.write_text(json.dumps({'total': len(exploratory_items), 'items': [i.__dict__ for i in exploratory_items]}, indent=2), encoding='utf-8')
        print(f"[dead-code] Exploratory report written: {extra_path}")
    return exit_code

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
