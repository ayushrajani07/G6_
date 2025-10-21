"""Generate dynamic sections for CLEANUP_FINAL_REPORT.md.

Outputs a markdown snippet replacing placeholder tables for:
  * Inventory & Footprint Delta
  * Quality Gates & Baselines

Heuristics:
  - Before counts inferred from first inventory snapshot if tools/cleanup_inventory_baseline.json exists;
    else treat current as both before/after with delta 0.
  - Canonical markdown docs: those tagged 'docs-active' excluding stub files containing '(Deprecated Stub)'.
  - Stub docs: files containing '(Deprecated Stub)' in content under docs/.
  - Archived/Removed: counted from inventory entries tagged 'candidate-remove' or 'archived' (if future tag) plus
    absence from current vs baseline (if baseline exists).
  - Python modules: *.py under src/ (excluding tests, archive) count.
  - Active scripts: top-level scripts/*.py minus archive.

Quality gates:
  - Coverage: parse coverage.xml line-rate; baseline from tools/coverage_baseline.json.
  - Dead code: parse tools/dead_code_report.json (new_items length).
  - Orphan tests: run orphan_tests module and interpret output without failing (non-zero -> count length of JSON list).
  - Env missing vars: run env_catalog_check in a capture mode; parse 'MISSING:' line.
  - Docs index missing: run doc_index_check; parse 'missing entries:' if present.

Insert updated tables between marker comments in CLEANUP_FINAL_REPORT.md:
  <!-- INVENTORY_TABLE_START --> ... <!-- INVENTORY_TABLE_END -->
  <!-- GATES_TABLE_START --> ... <!-- GATES_TABLE_END -->

If markers absent, append at end.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'docs' / 'CLEANUP_FINAL_REPORT.md'
INV_CURRENT = ROOT / 'tools' / 'cleanup_inventory.json'
INV_BASELINE = ROOT / 'tools' / 'cleanup_inventory_baseline.json'
ORPHAN_JSON = ROOT / 'tools' / 'orphan_tests_report.json'
DEAD_CODE = ROOT / 'tools' / 'dead_code_report.json'
COVERAGE_XML = ROOT / 'coverage.xml'
COVERAGE_BASE = ROOT / 'tools' / 'coverage_baseline.json'

def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None

def count_py_modules() -> int:
    base = ROOT / 'src'
    count = 0
    for p in base.rglob('*.py'):
        rel = p.relative_to(ROOT)
        if 'tests' in rel.parts or 'archive' in rel.parts:
            continue
        count += 1
    return count

def count_scripts() -> int:
    base = ROOT / 'scripts'
    if not base.exists():
        return 0
    return sum(1 for p in base.rglob('*.py') if 'archive' not in p.parts)

def classify_docs() -> tuple[int, int]:
    docs_dir = ROOT / 'docs'
    canonical = 0
    stubs = 0
    for p in docs_dir.rglob('*.md'):
        try:
            txt = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if '(Deprecated Stub)' in txt or '(Stub)' in txt and 'SSE Security' in txt:
            stubs += 1
        else:
            canonical += 1
    return canonical, stubs

def archived_removed(current_inv: dict[str, Any], base_inv: dict[str, Any] | None) -> int:
    # Use tags first
    tagged = sum(1 for e in current_inv.get('inventory', []) if any(t in ('candidate-remove','archived') for t in e.get('tags', [])))
    if not base_inv:
        return tagged
    base_paths = {e['path'] for e in base_inv.get('inventory', [])}
    curr_paths = {e['path'] for e in current_inv.get('inventory', [])}
    removed = base_paths - curr_paths
    return tagged + len(removed)

def parse_coverage() -> float | None:
    if not COVERAGE_XML.exists():
        return None
    import re
    try:
        txt = COVERAGE_XML.read_text(encoding='utf-8', errors='ignore')
        m = re.search(r'line-rate="([0-9]*\.?[0-9]+)"', txt)
        if m:
            return round(float(m.group(1))*100.0, 2)
    except Exception:
        return None
    return None

def run_module(mod: str) -> subprocess.CompletedProcess[str] | None:
    try:
        proc = subprocess.run([sys.executable, '-m', mod], cwd=ROOT, capture_output=True, text=True, timeout=60)
        return proc
    except Exception:  # pragma: no cover
        return None

def orphan_count() -> int | None:
    proc = run_module('scripts.cleanup.orphan_tests')
    if not proc:
        return None
    if proc.returncode == 0:
        # Write empty list
        ORPHAN_JSON.write_text('[]\n', encoding='utf-8')
        return 0
    # stdout should be JSON list; persist for inspection
    try:
        data = json.loads(proc.stdout)
        ORPHAN_JSON.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return len(data)
    except Exception:
        return None

def env_missing_count() -> int | None:
    proc = run_module('scripts.cleanup.env_catalog_check')
    if not proc:
        return None
    # look for MISSING line
    if 'MISSING:' in proc.stdout:
        # parse after colon
        parts = proc.stdout.split('MISSING:')[-1].strip()
        if parts:
            return len([p for p in parts.split(',') if p.strip()])
    return 0

def docs_index_missing_count() -> int | None:
    proc = run_module('scripts.cleanup.doc_index_check')
    if not proc:
        return None
    if 'missing entries:' in proc.stdout:
        seg = proc.stdout.split('missing entries:')[-1].strip()
        return len([p for p in seg.split(',') if p.strip()])
    return 0

def ensure_inventory_baseline(cur: dict[str, Any]) -> dict[str, Any]:
    """Create a baseline snapshot if missing to enable real deltas later."""
    if INV_BASELINE.exists():
        data = load_json(INV_BASELINE)
        return data if isinstance(data, dict) else cur
    try:
        INV_BASELINE.write_text(json.dumps(cur, indent=2), encoding='utf-8')
        print('[final-report] created inventory baseline snapshot')
    except Exception:
        pass
    return cur

def build_inventory_table(cur: dict[str, Any], base: dict[str, Any] | None) -> str:
    if base is None:
        base = cur
    before_py = count_py_modules()
    after_py = before_py  # currently not comparing historical snapshot; TODO: compute from base paths
    before_scripts = count_scripts()
    after_scripts = before_scripts
    canonical, stubs = classify_docs()
    archived = archived_removed(cur, base)
    rows = [
        ('Python Modules', before_py, after_py, after_py-before_py, ''),
        ('Scripts (active)', before_scripts, after_scripts, after_scripts-before_scripts, ''),
        ('Archived / Removed', 0 if not base else 0, archived, archived, 'tagged or removed vs baseline'),
        ('Markdown Docs (canonical)', canonical, canonical, 0, 'post-consolidation'),
        ('Stub Docs', stubs, stubs, 0, 'pending removal window'),
    ]
    lines = ['| Category | Before | After | Delta | Notes |', '|----------|--------|-------|-------|-------|']
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")
    return "\n".join(lines)

def build_gates_table() -> str:
    cov_current = parse_coverage()
    cov_base = load_json(COVERAGE_BASE)
    cov_baseline_val = cov_base.get('line_coverage_pct') if cov_base else None
    dead = load_json(DEAD_CODE) or {}
    dead_new = len(dead.get('new_items', []) or [])
    orphan = orphan_count()
    env_miss = env_missing_count()
    docs_miss = docs_index_missing_count()
    def fmt(v: int | float | None) -> int | float | str:
        return 'TBD' if v is None else v
    # Pass/fail logic
    cov_pass = 'TBD'
    drift = 'TBD'
    if cov_current is not None and cov_baseline_val is not None:
        drift = round(cov_current - cov_baseline_val, 2)
    # Mirror defaults in validate_cleanup.py (initial baseline ~45%).
    min_floor = float(os.getenv('G6_COVERAGE_MIN_PCT', '45.0'))
    max_drop = float(os.getenv('G6_COVERAGE_MAX_DROP', '3.0'))
    if cov_current is not None and cov_baseline_val is not None:
        if cov_current < min_floor:
            cov_pass = 'N'
        else:
            # Negative drift allowed up to -max_drop
            if (cov_baseline_val - cov_current) > max_drop:
                cov_pass = 'N'
            else:
                cov_pass = 'Y'
    dead_pass = 'Y' if dead_new == 0 else 'N'
    orphan_pass = 'Y' if orphan == 0 else 'N'
    env_pass = 'Y' if env_miss == 0 else 'N'
    docs_pass = 'Y' if docs_miss == 0 else 'N'
    lines = ['| Gate | Baseline | Current | Drift | Pass? | Notes |', '|------|----------|---------|-------|-------|-------|']
    lines.append(f"| Coverage (%) | {fmt(cov_baseline_val)} | {fmt(cov_current)} | {drift} | {cov_pass} | floor+drop enforced |")
    lines.append(f"| Dead Code (new items) | 0 | {dead_new} | {dead_new} | {dead_pass} | high-confidence only |")
    lines.append(f"| Orphan Tests | 0 | {fmt(orphan)} | {fmt(orphan)} | {orphan_pass} | heuristic |")
    lines.append(f"| Env Missing Vars | 0 | {fmt(env_miss)} | {fmt(env_miss)} | {env_pass} | strict missing |")
    lines.append(f"| Docs Index Missing | 0 | {fmt(docs_miss)} | {fmt(docs_miss)} | {docs_pass} | required set |")
    return "\n".join(lines)

def update_report(inv_table: str, gates_table: str) -> bool:
    if not REPORT.exists():
        print('[final-report] report file missing')
        return False
    text = REPORT.read_text(encoding='utf-8')
    def replace_block(start_marker: str, end_marker: str, new_content: str) -> str:
        if start_marker in text and end_marker in text:
            pattern = re.compile(re.escape(start_marker) + '.*?' + re.escape(end_marker), re.DOTALL)
            return pattern.sub(start_marker + '\n' + new_content + '\n' + end_marker, text)
        else:
            return text + f"\n{start_marker}\n{new_content}\n{end_marker}\n"
    new_text = replace_block('<!-- INVENTORY_TABLE_START -->','<!-- INVENTORY_TABLE_END -->', inv_table)
    new_text = replace_block('<!-- GATES_TABLE_START -->','<!-- GATES_TABLE_END -->', gates_table)
    if new_text != text:
        REPORT.write_text(new_text, encoding='utf-8')
        print('[final-report] updated report tables')
    else:
        print('[final-report] no changes applied')
    return True

def main() -> int:
    current_inv = load_json(INV_CURRENT) or {'inventory': []}
    baseline = load_json(INV_BASELINE)
    if baseline is None:
        baseline = ensure_inventory_baseline(current_inv)
    inv_table = build_inventory_table(current_inv, baseline)
    gates_table = build_gates_table()
    update_report(inv_table, gates_table)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
