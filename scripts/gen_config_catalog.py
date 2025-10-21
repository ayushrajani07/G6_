#!/usr/bin/env python
"""Generate a configuration keys catalog from `config/_config.json`.

The output is a simple markdown table listing dotted key paths, value type,
default value (stringified), and a heuristic category (top-level section).

Intended for operator quick reference and to pair with ENV_VARS_CATALOG.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / 'config' / '_config.json'
OUT = ROOT / 'docs' / 'CONFIG_KEYS_CATALOG.md'

def iter_items(prefix: str, obj: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f'{prefix}.{k}' if prefix else k
            yield from iter_items(new_prefix, v)
    else:
        yield prefix, obj

def classify(val: Any) -> str:
    if isinstance(val, bool):
        return 'bool'
    if isinstance(val, int):
        return 'int'
    if isinstance(val, float):
        return 'float'
    if isinstance(val, list):
        return 'list'
    if isinstance(val, dict):
        return 'object'
    return 'str'

def stringify(val: Any) -> str:
    if isinstance(val, (dict, list)):
        import json
        txt = json.dumps(val, separators=(',',':'))
        return txt if len(txt) <= 80 else txt[:77] + '…'
    return str(val)

def build_markdown(pairs: list[tuple[str, Any]]) -> str:
    now = datetime.now(UTC).isoformat().replace('+00:00','Z')
    stamp = os.getenv('G6_CATALOG_TS', now)
    out = []
    out.append('# G6 Configuration Keys Catalog')
    out.append('')
    out.append(f'Generated: {stamp}')
    out.append('Source file: config/_config.json (do not edit generated catalog manually).')
    out.append('')
    out.append('Key | Type | Default | Section')
    out.append('--- | --- | --- | ---')
    for key, val in sorted(pairs, key=lambda kv: kv[0]):
        section = key.split('.',1)[0]
        out.append(f'{key} | {classify(val)} | {stringify(val)} | {section}')
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
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        pairs = list(iter_items('', data))
        md = build_markdown(pairs)
        write_atomic(OUT, md)
        print(f'Wrote {OUT} (keys={len(pairs)})')
    except Exception as e:  # pragma: no cover
        print(f'ERROR generating config catalog: {e}', file=sys.stderr)
        return 0
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
