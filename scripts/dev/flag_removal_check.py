"""Flag Removal Checklist Script

Purpose:
    Guard PRs that propose deleting deprecated environment flags or modules by
    asserting that all references (code + docs) have been eliminated except
    those explicitly whitelisted (historical deprecation records).

Usage:
    python scripts/dev/flag_removal_check.py --flag G6_SUMMARY_REWRITE --flag G6_SSE_ENABLED

Exit Codes:
    0 - All checks passed (no disallowed references found).
    1 - One or more flags still referenced outside allowlisted files/paths.
    2 - Script error / invalid arguments.

Logic:
    * Walk repository root (relative to this script).
    * For each file with a text-based extension (py, md, rst, txt, yml, yaml, sh, ps1, bat, json, ini, toml):
        - Search for exact flag token.
    * Ignore allowlisted paths (historical docs & deprecation registries) unless --strict provided.
    * Produce JSON summary to stdout when --json used; else print human readable table.

Environment:
    Designed to be dependency-light (stdlib only) for CI portability.

Planned Enhancements:
    * Add --remove-mode to automatically stage a patch removing leftover references (opt-in).
    * Support regex groups of flags from a preset file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass

TEXT_EXT = {'.py','.md','.rst','.txt','.yml','.yaml','.sh','.ps1','.bat','.json','.ini','.toml','.cfg'}
ALLOW_DEFAULT = {
    'DEPRECATIONS.md',
    os.path.join('docs','DEPRECATIONS.md'),
    'PHASE6_SCOPE.md',
    'PHASE7_SCOPE.md',
}

@dataclass
class FlagFinding:
    flag: str
    path: str
    line_no: int
    line: str

@dataclass
class FlagReport:
    flag: str
    findings: list[FlagFinding]
    allowed: bool

@dataclass
class Summary:
    reports: list[FlagReport]
    flags: list[str]
    fail_flags: list[str]


def iter_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip common vendor / cache dirs
        parts = {p.lower() for p in dirpath.split(os.sep)}
        if any(p in parts for p in {'.git','__pycache__','node_modules','.venv','.mypy_cache'}):
            continue
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT:
                yield os.path.join(dirpath, fn)


def scan_file(path: str, flags: set[str]) -> list[FlagFinding]:
    out: list[FlagFinding] = []
    try:
        with open(path,encoding='utf-8',errors='ignore') as f:
            for i, line in enumerate(f, start=1):
                for fl in flags:
                    if fl in line:
                        out.append(FlagFinding(fl, path, i, line.rstrip()))
    except Exception:
        return out
    return out


def build_reports(root: str, flags: list[str], allow: set[str], strict: bool) -> Summary:
    flag_set = set(flags)
    by_flag = {f: [] for f in flags}
    for fp in iter_files(root):
        rel = os.path.relpath(fp, root)
        for finding in scan_file(fp, flag_set):
            by_flag[finding.flag].append(finding)
    reports: list[FlagReport] = []
    fail_flags: list[str] = []
    for fl in flags:
        findings = by_flag.get(fl, [])
        # Determine if all findings are in allow list
        if strict:
            allowed = len(findings) == 0
        else:
            def _is_allowed(finding: FlagFinding) -> bool:
                rel_path = os.path.relpath(finding.path, root)
                return any(rel_path.endswith(a) for a in allow) or any(a in rel_path for a in allow)
            allowed = all(_is_allowed(f) for f in findings)
        if not allowed:
            fail_flags.append(fl)
        reports.append(FlagReport(flag=fl, findings=findings, allowed=allowed))
    return Summary(reports=reports, flags=flags, fail_flags=fail_flags)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Check repository for lingering deprecated flag references.')
    ap.add_argument('--flag', action='append', dest='flags', required=True, help='Flag (env var) to check; can repeat.')
    ap.add_argument('--root', default='.', help='Repo root (default .)')
    ap.add_argument('--json', action='store_true', help='Emit JSON report to stdout')
    ap.add_argument('--strict', action='store_true', help='Fail if ANY reference exists (ignores allow list)')
    ap.add_argument('--allow', action='append', dest='allow', default=[], help='Additional allowlisted relative paths (can repeat)')
    ns = ap.parse_args(argv)
    flags = ns.flags
    if not flags:
        print('No flags provided', file=sys.stderr)
        return 2
    allow: set[str] = set(ALLOW_DEFAULT)
    for extra in ns.allow:
        allow.add(extra)
    summary = build_reports(ns.root, flags, allow, ns.strict)
    if ns.json:
        payload = {
            'flags': summary.flags,
            'fail_flags': summary.fail_flags,
            'reports': [
                {
                    'flag': r.flag,
                    'allowed': r.allowed,
                    'findings': [asdict(f) for f in r.findings],
                } for r in summary.reports
            ]
        }
        print(json.dumps(payload, indent=2))
    else:
        print('Flag Removal Check Report')
        for r in summary.reports:
            status = 'OK' if r.allowed else 'FAIL'
            print(f"Flag {r.flag}: {status}")
            for f in r.findings:
                print(f"  {f.path}:{f.line_no}: {f.line}")
        if summary.fail_flags:
            print('\nFail flags:', ', '.join(summary.fail_flags))
    return 0 if not summary.fail_flags else 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
