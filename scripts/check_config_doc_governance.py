#!/usr/bin/env python
"""Fast pre-commit governance check for config key documentation.
Matches logic in tests/test_config_doc_coverage.py but quicker (no AST wildcard extras beyond subscripts).
"""
from __future__ import annotations
import json, ast, re, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_FILE = ROOT / 'docs' / 'config_dict.md'
BASELINE_FILE = ROOT / 'tests' / 'config_doc_baseline.txt'
CONFIG_DIR = ROOT / 'config'
SRC_DIR = ROOT / 'src'
DOC_KEY_PATTERN = re.compile(r'`([a-zA-Z0-9_.<>*]+)`')

class KeyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.keys=set()
    def visit_Subscript(self,node):  # type: ignore[override]
        try:
            sl=node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value,str):
                v=sl.value
                if re.match(r'^[A-Za-z0-9_]+$', v):
                    self.keys.add(v)
        except Exception:
            pass
        self.generic_visit(node)

def load_json_keys():
    keys=set()
    for p in CONFIG_DIR.glob('*config*.json'):
        try:
            data=json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        keys |= extract_json_keys(data)
    return keys

def extract_json_keys(data,prefix=''):
    out=set()
    if isinstance(data,dict):
        for k,v in data.items():
            if not isinstance(k,str):
                continue
            path=f"{prefix}.{k}" if prefix else k
            out.add(path)
            out|=extract_json_keys(v,path)
    elif isinstance(data,list):
        for it in data:
            out|=extract_json_keys(it,prefix)
    return out

def load_doc_keys():
    if not DOC_FILE.exists():
        return set()
    text=DOC_FILE.read_text(encoding='utf-8')
    keys=set(m.group(1) for m in DOC_KEY_PATTERN.finditer(text))
    return keys

def collect_code_keys():
    agg=set()
    for p in SRC_DIR.rglob('*.py'):
        if '__pycache__' in p.parts:
            continue
        try:
            text=p.read_text(encoding='utf-8')
            tree=ast.parse(text)
        except Exception:
            continue
        v=KeyVisitor(); v.visit(tree)
        agg|=v.keys
    return agg

def main():
    doc=load_doc_keys()
    baseline=set()
    if BASELINE_FILE.exists():
        for line in BASELINE_FILE.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            baseline.add(line)
    json_keys=load_json_keys()
    code_keys=collect_code_keys()
    candidates=json_keys|code_keys
    missing=[]
    for key in sorted(candidates):
        if key in doc:
            continue
        matched=False
        for d in doc:
            if d.endswith('.*') and key.startswith(d[:-2]):
                matched=True; break
        if not matched:
            missing.append(key)
    if missing:
        print("Undocumented config keys (up to 25):\n  - "+"\n  - ".join(missing[:25]), file=sys.stderr)
        return 1
    if baseline:
        print(f"Config baseline not empty ({len(baseline)}) – remove entries after documenting.", file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
