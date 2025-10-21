"""Validate that referenced environment variables in code are present in the catalog.

Scan *.py under src/ and scripts/ for os.getenv()/os.environ[] usage and compare
to `tools/env_vars.json` (expected schema with key `env_vars`: list[str] or list[objects]).

Exit codes:
 0 OK
 1 Missing vars (referenced in code but absent from catalog)
 2 Catalog stale (vars in catalog not referenced anymore) if strict mode

Env Vars:
  G6_ENV_CATALOG_STRICT=1  -> treat stale entries as failure
  G6_ENV_CATALOG_ALLOW_PREFIXES=CSV of prefixes to ignore during comparison
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'tools' / 'env_vars.json'
GETENV_RE = re.compile(r'os\.getenv\(\s*["\']([A-Z0-9_]+)["\']')
ENV_INDEX_RE = re.compile(r'os\.environ\[\s*["\']([A-Z0-9_]+)["\']')

# Ignore policy (v1): Only strictly govern internal G6_ variables.
# Suppress noise from system/CI/test framework vars and external provider/storage secrets.
SYSTEM_IGNORE_NAMES = { 'TERM', 'PYTEST_CURRENT_TEST' }
SYSTEM_IGNORE_PREFIXES = ('GITHUB_', 'PYTEST_')
EXTERNAL_IGNORE_PREFIXES = ('KITE_', 'STORAGE_')  # treat provider/storage secrets as external for now

def load_catalog() -> set[str]:
    if not CATALOG.exists():
        return set()
    try:
        data = json.loads(CATALOG.read_text(encoding='utf-8'))
    except Exception:
        return set()
    vals = data.get('env_vars') or []
    result = set()
    for v in vals:
        if isinstance(v, str):
            result.add(v)
        elif isinstance(v, dict):
            name = v.get('name')
            if name:
                result.add(name)
    return result

def scan_vars() -> set[str]:
    found: set[str] = set()
    for base in ('src', 'scripts'):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob('*.py'):
            try:
                txt = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for pat in (GETENV_RE, ENV_INDEX_RE):
                for m in pat.finditer(txt):
                    found.add(m.group(1))
    return found

def main() -> int:
    catalog = load_catalog()
    code_vars = scan_vars()
    allow_prefixes = [p.strip() for p in os.getenv('G6_ENV_CATALOG_ALLOW_PREFIXES', '').split(',') if p.strip()]
    def allowed(name: str) -> bool:
        return any(name.startswith(pref) for pref in allow_prefixes)
    raw_missing = sorted([v for v in code_vars if v not in catalog and not allowed(v)])
    def ignored(name: str) -> bool:
        if name in SYSTEM_IGNORE_NAMES:
            return True
        if any(name.startswith(p) for p in SYSTEM_IGNORE_PREFIXES):
            return True
        if any(name.startswith(p) for p in EXTERNAL_IGNORE_PREFIXES):
            return True
        # Only govern G6_ namespace by default
        if not name.startswith('G6_'):
            return True
        return False
    missing = [v for v in raw_missing if not ignored(v)]
    stale = sorted([v for v in catalog if v not in code_vars and not allowed(v)])
    strict = os.getenv('G6_ENV_CATALOG_STRICT') == '1'
    print(f"[env-catalog] code_refs={len(code_vars)} catalog={len(catalog)} missing={len(missing)} stale={len(stale)} strict={strict}")
    ignored_count = len(raw_missing) - len(missing)
    if ignored_count:
        print(f"[env-catalog] ignored_non_governed={ignored_count}")
    if missing:
        print('[env-catalog] MISSING:', ','.join(missing))
        return 1
    if strict and stale:
        print('[env-catalog] STALE:', ','.join(stale))
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
