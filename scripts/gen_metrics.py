#!/usr/bin/env python3
"""Generate metrics accessors and catalog from YAML spec.

Reads metrics/spec/base.yml and outputs:
  - src/metrics/generated.py  (accessor functions & registration)
  - METRICS_CATALOG.md        (human-readable catalog)

Adds SPEC_HASH constant + optional g6_metrics_spec_hash_info initialization.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
from typing import Any

import yaml  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / 'metrics' / 'spec' / 'base.yml'
OUT_MODULE = ROOT / 'src' / 'metrics' / 'generated.py'
OUT_CATALOG = ROOT / 'METRICS_CATALOG.md'

HEADER = """# Auto-generated file\n# SOURCE OF TRUTH: metrics/spec/base.yml (YAML)\n# DO NOT EDIT MANUALLY - run scripts/gen_metrics.py after modifying the spec.\n"""


def load_spec() -> dict[str, Any]:
    with open(SPEC, encoding='utf-8') as f:
        data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}


def compute_spec_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def gen_module(spec: dict[str, Any], spec_hash: str) -> str:
    families = spec.get('families', {})
    accessor_prefix = spec.get('codegen', {}).get('accessor_prefix', 'm_')
    lines = [HEADER, 'from __future__ import annotations', 'from .cardinality_guard import registry_guard', 'from typing import Any, Dict']
    lines.append("_METRICS: Dict[str, Any] = {}  # name -> metric instance")
    lines.append("def _get(name: str): return _METRICS.get(name)")
    lines.append(f"SPEC_HASH = '{spec_hash}'  # short sha256 of spec file")

    for fam, data in families.items():
        for m in data.get('metrics', []):
            name = m['name']
            mtype = m['type']
            help_text = m.get('help','').replace('"','\\"')
            labels = m.get('labels', []) or []
            budget = m.get('cardinality_budget', 100)
            buckets = m.get('buckets') if mtype == 'histogram' else None
            func_name = accessor_prefix + name.replace('g6_','')
            reg_call = {
                'counter': f"registry_guard.counter('{name}', '{help_text}', {labels}, {budget})",
                'gauge': f"registry_guard.gauge('{name}', '{help_text}', {labels}, {budget})",
                'histogram': f"registry_guard.histogram('{name}', '{help_text}', {labels}, {budget}, buckets={buckets})",
            }[mtype]
            lines.append(f"def {func_name}():\n    if '{name}' not in _METRICS:\n        _METRICS['{name}'] = {reg_call}\n    return _METRICS['{name}']")
            if labels:
                label_sig = ', '.join([f"{l}: str" for l in labels])
                tuple_expr = '(' + ','.join([l for l in labels]) + ',)'
                lines.append(f"def {func_name}_labels({label_sig}):\n    metric = {func_name}()\n    if not metric: return None\n    if not registry_guard.track('{name}', {tuple_expr}): return None\n    return metric.labels({', '.join([f'{l}={l}' for l in labels])})")

    # Governance static hash metrics auto-initialization
    spec_hash_accessor = None
    build_hash_accessor = None
    for fam2, data2 in families.items():
        for m2 in data2.get('metrics', []):
            n = m2.get('name')
            if n == 'g6_metrics_spec_hash_info':
                spec_hash_accessor = accessor_prefix + 'metrics_spec_hash_info'
            elif n == 'g6_build_config_hash_info':
                build_hash_accessor = accessor_prefix + 'build_config_hash_info'
        if spec_hash_accessor and build_hash_accessor:
            break
    if spec_hash_accessor:
        lines.append("try:\n    _hm = %s()\n    if _hm: _hm.labels(hash=SPEC_HASH).set(1)\nexcept Exception: pass" % spec_hash_accessor)
    # Build/config hash is provided via env var G6_BUILD_CONFIG_HASH (falls back to SPEC_HASH if unset)
    if build_hash_accessor:
        lines.append("try:\n    import os\n    _bhv = os.getenv('G6_BUILD_CONFIG_HASH', SPEC_HASH)\n    _bh = %s()\n    if _bh: _bh.labels(hash=_bhv).set(1)\nexcept Exception: pass" % build_hash_accessor)

    lines.append("__all__ = [n for n in globals() if n.startswith('%s') or n in {'SPEC_HASH'}]" % accessor_prefix)
    return '\n\n'.join(lines) + '\n'


def gen_catalog(spec: dict[str, Any]) -> str:
    # Use timezone-aware UTC (utcnow deprecated)
    ts = dt.datetime.now(dt.UTC).isoformat(timespec='seconds').replace('+00:00','Z')
    out = [f"# Metrics Catalog\n\nGenerated: {ts}\n\n"]
    for fam, data in spec.get('families', {}).items():
        out.append(f"## Family: {fam}\nOwner: {data.get('owner','unknown')}\n")
        for m in data.get('metrics', []):
            out.append(f"### {m['name']}\nType: {m['type']}  ")
            out.append(f"Help: {m.get('help','')}  ")
            labels = m.get('labels', []) or []
            out.append(f"Labels: {', '.join(labels) if labels else '(none)'}  ")
            out.append(f"Cardinality Budget: {m.get('cardinality_budget','?')}\n")
    return '\n'.join(out) + '\n'


def main() -> None:
    spec = load_spec()
    raw = SPEC.read_bytes()
    spec_hash = compute_spec_hash(raw)
    OUT_MODULE.write_text(gen_module(spec, spec_hash), encoding='utf-8')
    OUT_CATALOG.write_text(gen_catalog(spec), encoding='utf-8')
    print(json.dumps({
        'module': str(OUT_MODULE),
        'catalog': str(OUT_CATALOG),
        'spec_hash': spec_hash,
        'status': 'ok'
    }))


if __name__ == '__main__':
    main()
