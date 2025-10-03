"""Governance test: JSON Schema key coverage in documentation.

Ensures every concrete key path defined in config/schema_v2.json appears in docs/config_dict.md.

Key path extraction rules:
  * Walk schema recursively collecting property paths (object -> properties keys).
  * Include patternProperties prefix placeholders as wildcard entries (<pattern>).* where appropriate.
  * For objects with additionalProperties=false we treat defined keys as canonical.
  * Arrays/lists do not introduce new key names (we only care about property names, not values).

Documentation recognition:
  * Any backticked entry `path.to.key` counts as documented.
  * Wildcard lines using `path.*` satisfy any subordinate key path.

Baseline management mirrors other governance tests:
  * tests/config_schema_doc_baseline.txt (should remain empty long-term)
  * G6_SKIP_CONFIG_SCHEMA_DOC_SYNC=1 to skip
  * G6_WRITE_CONFIG_SCHEMA_DOC_BASELINE=1 to rewrite baseline with current missing
  * G6_CONFIG_SCHEMA_DOC_STRICT=1 fail if baseline non-empty
"""
from __future__ import annotations

import json, os, re, pathlib, pytest
from typing import Set

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / 'config' / 'schema_v2.json'
DOC_FILE = ROOT / 'docs' / 'config_dict.md'
BASELINE_FILE = ROOT / 'tests' / 'config_schema_doc_baseline.txt'

SKIP_FLAG = 'G6_SKIP_CONFIG_SCHEMA_DOC_SYNC'
GEN_BASELINE_FLAG = 'G6_WRITE_CONFIG_SCHEMA_DOC_BASELINE'
STRICT_FLAG = 'G6_CONFIG_SCHEMA_DOC_STRICT'

DOC_KEY_PATTERN = re.compile(r'`([a-zA-Z0-9_.<>*]+)`')


def _walk_schema(node, prefix: str, out: Set[str]) -> None:
    if not isinstance(node, dict):
        return
    t = node.get('type')
    # Object properties
    if t == 'object':
        props = node.get('properties') or {}
        for k, v in props.items():
            path = f"{prefix}.{k}" if prefix else k
            out.add(path)
            _walk_schema(v, path, out)
        # patternProperties -> treat as wildcard prefix
        patt = node.get('patternProperties') or {}
        for pattern, v in patt.items():
            # represent documented need as <prefix>.<PATTERN>.* or pattern.* if top-level
            # Simplify regex anchor removal ^...$ and replace A-Z0-9_ range with SYMBOL placeholder
            core = pattern
            if core.startswith('^') and core.endswith('$'):
                core = core[1:-1]
            # Replace character classes with symbolic token
            core_token = '<SYMBOL>' if '[' in core else core
            path = f"{prefix}.{core_token}.*" if prefix else f"{core_token}.*"
            out.add(path)
            _walk_schema(v, f"{prefix}.{core_token}" if prefix else core_token, out)


def _load_schema_paths() -> Set[str]:
    data = json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))
    paths: Set[str] = set()
    _walk_schema(data, '', paths)
    return paths


def _load_documented() -> Set[str]:
    if not DOC_FILE.exists():
        return set()
    doc = DOC_FILE.read_text(encoding='utf-8')
    keys: Set[str] = set()
    for m in DOC_KEY_PATTERN.finditer(doc):
        keys.add(m.group(1))
    return keys


def _is_documented(key: str, documented: Set[str]) -> bool:
    if key in documented:
        return True
    # Parent wildcard match: any documented entry ending with .* that matches prefix
    parts = key.split('.')
    for i in range(1, len(parts) + 1):
        prefix = '.'.join(parts[:i])
        if prefix + '.*' in documented:
            return True
    return False


@pytest.mark.skipif(os.getenv(SKIP_FLAG, '').lower() in {'1','true','yes','on'}, reason='schema doc sync skipped')
def test_config_schema_keys_documented():
    schema_paths = _load_schema_paths()
    documented = _load_documented()

    missing = []
    for key in sorted(schema_paths):
        if not _is_documented(key, documented):
            missing.append(key)

    baseline = set()
    if BASELINE_FILE.exists():
        for line in BASELINE_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            baseline.add(line)

    new_missing = [k for k in missing if k not in baseline]

    if os.getenv(GEN_BASELINE_FLAG, '').lower() in {'1','true','yes','on'}:
        BASELINE_FILE.write_text('\n'.join(missing) + '\n', encoding='utf-8')
        pytest.skip(f'Schema doc baseline regenerated with {len(missing)} missing keys.')

    if new_missing:
        pytest.fail('Undocumented schema keys (new):\n' + '\n'.join(new_missing[:50]))

    if os.getenv(STRICT_FLAG, '').lower() in {'1','true','yes','on'} and baseline:
        pytest.fail(f'Strict mode: schema doc baseline not empty ({len(baseline)})')
