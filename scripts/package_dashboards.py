"""Package Grafana dashboards into a versioned bundle.

Outputs (default dist/):
  dashboards_<version>.tar.gz
  dashboards_<version>.sha256
  dashboards_manifest_<version>.json

Manifest fields:
  version, created_utc, count, files:[{path, sha256, size_bytes, uid, title}]

Version resolution order:
  1. --version CLI argument
  2. G6_DASHBOARD_VERSION env
  3. git describe --tags (fallback to short commit hash)
  4. 'dev'

Usage:
  python scripts/package_dashboards.py --out dist/ --version 1.2.0

Integrity verify example:
  sha256sum -c dashboards_1.2.0.sha256

Design notes:
  * Ignores placeholder/example dashboards (filename contains 'placeholder').
  * Validates JSON parse and presence of uid/title fields.
  * Includes per-file checksum in manifest to enable partial distribution integrity.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DASH_DIR = REPO / 'grafana' / 'dashboards'

SKIP_SUBSTRINGS = ['placeholder']


def detect_version(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_v = os.getenv('G6_DASHBOARD_VERSION')
    if env_v:
        return env_v
    try:
        r = subprocess.run(['git','describe','--tags','--always'], capture_output=True, text=True, cwd=REPO, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return 'dev'


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def collect_dashboards() -> list[Path]:
    if not DASH_DIR.exists():
        raise SystemExit(f"Dashboards dir missing: {DASH_DIR}")
    out: list[Path] = []
    for p in DASH_DIR.glob('*.json'):
        if any(sub in p.name for sub in SKIP_SUBSTRINGS):
            continue
        out.append(p)
    return sorted(out)


def build_manifest(files: list[Path], version: str) -> dict[str, Any]:
    records = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding='utf-8', errors='ignore'))
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid JSON in {p}: {e}") from e
        uid = data.get('uid')
        title = data.get('title')
        if not uid or not title:
            print(f"[warn] Missing uid/title in {p.name}")
        sha256 = file_sha256(p)
        records.append({
            'path': str(p.relative_to(REPO)),
            'file': p.name,
            'sha256': sha256,
            'size_bytes': p.stat().st_size,
            'uid': uid,
            'title': title,
        })
    return {
        'version': version,
    'created_utc': datetime.datetime.now(datetime.UTC).isoformat().replace('+00:00','Z'),
        'count': len(records),
        'files': records,
    }


def write_bundle(files: list[Path], version: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"dashboards_{version}.tar.gz"
    with tarfile.open(archive, 'w:gz') as tf:
        for p in files:
            arcname = p.relative_to(REPO)
            tf.add(p, arcname=str(arcname))
    return archive


def write_checksum(archive: Path) -> Path:
    digest = file_sha256(archive)
    cs = archive.parent / f"{archive.name}.sha256"
    cs.write_text(f"{digest}  {archive.name}\n", encoding='utf-8')
    return cs


def main() -> int:
    ap = argparse.ArgumentParser(description='Package Grafana dashboards bundle')
    ap.add_argument('--out', default='dist', help='Output directory')
    ap.add_argument('--version', help='Explicit version override')
    ap.add_argument('--manifest-only', action='store_true', help='Only emit manifest JSON')
    args = ap.parse_args()

    version = detect_version(args.version)
    files = collect_dashboards()
    if not files:
        print('No dashboards found', file=sys.stderr)
        return 1
    manifest = build_manifest(files, version)
    out_dir = Path(args.out)
    manifest_path = out_dir / f"dashboards_manifest_{version}.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"[package] wrote manifest {manifest_path}")
    if args.manifest_only:
        return 0
    archive = write_bundle(files, version, out_dir)
    cs = write_checksum(archive)
    print(f"[package] archive={archive} checksum={cs}")
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
