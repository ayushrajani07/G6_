"""Generate a PR / release checklist markdown snippet.

Combines status from:
  * Presence of key scripts (readiness, benchmark, clients)
  * Absence of deprecated scripts
  * Core docs sections present in README (security, structured diff, perf, readiness)
  * Optional live readiness run (--run-readiness)

Usage:
  python scripts/pr_checklist.py > PR_CHECKLIST.md
  python scripts/pr_checklist.py --run-readiness --strict > PR_CHECKLIST.md

Exit code non-zero if --strict and a required item is missing.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / 'README.md'
ENV_DOC = REPO / 'docs' / 'env_dict.md'

REQUIRED_FILES = [
    'scripts/release_readiness.py',
    'scripts/bench_sse_loop.py',
    'clients/python_sse_client.py',
    'clients/js_sse_client.js',
]
ABSENT_DEPRECATED = [
    'scripts/run_live.py'
]
README_SECTIONS = [
    'SSE Streaming Security','Structured Diff & Clients','Performance Instrumentation','Release Readiness Automation'
]

CHECK_ICONS = {True: '✅', False: '❌'}

class ChecklistFailure(Exception):
    pass

def file_exists(rel: str) -> bool:
    return (REPO / rel).exists()

def run_readiness(strict: bool) -> tuple[bool,str]:
    cmd = [sys.executable,'scripts/release_readiness.py','--check-env','--check-deprecations']
    if strict:
        cmd.append('--strict')
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0
    return ok, proc.stdout.strip() or proc.stderr.strip()

def main() -> int:
    ap = argparse.ArgumentParser(description='Generate PR checklist')
    ap.add_argument('--run-readiness', action='store_true')
    ap.add_argument('--strict', action='store_true', help='Non-zero exit if any required item missing')
    ap.add_argument('--summary-line', action='store_true', help='Emit a single-line machine friendly summary (no checklist)')
    args = ap.parse_args()

    missing: list[str] = []

    readme_text = README.read_text(encoding='utf-8', errors='ignore') if README.exists() else ''

    items = []
    # Required files
    for f in REQUIRED_FILES:
        ok = file_exists(f)
        if not ok and args.strict:
            missing.append(f)
        items.append((f"File present: {f}", ok))
    # Deprecated absence
    for f in ABSENT_DEPRECATED:
        ok = not file_exists(f)
        if not ok and args.strict:
            missing.append(f"deprecated:{f}")
        items.append((f"Deprecated removed: {f}", ok))
    # README sections
    for sec in README_SECTIONS:
        ok = sec.lower() in readme_text.lower()
        if not ok and args.strict:
            missing.append(f"readme:{sec}")
        items.append((f"README section: {sec}", ok))
    # Env doc presence (basic existence)
    env_doc_ok = ENV_DOC.exists()
    if not env_doc_ok and args.strict:
        missing.append('env_doc')
    items.append(("Env doc exists", env_doc_ok))

    readiness_output = ''
    if args.run_readiness:
        ok, out = run_readiness(strict=args.strict)
        items.append(("Readiness script run (basic)", ok))
        readiness_output = out
        if not ok and args.strict:
            missing.append('readiness')

    if args.summary_line:
        status = 'OK' if not missing else 'FAIL'
        # Build compact fields
        fields = []
        for label, ok in items:
            key = label.split(':',1)[0].replace(' ','_').lower()
            fields.append(f"{key}={'1' if ok else '0'}")
        if readiness_output:
            fields.append(f"readiness={'OK' if 'readiness:OK' in readiness_output or '[readiness:OK]' in readiness_output else 'FAIL'}")
        print(f"PR_CHECKLIST_SUMMARY status={status} {' '.join(fields)}")
        return 0 if status=='OK' else 1
    else:
        # Emit markdown
        print('# PR Checklist')
        print()
        for label, ok in items:
            print(f"- {CHECK_ICONS[ok]} {label}")
        if readiness_output:
            print('\n<details><summary>Readiness Output</summary>')
            print('\n```')
            print(readiness_output)
            print('```\n</details>')
        if missing and args.strict:
            print(f"\n**Missing Critical Items:** {', '.join(missing)}")
            return 1
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
