"""Verify provenance statement checksums against local artifacts.

Usage:
  python scripts/verify_provenance.py --provenance dist/provenance_1.2.3.json
  python scripts/verify_provenance.py --provenance dist/provenance_1.2.3.json --json --strict

Exit Codes:
 0 - All artifacts match (or mismatches allowed without --strict)
 1 - Mismatch(es) detected in strict mode
 2 - Provenance file unreadable / schema error

JSON Output (if --json):
 {
   "ok": bool,
   "mismatches": [{name,path,expected,actual}],
   "missing": [{name,path,expected}],
   "extra": [artifact_names_not_listed]
 }
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Verify provenance artifacts')
    ap.add_argument('--provenance', required=True)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true')
    return ap.parse_args()

def main() -> int:  # pragma: no cover
    args = parse_args()
    pv_path = Path(args.provenance)
    if not pv_path.exists():
        print(f"Provenance missing: {pv_path}")
        return 2
    try:
        data = json.loads(pv_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"Failed to parse provenance: {e}")
        return 2
    artifacts = data.get('artifacts') or []
    mismatches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for ent in artifacts:
        path = Path(ent.get('path',''))
        expected = ent.get('sha256')
        name = ent.get('name')
        if not path.exists():
            missing.append({'name': name, 'path': str(path), 'expected': expected})
            continue
        actual = sha256_file(path)
        if actual != expected:
            mismatches.append({'name': name, 'path': str(path), 'expected': expected, 'actual': actual})
    ok = not mismatches and not missing
    if args.json:
        print(json.dumps({'ok': ok, 'mismatches': mismatches, 'missing': missing}, indent=2))
    else:
        if ok:
            print('Provenance OK')
        else:
            if mismatches:
                print('Checksum mismatches:')
                for m in mismatches:
                    print(f"  {m['name']}: expected {m['expected']} actual {m['actual']}")
            if missing:
                print('Missing artifacts:')
                for m in missing:
                    print(f"  {m['name']}: path {m['path']}")
    if not ok and args.strict:
        return 1
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
