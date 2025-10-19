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

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class ManifestFileRec(TypedDict):
  file: str
  title: NotRequired[str]
  uid: NotRequired[str]
  sha256: NotRequired[str]


class Manifest(TypedDict):
  files: list[ManifestFileRec]


class _ChangedEntryReq(TypedDict):
  file: str


class ChangedEntry(_ChangedEntryReq, total=False):
  title_change: tuple[Any, Any]
  uid_change: tuple[Any, Any]
  sha256_changed: bool


class DiffResult(TypedDict):
  added: list[ManifestFileRec]
  removed: list[ManifestFileRec]
  changed: list[ChangedEntry]


def load_manifest(path: Path) -> Manifest:
  try:
    data = json.loads(path.read_text(encoding='utf-8'))
  except Exception as e:  # noqa: BLE001 - broad to surface file+json errors uniformly
    raise SystemExit(f"Failed reading manifest {path}: {e}") from e
  files_any = data.get('files', [])
  files: list[ManifestFileRec] = []
  if isinstance(files_any, list):
    for rec in files_any:
      if isinstance(rec, dict):
        f = rec.get('file')
        if isinstance(f, str) and f:
          mf: ManifestFileRec = {'file': f}
          t = rec.get('title')
          if isinstance(t, str):
            mf['title'] = t
          u = rec.get('uid')
          if isinstance(u, str):
            mf['uid'] = u
          s = rec.get('sha256')
          if isinstance(s, str):
            mf['sha256'] = s
          files.append(mf)
  return {'files': files}

def index_files(manifest: Manifest) -> dict[str, ManifestFileRec]:
  out: dict[str, ManifestFileRec] = {}
  for rec in manifest['files']:
    out[rec['file']] = rec
  return out

def compute_diff(prev: Manifest, curr: Manifest) -> DiffResult:
  pmap = index_files(prev)
  cmap = index_files(curr)
  added: list[ManifestFileRec] = []
  removed: list[ManifestFileRec] = []
  changed: list[ChangedEntry] = []
  for f, rec in cmap.items():
    if f not in pmap:
      added.append(rec)
    else:
      prec = pmap[f]
      chg: ChangedEntry = {'file': f}
      if prec.get('sha256') != rec.get('sha256'):
        chg['sha256_changed'] = True
      if prec.get('title') != rec.get('title'):
        chg['title_change'] = (prec.get('title'), rec.get('title'))
      if prec.get('uid') != rec.get('uid'):
        chg['uid_change'] = (prec.get('uid'), rec.get('uid'))
      # keep only if any change aside from 'file'
      if any(k in chg for k in ('sha256_changed', 'title_change', 'uid_change')):
        changed.append(chg)
  removed.extend(pmap[f] for f in pmap if f not in cmap)
  return {'added': added, 'removed': removed, 'changed': changed}

def render_changelog_section(version: str, diff: DiffResult) -> str:
  ts = datetime.datetime.now(datetime.UTC).isoformat()
  lines: list[str] = [f"## {version} - {ts}"]
  if diff['added']:
    lines.append('Added:')
    lines.extend(f"- {rec_add.get('file')} ({rec_add.get('title')})" for rec_add in diff['added'])
  if diff['removed']:
    lines.append('Removed:')
    lines.extend(f"- {rec_rem.get('file')} ({rec_rem.get('title')})" for rec_rem in diff['removed'])
  if diff['changed']:
    lines.append('Changed:')
    for ch in diff['changed']:
      parts: list[str] = []
      if 'title_change' in ch:
        old, new = ch['title_change']
        parts.append(f'title "{old}" -> "{new}"')
      if 'uid_change' in ch:
        old, new = ch['uid_change']
        parts.append(f'uid {old} -> {new}')
      if ch.get('sha256_changed'):
        parts.append('content updated')
      lines.append(f"- {ch['file']}: {', '.join(parts)}")
  lines.append('')
  lines.append('---')
  lines.append('')
  return '\n'.join(lines)

def prepend_changelog(changelog: Path, section: str) -> None:
  existing = ''
  if changelog.exists():
    existing = changelog.read_text(encoding='utf-8')
  # Preserve original behavior: prepend section verbatim.
  changelog.write_text(section + existing, encoding='utf-8')

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
  dr = compute_diff(prev_m, curr_m)
  changed_count = len(dr['added']) + len(dr['removed']) + len(dr['changed'])
  if args.fail_if_no_change and changed_count == 0:
    print('No dashboard changes detected')
    return 3
  if args.changelog:
    section = render_changelog_section(args.version, dr)
    prepend_changelog(Path(args.changelog), section)
  if args.json:
    print(json.dumps({'version': args.version, 'changes': dr, 'total_changes': changed_count}, indent=2))
  else:
    print(
      "Dashboard changes: "
      f"{changed_count} (added={len(dr['added'])} removed={len(dr['removed'])} changed={len(dr['changed'])})"
    )
  return 0

if __name__ == '__main__':  # pragma: no cover
  raise SystemExit(main())
