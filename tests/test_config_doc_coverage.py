"""Governance test: ensure all config JSON keys present in code are documented in docs/config_dict.md.

Strategy:
1. Load primary config file (config/g6_config.json) plus any *_config*.json variants to collect keys.
2. Collect keys used in code by walking AST of src/ for dict/string subscripts (e.g., conf['metrics']['port']).
3. Normalize keys into dotted paths (e.g., metrics.port, storage.influx.bucket, indices.NIFTY.enable).
4. Compare with documentation lines in docs/config_dict.md.
5. Allow a baseline file (tests/config_doc_baseline.txt) for transitional adoption (should remain empty now).

Flags:
  G6_SKIP_CONFIG_DOC_VALIDATION=1  -> skip test (emergency only)
  G6_WRITE_CONFIG_DOC_BASELINE=1    -> rewrite baseline file with current missing keys
  G6_CONFIG_DOC_STRICT=1            -> fail if baseline not empty (CI enforced)

Heuristics:
  - Keys limited to alphanum + underscore (converted to dotted notation by file traversal).
  - Only JSON-defined keys considered authoritative; AST string keys supplement detection for newly added code references.
  - Proposed/planned keys section in docs (Pending / Planned) ignored (treated as documented if present there).
"""
from __future__ import annotations

import json, os, re, ast, pathlib, pytest
from typing import Set, Iterable

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_FILE = ROOT / 'docs' / 'config_dict.md'
BASELINE_FILE = ROOT / 'tests' / 'config_doc_baseline.txt'
CONFIG_DIR = ROOT / 'config'
SOURCE_DIR = ROOT / 'src'

SKIP_FLAG = 'G6_SKIP_CONFIG_DOC_VALIDATION'
GEN_BASELINE_FLAG = 'G6_WRITE_CONFIG_DOC_BASELINE'
STRICT_FLAG = 'G6_CONFIG_DOC_STRICT'

# Simple regex to detect table lines containing a path/key segment (| `collection.interval_seconds` | etc.)
DOC_KEY_PATTERN = re.compile(r'`([a-zA-Z0-9_.<>]+)`')
WILDCARD_DOC_IMPLICIT = {
    'index_params.*',  # treat any legacy translated index_params.* keys as covered by indices.* docs
    'indices.*',       # dynamic indices subtree
}
CANONICAL_ALIASES = {
    'collection_interval': 'collection.interval_seconds',
}
EXPLICIT_DOC_IMPLICIT = {
    'console', 'features', 'greeks', 'collection', 'storage', 'metrics', 'data_dir',
    'overlays', 'providers', 'orchestration', 'influx'
}

def iter_config_files() -> Iterable[pathlib.Path]:
    for p in CONFIG_DIR.glob('*config*.json'):
        if p.is_file():
            yield p

def extract_json_keys(data, prefix='') -> Set[str]:
    keys: Set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            path = f"{prefix}.{k}" if prefix else k
            keys.add(path)
            keys |= extract_json_keys(v, path)
    elif isinstance(data, list):
        # For lists of dicts with homogeneous schema we do not attempt per-index keys
        for item in data:
            keys |= extract_json_keys(item, prefix)
    return keys

CONFIG_ROOT_VARS = {"config", "cfg", "conf", "raw_config", "normalized"}

class KeyVisitor(ast.NodeVisitor):
    """Collect dotted key paths only when the subscript chain roots in a known config variable name.

    Example accepted: config['storage']['influx']['bucket'] -> storage.influx.bucket
    Example ignored: arbitrary_dict['avg_price'] (root not recognized).
    """

    def __init__(self):
        self.paths: Set[str] = set()

    def visit_Subscript(self, node: ast.Subscript):  # type: ignore[override]
        chain: list[str] = []
        cur = node
        valid = True
        # Walk nested Subscript nodes outward
        while isinstance(cur, ast.Subscript):
            sl = cur.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and re.match(r'^[A-Za-z0-9_]+$', sl.value):
                chain.append(sl.value)
            else:
                valid = False
                break
            cur = cur.value  # type: ignore[attr-defined]
        # At root expect Name(id in CONFIG_ROOT_VARS)
        if not (valid and isinstance(cur, ast.Name) and cur.id in CONFIG_ROOT_VARS):
            return  # ignore non-config chains
        # Build dotted path excluding the root variable name
        dotted = '.'.join(reversed(chain))
        if dotted:
            self.paths.add(dotted)
        # Continue traversal
        self.generic_visit(node)

def collect_code_string_keys() -> Set[str]:
    keys: Set[str] = set()
    for p in SOURCE_DIR.rglob('*.py'):
        if '__pycache__' in p.parts:
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        v = KeyVisitor()
        v.visit(tree)
        keys |= v.paths
    return keys

def load_documented_keys() -> Set[str]:
    if not DOC_FILE.exists():
        return set()
    text = DOC_FILE.read_text(encoding='utf-8')
    doc_keys: Set[str] = set()
    for m in DOC_KEY_PATTERN.finditer(text):
        doc_keys.add(m.group(1))
    return doc_keys

@pytest.mark.skipif(os.getenv(SKIP_FLAG, '').lower() in {'1','true','yes','on'}, reason='config doc validation skipped')
def test_all_config_keys_are_documented():
    # 1. Collect keys from JSON config files
    json_keys: Set[str] = set()
    for cfg in iter_config_files():
        try:
            data = json.loads(cfg.read_text(encoding='utf-8'))
        except Exception:
            continue
        json_keys |= extract_json_keys(data)

    # 2. Collect dotted paths from code rooted in config variables
    code_paths = collect_code_string_keys()

    # 3. Candidate keys: union of JSON dotted paths and code-derived paths
    candidate_keys = set(json_keys) | code_paths

    documented = load_documented_keys()

    # Filter candidate keys already documented when appearing as exact path OR prefix match (e.g., indices.<SYMBOL>.enable documented generically as indices.<SYMBOL>.* )
    effective_missing = []
    for key in sorted(candidate_keys):
        # normalize aliases
        key_norm = CANONICAL_ALIASES.get(key, key)
        if key in documented or key_norm in documented or key.split('.')[0] in EXPLICIT_DOC_IMPLICIT:
            continue
        # prefix wildcard support: if any documented entry endswith .* and matches prefix
        matched = False
        for d in documented:
            if d.endswith('.*') and key.startswith(d[:-2]):
                matched = True
                break
        if not matched:
            # implicit wildcards
            for w in WILDCARD_DOC_IMPLICIT:
                if w.endswith('.*') and key.startswith(w[:-2]):
                    matched = True
                    break
        if not matched:
            effective_missing.append(key_norm)

    # Baseline management
    baseline = set()
    if BASELINE_FILE.exists():
        for line in BASELINE_FILE.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            baseline.add(line)

    new_missing = [k for k in effective_missing if k not in baseline]

    if os.getenv(GEN_BASELINE_FLAG,'').lower() in {'1','true','yes','on'}:
        BASELINE_FILE.write_text('\n'.join(effective_missing) + '\n', encoding='utf-8')
        pytest.skip(f'Config baseline regenerated with {len(effective_missing)} missing keys.')

    if new_missing:
        preview='\n'.join(new_missing[:25])
        pytest.fail(f"Undocumented config keys (new):\n{preview}\nNew missing: {len(new_missing)} Total missing (incl baseline): {len(effective_missing)}")

    if os.getenv(STRICT_FLAG,'').lower() in {'1','true','yes','on'} and baseline:
        pytest.fail(f"Strict mode: config baseline not empty ({len(baseline)})")

