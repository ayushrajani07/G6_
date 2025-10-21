"""Generate a lightweight provenance statement for release artifacts.

Schema v0 (subject to additive change only; existing fields stable):
{
  "schema": "g6.provenance.v0",
  "generated_at_utc": ISO8601Z,
  "builder": {"tool": "g6-release-automation", "version": <git_describe_or_env>},
  "source": {"git_commit": sha, "git_ref": ref/tag, "dirty": bool},
  "environment": {"python_version": str, "platform": str, "ci": str},
  "release": {"version": resolved_version},
  "artifacts": [ { name, path, sha256, size_bytes, type } ... ],
  "signing": {"archive_algorithm": algo|None, "public_key_b64": str|None, "signature_file": path|None},
  "metrics_snapshot": { diff_ratio_threshold, queue_latency_warn_s, queue_latency_crit_s }
}

Usage:
  python scripts/gen_provenance.py --version 1.2.3 \
    --artifact dist/dashboards_1.2.3.tar.gz:tar+gzip \
    --artifact dist/dashboards_manifest_1.2.3.json:json \
    --artifact dist/sbom_1.2.3.json:json \
    --output dist/provenance_1.2.3.json

If --auto discover is specified, attempts to infer standard artifact set in dist/.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

DEFAULT_THRESHOLDS: dict[str, float] = {
    "diff_ratio_threshold": 0.85,
    "queue_latency_warn_s": 0.4,
    "queue_latency_crit_s": 0.75,
}

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def git(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(['git'] + cmd, cwd=REPO, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        return None
    return None

def detect_source() -> dict[str, Any]:
    commit = git(['rev-parse','HEAD']) or 'unknown'
    ref = os.getenv('GITHUB_REF') or git(['symbolic-ref','--short','HEAD']) or 'unknown'
    dirty = bool(git(['status','--porcelain']))
    return {"git_commit": commit, "git_ref": ref, "dirty": dirty}

def detect_builder() -> dict[str, str]:
    ver = git(['describe','--tags','--always']) or os.getenv('G6_VERSION') or 'dev'
    return {"tool": "g6-release-automation", "version": ver}

def detect_env() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "ci": 'github-actions' if os.getenv('GITHUB_ACTIONS') else 'local'
    }

def parse_artifact(spec: str) -> dict[str, Any]:
    # format path[:type]
    if ':' in spec:
        path, atype = spec.split(':',1)
    else:
        path, atype = spec, 'file'
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Artifact missing: {path}")
    return {
        'name': p.name,
        'path': str(p),
        'sha256': sha256_file(p),
        'size_bytes': p.stat().st_size,
        'type': atype,
    }

def auto_discover(version: str) -> list[dict[str, Any]]:
    dist = REPO / 'dist'
    if not dist.exists():
        return []
    patterns = [
        f'dashboards_{version}.tar.gz',
        f'dashboards_manifest_{version}.json',
        f'sbom_{version}.json',
        f'provenance_{version}.json',  # self (if regenerating)
    ]
    out: list[dict] = []
    for pat in patterns:
        p = dist / pat
        if p.exists():
            atype = 'tar+gzip' if pat.endswith('.tar.gz') else 'json'
            out.append(parse_artifact(f"{p}:{atype}"))
    return out

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Generate provenance statement')
    ap.add_argument('--version', required=True)
    ap.add_argument('--artifact', action='append', help='Artifact spec path[:type] (repeatable)')
    ap.add_argument('--output', help='Output path (default dist/provenance_<version>.json)')
    ap.add_argument('--auto', action='store_true', help='Auto discover standard artifacts in dist/')
    ap.add_argument('--with-signing-info', action='store_true', help='Include signing metadata if archive signature detected')
    return ap.parse_args()

def main() -> int:  # pragma: no cover
    args = parse_args()
    version = args.version
    artifacts: list[dict[str, Any]] = []
    if args.artifact:
        for spec in args.artifact:
            artifacts.append(parse_artifact(spec))
    if args.auto:
        existing = {a['name'] for a in artifacts}
        for auto in auto_discover(version):
            if auto['name'] not in existing:
                artifacts.append(auto)
    # Deduplicate by path
    seen = {}
    final = []
    for a in artifacts:
        if a['path'] in seen:
            continue
        seen[a['path']] = True
        final.append(a)

    signing_block: dict[str, Any] | None = None
    if args.with_signing_info:
        # Heuristic: find dashboards_<ver>.tar.gz and its .sig
        arc = next((a for a in final if a['name'] == f'dashboards_{version}.tar.gz'), None)
        if arc:
            sig_path = Path(arc['path'] + '.sig')
            if sig_path.exists():
                # Attempt to read sign metadata if previously printed JSON (best-effort skipped)
                signing_block = {
                    'archive_algorithm': os.getenv('G6_SIGN_KEY') and 'ed25519' or (os.getenv('G6_SIGN_SECRET') and 'hmac-sha256') or None,
                    'public_key_b64': os.getenv('G6_SIGN_PUB'),
                    'signature_file': str(sig_path),
                }
    provenance = {
        'schema': 'g6.provenance.v0',
        'generated_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
        'builder': detect_builder(),
        'source': detect_source(),
        'environment': detect_env(),
        'release': {'version': version},
        'artifacts': final,
        'signing': signing_block,
        'metrics_snapshot': DEFAULT_THRESHOLDS,
    }

    out_path = Path(args.output) if args.output else (REPO / 'dist' / f'provenance_{version}.json')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(f"[provenance] wrote {out_path}")
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
