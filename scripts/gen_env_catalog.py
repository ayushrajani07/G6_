#!/usr/bin/env python
"""Generate a normalized environment variable catalog.

This complements `gen_env_inventory.py` (which is diff/coverage oriented) by
producing a single markdown table suitable for operator / release artifacts.

Source of truth for descriptions remains `docs/env_dict.md` – we parse the
bullet list sections and extract lines beginning with `- G6_` (or space + dash).

Columns:
  Name | Type | Default | Referenced (Code) | Documented | Description (truncated)

Referenced(Code) uses a repo scan (same token regex) to flag variables present
in code. Documented is always Y for rows we extract; rows referenced in code
but *not* documented are appended in a second section (Undocumented) so the
catalog still surfaces them when run ad‑hoc outside the governance test.

Usage:
  python scripts/gen_env_catalog.py                # writes docs/ENV_VARS_CATALOG.md
  G6_CATALOG_TS=2025-10-02 python scripts/gen_env_catalog.py  # inject version/timestamp label

The script is deliberately permissive; failures never raise (exit 0) so that
missing sections do not break release automation.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_DICT = ROOT / 'docs' / 'env_dict.md'
OUT = ROOT / 'docs' / 'ENV_VARS_CATALOG.md'
TOKEN_RE = re.compile(r"\bG6_[A-Z0-9_]+\b")

# Pattern capturing lines like: - G6_FOO_BAR – type – default – description (example token omitted to avoid false positives)
LINE_RE = re.compile(r"^\s*-\s*(G6_[A-Z0-9_]+)\s+–\s+([^–]+?)\s+–\s+([^–]+?)\s+–\s+(.*)$")

SCAN_EXT = {'.py', '.md', '.sh', '.ps1', '.yml', '.yaml'}
EXCLUDE_DIRS = {'.git', '__pycache__', 'logs', 'data', 'parity_snapshots', 'archive'}


def scan_repo_tokens(root: Path) -> set[str]:
    out: set[str] = set()
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in SCAN_EXT:
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        out.update(TOKEN_RE.findall(text))
    return out




def parse_env_dict(path: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            m = LINE_RE.match(line.rstrip())
            if not m:
                continue
            name, typ, default, desc = m.groups()
            rows.append((name.strip(), typ.strip(), default.strip(), desc.strip()))
    except Exception:
        return []
    return rows


def truncate(desc: str, limit: int = 120) -> str:
    if len(desc) <= limit:
        return desc
    return desc[: limit - 1].rstrip() + '…'


def build_markdown(doc_rows: list[tuple[str, str, str, str]], code_tokens: set[str]) -> str:
    documented_names = {r[0] for r in doc_rows}
    # Filter out broad prefix placeholders (tokens ending with '_' or obviously generic) to
    # reduce noise that would never be documented individually (e.g., G6_PANELS_, G6_METRICS_)
    filtered = {n for n in code_tokens - documented_names if not (n.endswith('_') or n in {'G6_NAME'})}
    undocumented = sorted(filtered)

    now = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    stamp = os.getenv('G6_CATALOG_TS', now)
    out = []
    out.append('# G6 Environment Variables Catalog')
    out.append('')
    out.append(f'Generated: {stamp}')
    out.append('Source of truth: docs/env_dict.md (this table is derived, do not edit manually).')
    out.append('')
    out.append(f'Total documented: {len(doc_rows)}  | Referenced in code: {len(code_tokens)}  | Undocumented: {len(undocumented)}')
    out.append('')
    out.append('Name | Type | Default | Referenced | Description')
    out.append('--- | --- | --- | --- | ---')
    for name, typ, default, desc in sorted(doc_rows, key=lambda r: r[0]):
        ref = 'Y' if name in code_tokens else 'N'
        out.append(f'{name} | {typ} | {default} | {ref} | {truncate(desc)}')
    if undocumented:
        out.append('')
        out.append('## Undocumented (present in code but missing from env_dict.md)')
        out.append('')
        out.append('Name | Referenced | Rationale')
        out.append('--- | --- | ---')
        for name in undocumented:
            out.append(f'{name} | Y | needs docs')
    out.append('')
    return '\n'.join(out)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8') as tf:
        tmp = Path(tf.name)
        tf.write(text.rstrip() + '\n')
    tmp.replace(path)


def main(argv: list[str]) -> int:
    try:
        doc_rows = parse_env_dict(ENV_DICT)
        code_tokens = scan_repo_tokens(ROOT)
        md = build_markdown(doc_rows, code_tokens)
        write_atomic(OUT, md)
        print(f'Wrote {OUT} (documented={len(doc_rows)} code_tokens={len(code_tokens)})')
    except Exception as e:  # pragma: no cover - resilience
        print(f'ERROR generating env catalog: {e}', file=sys.stderr)
        return 0  # keep non-fatal
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
