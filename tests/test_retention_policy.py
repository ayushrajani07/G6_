"""Governance test: enforce infinite retention policy (no built-in retention config keys).

Assertions:
 1. `config/schema_v2.json` must not define properties containing the substring 'retention'.
 2. `docs/config_dict.md` must not list active (non-Removed) keys containing 'retention'.
 3. `docs/RETENTION_POLICY.md` must exist and mention 'infinite retention'.

Rationale: The platform intentionally removed planned retention worker; policy is explicit infinite retention until scale pressures justify reintroduction. This test prevents accidental schema creep.
"""
from __future__ import annotations

import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / 'config' / 'schema_v2.json'
CONFIG_DOC = ROOT / 'docs' / 'config_dict.md'
RETENTION_DOC = ROOT / 'docs' / 'RETENTION_POLICY.md'


def test_no_retention_keys_in_schema():
    data = json.loads(SCHEMA.read_text(encoding='utf-8'))
    flat = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == 'properties' and isinstance(v, dict):
                    for pk in v.keys():
                        flat.append(pk)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    offenders = [k for k in flat if 'retention' in k.lower()]
    assert not offenders, f"Unexpected retention-like keys in schema: {offenders}"


def test_config_doc_no_active_retention_entries():
    text = CONFIG_DOC.read_text(encoding='utf-8')
    # Look for lines that are not marked Removed but contain retention.*
    offenders = []
    for line in text.splitlines():
        if 'retention' in line.lower() and 'Removed' not in line and '(removed)' not in line.lower():
            offenders.append(line.strip())
    assert not offenders, f"Retention references should be removed or marked Removed: {offenders[:3]}"


def test_retention_policy_doc_present_and_explicit():
    assert RETENTION_DOC.exists(), "RETENTION_POLICY.md missing"
    content = RETENTION_DOC.read_text(encoding='utf-8').lower()
    assert 'infinite retention' in content, "Retention policy doc must declare 'infinite retention'"
