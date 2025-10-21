"""Check that docs/INDEX.md lists required canonical docs.

Minimal heuristic: required set present as backticked filenames or code spans.
Exit 0 on success, 1 if any missing.

Env:
  G6_DOC_INDEX_REQUIRED (csv override of required doc basenames)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / 'docs' / 'INDEX.md'
DEFAULT_REQUIRED = [
    'README.md', 'clean.md', 'ENVIRONMENT.md', 'METRICS.md', 'DEPRECATIONS.md',
    'SSE.md', 'UNIFIED_MODEL.md', 'PANELS_FACTORY.md', 'CONFIGURATION.md'
]

def main() -> int:
    req_csv = os.getenv('G6_DOC_INDEX_REQUIRED')
    required = [r.strip() for r in req_csv.split(',')] if req_csv else DEFAULT_REQUIRED
    if not INDEX.exists():
        print('[doc-index] FAIL: INDEX.md missing')
        return 1
    txt = INDEX.read_text(encoding='utf-8', errors='ignore')
    missing = []
    for name in required:
        if name not in txt:
            missing.append(name)
    if missing:
        print('[doc-index] missing entries:', ','.join(missing))
        return 1
    print(f'[doc-index] OK required={len(required)}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
