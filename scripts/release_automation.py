"""Release automation orchestrator.

Aggregates key pre-release steps into a single, CI-friendly command.

Pipeline stages (current & future):
  1. Readiness gate (strict env + deprecations + optional perf budget)
  2. Dashboard packaging (manifest + archive + checksum)
  3. (Optional now / future) Dashboard diff & changelog update
  4. (Optional) Signing (if sign script & key present)
  5. (Optional) SBOM generation
  6. Emit JSON summary for downstream release job steps

Design goals:
  * Fail-fast with clear stage name & message
  * Allow soft-fail for optional stages (--allow-soft-fail <stage>)
  * Output machine parsable JSON ONLY to stdout on success (unless --verbose)
  * Non-zero exit if any mandatory stage fails

JSON summary schema (example):
{
  "ok": true,
  "version": "1.2.3",
  "stages": {
  "readiness": {"ok": true, "details": "[readiness:OK]"},
  "dashboards": {"ok": true, "manifest": "dist/dashboards_manifest_1.2.3.json", "archive": "dist/dashboards_1.2.3.tar.gz"},
  "sign": {"ok": false, "skipped": true, "reason": "no key"},
  "sbom": {"ok": true, "path": "dist/sbom.json"}
  }
}

Exit codes:
  0 success (all mandatory ok)
  2 readiness failed
  3 packaging failed
  4 signing failed (mandatory)
  5 sbom failed (mandatory when requested)
  7 generic stage failure
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

def run_cmd(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
  return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def detect_version() -> str:
  # Reuse logic from package_dashboards detect order (env or git) but simplified
  env_v = os.getenv('G6_VERSION') or os.getenv('G6_DASHBOARD_VERSION')
  if env_v:
    return env_v
  try:
    r = run_cmd(['git','describe','--tags','--always'])
    if r.returncode == 0:
      return r.stdout.strip()
  except Exception:
    pass
  return 'dev'

def stage_readiness(args) -> dict[str, Any]:
  cmd = [sys.executable, 'scripts/release_readiness.py', '--check-env', '--check-deprecations', '--strict']
  if args.perf_budget_p95_ms is not None:
    cmd.extend([
      '--perf-budget-p95-ms', str(args.perf_budget_p95_ms),
      '--perf-budget-cycles', str(args.perf_budget_cycles),
      '--perf-budget-panels', str(args.perf_budget_panels),
      '--perf-budget-change-ratio', str(args.perf_budget_change_ratio)
    ])
    if args.perf_budget_structured:
      cmd.append('--perf-budget-structured')
  r = run_cmd(cmd)
  ok = r.returncode == 0
  return {
    'ok': ok,
    'rc': r.returncode,
    'stdout': r.stdout.strip(),
    'stderr': r.stderr.strip(),
  }

def stage_dashboards(args, version: str) -> dict[str, Any]:
  out_dir = args.out
  cmd = [sys.executable, 'scripts/package_dashboards.py', '--out', out_dir, '--version', version]
  if args.manifest_only:
    cmd.append('--manifest-only')
  r = run_cmd(cmd)
  ok = r.returncode == 0
  manifest = None
  archive = None
  checksum = None
  if ok:
    # Discover produced files
    d = Path(out_dir)
    manifest = str(next(d.glob(f'dashboards_manifest_{version}.json'), None))
    arc = next(d.glob(f'dashboards_{version}.tar.gz'), None)
    if arc:
      archive = str(arc)
      cs = Path(archive + '.sha256')
      if cs.exists():
        checksum = str(cs)
  return {
    'ok': ok,
    'rc': r.returncode,
    'manifest': manifest,
    'archive': archive,
    'checksum': checksum,
    'stdout': r.stdout.strip(),
    'stderr': r.stderr.strip(),
  }

def stage_sign(args, archive_path: str | None) -> dict[str, Any]:
  if not archive_path:
    return {'ok': True, 'skipped': True, 'reason': 'no archive'}
  if not args.sign:
    return {'ok': True, 'skipped': True, 'reason': 'sign not requested'}
  if not shutil.which(sys.executable):  # trivial always true
    return {'ok': False, 'stderr': 'python missing'}
  script = REPO / 'scripts' / 'sign_dashboards.py'
  if not script.exists():
    return {'ok': True, 'skipped': True, 'reason': 'sign script absent'}
  cmd = [sys.executable, str(script), '--archive', archive_path]
  r = run_cmd(cmd)
  return {
    'ok': r.returncode == 0,
    'rc': r.returncode,
    'stdout': r.stdout.strip(),
    'stderr': r.stderr.strip(),
  }

def stage_sbom(args, version: str) -> dict[str, Any]:
  if not args.sbom:
    return {'ok': True, 'skipped': True}
  out_dir = Path(args.out)
  out_dir.mkdir(parents=True, exist_ok=True)
  target = out_dir / f'sbom_{version}.json'
  cmd = [sys.executable, 'scripts/gen_sbom.py', '--output', str(target)]
  r = run_cmd(cmd)
  return {
    'ok': r.returncode == 0,
    'rc': r.returncode,
    'path': str(target) if target.exists() else None,
    'stdout': r.stdout.strip(),
    'stderr': r.stderr.strip(),
  }

def parse_args() -> argparse.Namespace:
  ap = argparse.ArgumentParser(description='G6 Release Automation Orchestrator')
  ap.add_argument('--out', default='dist', help='Output directory for artifacts')
  ap.add_argument('--perf-budget-p95-ms', type=float, help='Enable readiness benchmark budget')
  ap.add_argument('--perf-budget-cycles', type=int, default=160)
  ap.add_argument('--perf-budget-panels', type=int, default=60)
  ap.add_argument('--perf-budget-change-ratio', type=float, default=0.12)
  ap.add_argument('--perf-budget-structured', action='store_true')
  ap.add_argument('--manifest-only', action='store_true', help='Only build manifest (no archive)')
  ap.add_argument('--sign', action='store_true', help='Attempt signing stage')
  ap.add_argument('--sbom', action='store_true', help='Generate SBOM artifact')
  ap.add_argument('--provenance', action='store_true', help='Generate provenance statement')
  ap.add_argument('--allow-soft-fail', action='append', default=[], help='Stage name allowed to fail without failing pipeline (e.g. sign,sbom)')
  ap.add_argument('--version', help='Explicit version override')
  ap.add_argument('--verbose', action='store_true')
  return ap.parse_args()

def main() -> int:  # pragma: no cover - exercised via integration
  args = parse_args()
  version = args.version or detect_version()
  summary: dict[str, Any] = {
    'version': version,
    'stages': {},
  }
  # Stage: readiness
  readiness = stage_readiness(args)
  summary['stages']['readiness'] = {k: v for k, v in readiness.items() if k not in ('stdout','stderr') or args.verbose}
  if not readiness['ok']:
    summary['ok'] = False
    code = 2
    print(json.dumps(summary, indent=2))
    return code
  # Stage: dashboards
  dashboards = stage_dashboards(args, version)
  summary['stages']['dashboards'] = {k: v for k, v in dashboards.items() if k not in ('stdout','stderr') or args.verbose}
  if not dashboards['ok']:
    summary['ok'] = False
    code = 3
    print(json.dumps(summary, indent=2))
    return code
  # Stage: sign (optional)
  sign_res = stage_sign(args, dashboards.get('archive'))
  summary['stages']['sign'] = {k: v for k, v in sign_res.items() if k not in ('stdout','stderr') or args.verbose}
  if not sign_res.get('ok') and 'sign' not in args.allow_soft_fail:
    summary['ok'] = False
    print(json.dumps(summary, indent=2))
    return 4
  # Stage: sbom (optional)
  sbom_res = stage_sbom(args, version)
  summary['stages']['sbom'] = {k: v for k, v in sbom_res.items() if k not in ('stdout','stderr') or args.verbose}
  if not sbom_res.get('ok') and 'sbom' not in args.allow_soft_fail:
    summary['ok'] = False
    print(json.dumps(summary, indent=2))
    return 5

  # Stage: provenance (optional, depends on dashboards + sbom presence)
  prov_res: dict[str, Any] = {'ok': True, 'skipped': True}
  if args.provenance:
    prov_cmd = [
      sys.executable, 'scripts/gen_provenance.py', '--version', version,
      '--auto', '--with-signing-info'
    ]
    # Ensure provenance ends up in dist automatically
    r = run_cmd(prov_cmd)
    prov_ok = r.returncode == 0
    prov_res = {
      'ok': prov_ok,
      'rc': r.returncode,
      'stdout': r.stdout.strip(),
      'stderr': r.stderr.strip(),
    }
    if not prov_ok and 'provenance' not in args.allow_soft_fail:
      summary['stages']['provenance'] = {k: v for k, v in prov_res.items() if k not in ('stdout','stderr') or args.verbose}
      summary['ok'] = False
      print(json.dumps(summary, indent=2))
      return 6
  summary['stages']['provenance'] = {k: v for k, v in prov_res.items() if k not in ('stdout','stderr') or args.verbose}

  summary['ok'] = True
  print(json.dumps(summary, indent=2))
  return 0

if __name__ == '__main__':  # pragma: no cover
  raise SystemExit(main())
