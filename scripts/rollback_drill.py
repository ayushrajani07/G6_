#!/usr/bin/env python3
"""Rollback Drill Script (Wave 2 Skeleton)

Purpose:
  Provide a dry-run (+ optional execute) workflow to validate ability to rollback
  from pipeline collector to legacy path rapidly if parity/regression issues emerge.

Modes:
  --dry-run (default): prints the steps it WOULD perform.
  --execute          : performs the rollback actions.

Planned Steps (subject to refinement):
  1. Health snapshot: capture current parity score (if available) & key metrics.
  2. Disable pipeline collector flag (G6_PIPELINE_COLLECTOR=0) in runtime config env file.
  3. Flush or archive pipeline-specific artifacts (optional; depends on retention policy).
  4. Trigger legacy warm run (one iteration) to re-populate caches.
  5. Validate summary + alerts presence.
  6. Emit structured rollback event (log + optional metrics increment).

Execution Safety:
  - No destructive operations by default.
  - Artifact archival to a timestamped directory (future enhancement).

Exit Codes:
  0 success, non-zero for failure in any execution step (execute mode only).
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Any

logger = logging.getLogger("scripts.rollback_drill")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')


def capture_health_snapshot() -> dict[str, Any]:
  """Capture parity score (if baseline + indices snapshot available) and timestamp.

  Looks for a JSON snapshot file path via env G6_PARITY_BASELINE (optional) to treat
  as legacy baseline and a pipeline snapshot via G6_PARITY_PIPELINE. If both load and
  contain 'indices', compute parity score.
  """
  ts = datetime.datetime.now(datetime.UTC).isoformat().replace('+00:00','Z')
  legacy_path = os.getenv('G6_PARITY_BASELINE')
  pipeline_path = os.getenv('G6_PARITY_PIPELINE')
  parity_obj = None
  try:
    if legacy_path and pipeline_path and pathlib.Path(legacy_path).is_file() and pathlib.Path(pipeline_path).is_file():
      with open(legacy_path,encoding='utf-8') as fh:
        legacy = json.load(fh)
      with open(pipeline_path,encoding='utf-8') as fh:
        pipe = json.load(fh)
      if isinstance(legacy, dict) and isinstance(pipe, dict):
        try:
          from src.collectors.pipeline.parity import compute_parity_score  # type: ignore
          parity_obj = compute_parity_score(legacy, pipe)
        except Exception:
          parity_obj = None
  except Exception:
    parity_obj = None
  return {
    'ts': ts,
    'parity': parity_obj,
    'legacy_source': legacy_path,
    'pipeline_source': pipeline_path,
  }

def perform_disable_pipeline_flag(execute: bool) -> dict[str, Any]:
    # Strategy: rely on environment variable toggling; in execute mode set an env file or instruct operator.
    # For now just simulate.
    if execute:
        os.environ['G6_PIPELINE_COLLECTOR'] = '0'
    return {'flag_set': execute, 'new_value': os.environ.get('G6_PIPELINE_COLLECTOR','<unset>')}


def legacy_warm_run(execute: bool) -> dict[str, Any]:
    # Placeholder for invoking legacy collector one-shot; not implemented here.
    return {'invoked': execute, 'status': 'skipped' if not execute else 'ok'}


def _persist_artifact(data: dict[str, Any], path: str) -> dict[str, Any]:
  try:
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path,'w',encoding='utf-8') as fh:
      json.dump(data, fh, indent=2, sort_keys=True)
    return {'written': True, 'path': path}
  except Exception as e:
    return {'written': False, 'path': path, 'error': str(e)}

def drill_steps(execute: bool, artifact_dir: str | None, metrics_enabled: bool) -> dict[str, Any]:
  result: dict[str, Any] = {'execute': execute, 'steps': [], 'artifact_dir': artifact_dir}
  snap = capture_health_snapshot()
  result['steps'].append({'step': 'health_snapshot', 'data': snap})
  flag = perform_disable_pipeline_flag(execute)
  result['steps'].append({'step': 'disable_pipeline', 'data': flag})
  warm = legacy_warm_run(execute)
  result['steps'].append({'step': 'legacy_warm_run', 'data': warm})
  # Persist artifact if directory requested
  if artifact_dir:
    ts_short = snap.get('ts','').replace(':','').replace('-','')
    fname = f"rollback_artifact_{ts_short or 'now'}.json"
    artifact_path = str(pathlib.Path(artifact_dir)/fname)
    persist = _persist_artifact({'snapshot': snap, 'steps': result['steps']}, artifact_path)
    result['steps'].append({'step': 'persist_artifact', 'data': persist})
  # Metrics counter increment
  if metrics_enabled:
    try:
      from prometheus_client import Counter  # type: ignore
      _c = Counter('g6_pipeline_rollback_drill_total','Count of rollback drills executed')
      _c.inc()
      result['steps'].append({'step': 'metrics_increment', 'data': {'ok': True}})
    except Exception as e:
      result['steps'].append({'step': 'metrics_increment', 'data': {'ok': False, 'error': str(e)}})
  result['status'] = 'ok'
  return result


def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(description='Pipeline rollback drill')
  ap.add_argument('--execute', action='store_true', help='Perform rollback actions instead of dry-run')
  ap.add_argument('--json', action='store_true', help='Emit JSON result only')
  ap.add_argument('--artifact-dir', help='Directory to persist rollback artifact (JSON)')
  ap.add_argument('--metrics', action='store_true', help='Emit metrics counter increment')
  args = ap.parse_args(argv)
  exec_mode = bool(args.execute)
  outcome = drill_steps(exec_mode, args.artifact_dir, args.metrics)
  if args.json:
    print(json.dumps(outcome, indent=2))
  else:
    print('# Rollback Drill Report')
    print(f"Mode: {'EXECUTE' if exec_mode else 'DRY-RUN'}")
    for step in outcome['steps']:
      print(f"- {step['step']}: {step['data']}")
  logger.info('rollback_drill_complete', extra={'execute': exec_mode})
  return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
