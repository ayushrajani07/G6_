import os, re, pathlib, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_FILE = ROOT / 'docs' / 'env_dict.md'
AUTO_JSON = ROOT / 'docs' / 'ENV_VARS_AUTO.json'

# Allowlist: names that may appear in code but are acceptable to ignore (proposed, deprecated, dynamic patterns)
ALLOWLIST = {
    'G6_DISABLE_PER_OPTION_METRICS',
    'G6_MEMORY_TIER_OVERRIDE',
    'G6_TRACE_METRICS',  # proposed (section 21)
}

BASELINE_FILE = ROOT / 'tests' / 'env_doc_baseline.txt'
GEN_BASELINE_FLAG = 'G6_WRITE_ENV_DOC_BASELINE'
STRICT_FLAG = 'G6_ENV_DOC_STRICT'

SKIP_FLAG = 'G6_SKIP_ENV_DOC_VALIDATION'

@pytest.mark.skipif(os.getenv(SKIP_FLAG, '').lower() in {'1','true','yes','on'}, reason=f"Set {SKIP_FLAG}=0 to enable env var documentation coverage test")
def test_all_g6_env_vars_are_documented():
    """Scan repository for G6_ env var usages and verify each is in env_dict.md.

    Heuristics:
      - We match tokens of the form G6_[A-Z0-9_]+ via regex.
      - We scan only relevant text files: .py, .md, .sh, .bat, .ps1, .ini, .txt inside src/, tests/, scripts/, docs/.
      - We exclude __pycache__ and virtual env like directories.
      - Documentation presence is a simple substring match in env_dict.md lines (case sensitive).
      - Proposed / roadmap variables (section 21) are allowlisted.
    """
    pattern = re.compile(r'G6_[A-Z0-9_]+')

    # Prefer using the generated JSON inventory if present (ensures parity with CI tooling)
    found = set()
    if AUTO_JSON.exists():
        try:
            import json
            data = json.loads(AUTO_JSON.read_text(encoding='utf-8'))
            for item in data.get('inventory', []):
                name = item.get('name')
                if isinstance(name, str) and pattern.fullmatch(name):
                    found.add(name)
        except Exception as e:
            print(f"[env-doc-coverage] WARN: Failed to read auto inventory JSON ({AUTO_JSON}): {e}; falling back to live scan")

    if not found:
        # Fallback live scan if JSON absent or unreadable
        search_dirs = [ROOT / 'src', ROOT / 'tests', ROOT / 'scripts']
        for base in search_dirs:
            if not base.exists():
                continue
            for path in base.rglob('*'):
                if path.is_dir():
                    continue
                if any(part.startswith('.') for part in path.parts):
                    continue
                if '__pycache__' in path.parts:
                    continue
                if path.suffix.lower() not in {'.py', '.md', '.sh', '.bat', '.ps1', '.ini', '.txt'}:
                    continue
                try:
                    text = path.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue
                for m in pattern.findall(text):
                    found.add(m)

    # Read documented md
    try:
        doc_text = DOC_FILE.read_text(encoding='utf-8')
    except FileNotFoundError:
        pytest.fail(f'Missing documentation file: {DOC_FILE}')

    # Load baseline if present (incremental adoption). Baseline lists known undocumented
    # variables accepted temporarily until documented. New undocumented names beyond the
    # baseline will still fail.
    baseline = set()
    if BASELINE_FILE.exists():
        try:
            for line in BASELINE_FILE.read_text(encoding='utf-8').splitlines():
                line=line.strip()
                if not line or line.startswith('#'):
                    continue
                baseline.add(line)
        except Exception as e:
            pytest.fail(f'Could not read baseline file {BASELINE_FILE}: {e}')

    undocumented_all = sorted([name for name in found if name not in ALLOWLIST and name not in doc_text])
    # Separate into previously-known (baseline) and new
    undocumented_new = [u for u in undocumented_all if u not in baseline]

    # Optionally (re)generate baseline file
    if os.getenv(GEN_BASELINE_FLAG,'').lower() in {'1','true','yes','on'}:
        BASELINE_FILE.write_text('\n'.join(undocumented_all) + '\n', encoding='utf-8')
        pytest.skip(f'Baseline file written with {len(undocumented_all)} undocumented names. Commit it and then document incrementally.')

    # Provide helpful diff style output
    if undocumented_new:
        # Rare intermittent false negatives have been observed on CI where doc file substring
        # search misses freshly added entries early in the run. Perform one guarded re-read
        # to rule out a transient I/O race before failing hard.
        doc_text_retry = None
        try:
            doc_text_retry = DOC_FILE.read_text(encoding='utf-8')
        except Exception:
            doc_text_retry = None
        if doc_text_retry and any(name in doc_text_retry for name in undocumented_new):
            # Recompute with retry contents
            pattern = re.compile(r'G6_[A-Z0-9_]+')
            documented_names_retry = set(pattern.findall(doc_text_retry))
            undocumented_all_retry = sorted([name for name in found if name not in ALLOWLIST and name not in documented_names_retry])
            undocumented_new_retry = [u for u in undocumented_all_retry if u not in baseline]
            if not undocumented_new_retry:
                # Log a diagnostic and continue without failing
                print('[env-doc-coverage] Transient doc miss resolved on retry; proceeding.')
            else:
                preview = '\n'.join(undocumented_new_retry[:10])
                pytest.fail(f"Undocumented G6_ environment variables (new since baseline) found (post-retry) (showing up to 10):\n{preview}\nNew missing: {len(undocumented_new_retry)} (Total undocumented incl. baseline: {len(undocumented_all_retry)})\nUpdate docs/env_dict.md or add to baseline only with justification.")
        else:
            preview = '\n'.join(undocumented_new[:10])
            pytest.fail(f"Undocumented G6_ environment variables (new since baseline) found (showing up to 10):\n{preview}\nNew missing: {len(undocumented_new)} (Total undocumented incl. baseline: {len(undocumented_all)})\nUpdate docs/env_dict.md or add to baseline only with justification.")

    # If there are still baseline entries, emit a reminder, or fail in strict mode
    if undocumented_all and not undocumented_new:
        if os.getenv(STRICT_FLAG, '').lower() in {'1','true','yes','on'}:
            pytest.fail(f"Strict mode enabled ({STRICT_FLAG}=1) but {len(undocumented_all)} undocumented env vars remain (baseline not empty). Clean baseline to zero.")
        else:
            print(f"[env-doc-coverage] All undocumented vars ({len(undocumented_all)}) are in baseline file; enable {STRICT_FLAG}=1 to enforce zero-baseline.")

    # Also check docs for stale entries (documented but unused) except allowlist / roadmap
    documented_names = set(pattern.findall(doc_text))
    stale = sorted([d for d in documented_names if d not in found and d not in ALLOWLIST])
    # We warn (not fail) on stale to avoid blocking interim deprecations.
    if stale:
        print(f"[env-doc-coverage] NOTE: {len(stale)} documented names not found in code: {stale[:15]} ...")

    # Ensure skip flag itself is documented once introduced; if not, don't block (optional)
    if SKIP_FLAG not in doc_text:
        print(f"[env-doc-coverage] INFO: {SKIP_FLAG} not documented (optional). Consider adding a note in env_dict.md.")
