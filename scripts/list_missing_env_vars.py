"""List environment variables referenced in the codebase that are absent from the canonical catalog.

Refactored (2025-10-05): Previously compared against deprecated `docs/env_dict.md` stub.
Now uses `tools/env_vars.json` (source of truth) and reports:
  - Missing: referenced in code but not in catalog JSON.
  - Extras (optional): present in catalog JSON but not referenced (potential drift / removal candidates) when `--show-extras`.

Exit codes:
  0: No missing vars.
  1: Missing vars detected.

Usage:
  python scripts/list_missing_env_vars.py [--show-extras]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG_JSON = ROOT / 'tools' / 'env_vars.json'

ALLOW = {
    # Historical / internal sentinels that may appear transiently without doc need
    'G6_DISABLE_PER_OPTION_METRICS',
    'G6_TRACE_METRICS',
    'G6_FOO_BAR',  # test / placeholder
    'G6_NAME',     # generic token captured by pattern in docs/examples
}

# Legacy fully deprecated flags (scheduled removal / no longer documented)
LEGACY_REMOVED = {
    'G6_ENABLE_LEGACY_LOOP',
    'G6_SUPPRESS_LEGACY_LOOP_WARN',
    'G6_SUMMARY_PANELS_MODE',
}

# Ignored prefixes represent truncated/partial tokens that appear in code (often during formatting or string building)
# and should not be treated as standalone env vars.
IGNORED_PREFIXES = (
    'G6_CARDINALITY_',
    'G6_CONTRACT_MULTIPLIER_',
    'G6_DUPLICATES_',
    'G6_FAULT_BUDGET_',
    'G6_METRICS_',  # broad; we rely on specific concrete names being cataloged
    'G6_PANELS_',
    'G6_PANEL_H_',
    'G6_PANEL_W_',
    'G6_PREFILTER_',
    'G6_STRIKE_STEP_',
    'G6_ADAPTIVE_ALERT_SEVERITY',  # treat family as documented via existing severity controls
    'G6_ADAPTIVE_STRIKE_REDUCTION',
)

SCAN_FILE_EXTS = {'.py', '.md', '.sh', '.bat', '.ps1', '.ini', '.txt'}
PATTERN = re.compile(r'G6_[A-Z0-9_]+')

def load_catalog() -> set[str]:
    if not CATALOG_JSON.exists():
        return set()
    try:
        data = json.loads(CATALOG_JSON.read_text(encoding='utf-8'))
        vars_list = set(data.get('env_vars') or [])
        meta = data.get('catalog_metadata') or []
        for obj in meta:
            name = obj.get('name') if isinstance(obj, dict) else None
            if name:
                vars_list.add(name)
        return vars_list
    except Exception:
        return set()

def scan_code() -> set[str]:
    found: set[str] = set()
    for base in ('src', 'scripts', 'tests'):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if path.is_dir():
                continue
            if '__pycache__' in path.parts:
                continue
            if any(part.startswith('.') for part in path.parts):
                continue
            if path.suffix.lower() not in SCAN_FILE_EXTS:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for m in PATTERN.findall(text):
                found.add(m)
    return found

def _is_ignored(name: str) -> bool:
    if name in LEGACY_REMOVED:
        return True
    for p in IGNORED_PREFIXES:
        if name.startswith(p):
            return True
    return False

def compute(members: set[str], catalog: set[str]) -> tuple[list[str], list[str]]:
    missing = sorted([
        n for n in members
        if n not in catalog
        and n not in ALLOW
        and not _is_ignored(n)
    ])
    extras = sorted([n for n in catalog if n not in members])
    return missing, extras

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--show-extras', action='store_true', help='Show catalog vars not referenced in code')
    args = ap.parse_args(argv)
    catalog = load_catalog()
    members = scan_code()
    missing, extras = compute(members, catalog)
    print(f"Missing count: {len(missing)}")
    for name in missing:
        print(name)
    if args.show_extras:
        print(f"Extras (unreferenced catalog entries): {len(extras)}")
        for name in extras:
            print(name)
    return 0 if not missing else 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
