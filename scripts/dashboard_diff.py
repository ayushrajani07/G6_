"""Dashboard manifest diff & changelog updater.

Compares two manifest JSON files produced by `package_dashboards.py` and
outputs structured diff (added, removed, changed). When provided a
`--changelog` path it prepends a formatted release section.

Changed items capture: title change, uid change, checksum change.

Usage:
  python scripts/dashboard_diff.py --prev dist/dashboards_manifest_old.json \
  --curr dist/dashboards_manifest_new.json --version 1.2.3 --changelog CHANGELOG_DASHBOARDS.md

Exit codes:
  0 success (diff computed, changelog updated if requested)
  2 invalid input
  3 no changes (if --fail-if-no-change specified)
"""
from __future__ import annotations

import argparse, json, sys, datetime
from pathlib import Path
from typing import Dict, Any, Tuple

def load_manifest(path: Path) -> Dict[str, Any]:
  try:
    return json.loads(path.read_text(encoding='utf-8'))
  except Exception as e:
    raise SystemExit(f"Failed reading manifest {path}: {e}")

def index_files(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  for rec in manifest.get('files', []):
    out[rec.get('file')] = rec
  return out

def compute_diff(prev: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, Any]:
  pmap = index_files(prev)
  cmap = index_files(curr)
  added = []
  removed = []
  changed = []
  for f, rec in cmap.items():
    if f not in pmap:
      added.append(rec)
    else:
      prec = pmap[f]
      chg = {}
      if (prec.get('sha256') != rec.get('sha256')):
        chg['sha256_changed'] = True
      if prec.get('title') != rec.get('title'):
        chg['title_change'] = (prec.get('title'), rec.get('title'))
      if prec.get('uid') != rec.get('uid'):
        chg['uid_change'] = (prec.get('uid'), rec.get('uid'))
      if chg:
        entry = {'file': f, **chg}
        changed.append(entry)
  for f in pmap:
    if f not in cmap:
      removed.append(pmap[f])
  return {'added': added, 'removed': removed, 'changed': changed}

def render_changelog_section(version: str, diff: Dict[str, Any]) -> str:
  ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
  lines = [f"## {version} - {ts}"]
  if diff['added']:
    lines.append('Added:')
    for rec in diff['added']:
      lines.append(f"- {rec.get('file')} ({rec.get('title')})")
  if diff['removed']:
    lines.append('Removed:')
    for rec in diff['removed']:
      lines.append(f"- {rec.get('file')} ({rec.get('title')})")
  if diff['changed']:
    lines.append('Changed:')
    for rec in diff['changed']:
      parts = []
      if rec.get('title_change'):
        old, new = rec['title_change']
        parts.append(f'title "{old}" -> "{new}"')
      if rec.get('uid_change'):
        old, new = rec['uid_change']
        parts.append(f'uid {old} -> {new}')
      if rec.get('sha256_changed'):
        parts.append('content updated')
      lines.append(f"- {rec['file']}: {', '.join(parts)}")
  lines.append('')
  lines.append('---')
  lines.append('')
  return '\n'.join(lines)

def prepend_changelog(changelog: Path, section: str) -> None:
  existing = ''
  if changelog.exists():
    existing = changelog.read_text(encoding='utf-8')
  changelog.write_text(section + ('' if existing.startswith('# Dashboard Changelog') else '') + existing, encoding='utf-8')

def parse_args() -> argparse.Namespace:
  ap = argparse.ArgumentParser(description='Dashboard manifest diff tool')
  ap.add_argument('--prev', required=True, help='Previous manifest JSON')
  ap.add_argument('--curr', required=True, help='Current manifest JSON')
  ap.add_argument('--version', required=True, help='Version label for changelog section')
  ap.add_argument('--changelog', help='CHANGELOG_DASHBOARDS.md path to prepend section')
  ap.add_argument('--json', action='store_true', help='Emit JSON diff to stdout')
  ap.add_argument('--fail-if-no-change', action='store_true', help='Exit 3 if no differences')
  return ap.parse_args()

def main() -> int:  # pragma: no cover
  args = parse_args()
  prev_path = Path(args.prev)
  curr_path = Path(args.curr)
  if not prev_path.exists() or not curr_path.exists():
    print('One or both manifest paths missing', file=sys.stderr)
    return 2
  prev_m = load_manifest(prev_path)
  curr_m = load_manifest(curr_path)
  diff = compute_diff(prev_m, curr_m)
  changed_count = len(diff['added']) + len(diff['removed']) + len(diff['changed'])
  if args.fail_if_no_change and changed_count == 0:
    print('No dashboard changes detected')
    return 3
  if args.changelog:
    section = render_changelog_section(args.version, diff)
    prepend_changelog(Path(args.changelog), section)
  if args.json:
    print(json.dumps({'version': args.version, 'changes': diff, 'total_changes': changed_count}, indent=2))
  else:
    print(f"Dashboard changes: {changed_count} (added={len(diff['added'])} removed={len(diff['removed'])} changed={len(diff['changed'])})")
  return 0

if __name__ == '__main__':  # pragma: no cover
  raise SystemExit(main())
