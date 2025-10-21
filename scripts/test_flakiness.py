"""Flaky test detector & slow test profiler.

Strategy:
  * Invoke pytest multiple times with JSON report (requires pytest >=7)
  * Aggregate outcome matrix per test nodeid
  * Identify flaky tests (both pass & fail across runs)
  * Compute average duration for successful runs; output top N slow tests
  * Optional: emit rerun snippet recommending pytest-rerunfailures config

Limitations:
  * Uses `--maxfail=1` avoided to capture full set each run
  * Assumes stable test collection order; nodeid used as key
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run_pytest(json_path: Path, extra: list[str]) -> int:
  cmd = [sys.executable, '-m', 'pytest', '--json-report', '--json-report-file', str(json_path), '-q'] + extra
  proc = subprocess.run(cmd, capture_output=True, text=True)
  return proc.returncode

def load_report(path: Path) -> dict[str, Any]:
  return json.loads(path.read_text(encoding='utf-8'))

def aggregate(reports: list[dict[str, Any]]):
  matrix: dict[str, dict[str, Any]] = {}
  for rep in reports:
    tests = rep.get('tests', [])
    for t in tests:
      nodeid = t.get('nodeid')
      if not nodeid:
        continue
      entry = matrix.setdefault(nodeid, {'outcomes': [], 'durations': []})
      outcome = t.get('outcome')
      entry['outcomes'].append(outcome)
      dur = t.get('duration')
      if isinstance(dur, (int, float)) and outcome == 'passed':
        entry['durations'].append(dur)
  return matrix

def classify(matrix: dict[str, dict[str, Any]]):
  flaky = {}
  always_fail = {}
  stable = {}
  for nodeid, data in matrix.items():
    outs = data['outcomes']
    uniq = set(outs)
    if 'passed' in uniq and 'failed' in uniq:
      flaky[nodeid] = data
    elif uniq == {'failed'}:
      always_fail[nodeid] = data
    else:
      stable[nodeid] = data
  return flaky, always_fail, stable

def slow_tests(matrix: dict[str, dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
  rows = []
  for nodeid, data in matrix.items():
    durs = data['durations']
    if len(durs) >= 1:
      rows.append({
        'nodeid': nodeid,
        'avg_duration': statistics.mean(durs),
        'runs': len(durs)
      })
  rows.sort(key=lambda r: r['avg_duration'], reverse=True)
  return rows[:top_n]

def parse_args():
  ap = argparse.ArgumentParser(description='Flaky test detector')
  ap.add_argument('--runs', type=int, default=3, help='Number of pytest runs')
  ap.add_argument('--extra', nargs='*', default=[], help='Extra pytest args')
  ap.add_argument('--top-slow', type=int, default=10, help='List top N slow tests')
  ap.add_argument('--json', action='store_true', help='Emit JSON summary')
  ap.add_argument('--fail-on-flaky', action='store_true', help='Exit non-zero if any flaky tests found')
  return ap.parse_args()

def main() -> int:  # pragma: no cover
  args = parse_args()
  reports: list[dict[str, Any]] = []
  with tempfile.TemporaryDirectory() as td:
    for i in range(args.runs):
      rpt = Path(td) / f'report_{i}.json'
      rc = run_pytest(rpt, args.extra)
      if not rpt.exists():
        print(f"Run {i} produced no report (rc={rc})", file=sys.stderr)
        return 2
      reports.append(load_report(rpt))
  matrix = aggregate(reports)
  flaky, always_fail, stable = classify(matrix)
  slow = slow_tests(matrix, args.top_slow)

  summary = {
    'runs': args.runs,
    'total_tests': len(matrix),
    'flaky_count': len(flaky),
    'always_fail_count': len(always_fail),
    'stable_count': len(stable),
    'flaky': {k: v['outcomes'] for k, v in flaky.items()},
    'always_fail': {k: v['outcomes'] for k, v in always_fail.items()},
    'top_slow': slow,
  }
  if args.json:
    print(json.dumps(summary, indent=2))
  else:
    print(f"Flaky tests: {len(flaky)} | Always fail: {len(always_fail)} | Total: {len(matrix)}")
    if flaky:
      print("\nFlaky detail:")
      for k, outs in summary['flaky'].items():
        print(f"  {k}: {outs}")
    if slow:
      print("\nTop slow tests (avg seconds):")
      for row in slow:
        print(f"  {row['avg_duration']:.3f}s {row['nodeid']} (runs={row['runs']})")
  if args.fail_on_flaky and flaky:
    return 3
  return 0

if __name__ == '__main__':  # pragma: no cover
  raise SystemExit(main())
