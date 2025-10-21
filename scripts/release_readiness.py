"""Release readiness gate script.

Purpose: Fast pre-release validation of critical surfaces.
Checks:
  1. Required environment documentation present for all referenced G6_ vars.
  2. Deprecated/removed artifacts absent (e.g., scripts/run_live.py).
  3. SSE security metrics & profiling histograms (if enabled) registered (optionally).
  4. Basic SSE endpoint health (if G6_UNIFIED_HTTP=1) returns hello/full_snapshot quickly.
  5. Prometheus metrics endpoint exposes core counters (if available).
  6. Optional short benchmark run (flag) to assert diff build within budget.

Usage:
  python scripts/release_readiness.py --strict
  python scripts/release_readiness.py --check-sse --check-metrics
  python scripts/release_readiness.py --bench --bench-cycles 100

Exit Codes:
  0 success, non-zero on first failure (details printed).
"""
from __future__ import annotations

import argparse
import http.client
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CORE_ENV_VARS = [
    'G6_SSE_API_TOKEN','G6_SSE_IP_ALLOW','G6_SSE_MAX_CONNECTIONS','G6_SSE_ALLOW_ORIGIN',
    'G6_SSE_IP_CONNECT_RATE','G6_SSE_UA_ALLOW','G6_SSE_MAX_EVENT_BYTES','G6_SSE_EVENTS_PER_SEC',
    'G6_SSE_STRUCTURED','G6_DISABLE_RESYNC_HTTP','G6_SSE_PERF_PROFILE'
]
REQUIRED_METRICS = [
    'g6_sse_http_connections_total','g6_sse_http_events_sent_total','g6_sse_http_event_size_bytes',
    'g6_sse_http_rate_limited_total','g6_sse_http_forbidden_ua_total'
]

DEPRECATED_PATHS_ABSENT = [
    REPO / 'scripts' / 'run_live.py'
]

ENV_DOC_FILE = REPO / 'docs' / 'env_dict.md'

class ReadinessError(Exception):
    pass

def load_env_doc_lines() -> list[str]:
    if not ENV_DOC_FILE.exists():
        raise ReadinessError(f"env doc missing: {ENV_DOC_FILE}")
    return ENV_DOC_FILE.read_text(encoding='utf-8', errors='ignore').splitlines()

def check_env_docs(strict: bool) -> None:
    lines = load_env_doc_lines()
    text = '\n'.join(lines)
    missing = [v for v in CORE_ENV_VARS if v not in text]
    if missing:
        msg = f"Missing env var docs: {missing}" if strict else f"[warn] Missing env var docs: {missing}"
        if strict:
            raise ReadinessError(msg)
        else:
            print(msg)

def check_deprecations() -> None:
    for p in DEPRECATED_PATHS_ABSENT:
        if p.exists():
            raise ReadinessError(f"Deprecated artifact present: {p}")

# --- SSE live checks ------------------------------------------------------

def fetch_sse_events(host: str, port: int, path: str = '/summary/events', timeout: float = 5.0, want: int = 2) -> list[str]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request('GET', path)
    resp = conn.getresponse()
    if resp.status != 200:
        raise ReadinessError(f"SSE status {resp.status}")
    raw = resp.read(4096).decode('utf-8','ignore')
    events = [ln.split(':',1)[1].strip() for ln in raw.split('\n') if ln.startswith('event:')]
    return events[:want]

def check_sse_endpoint(port: int = 9329) -> None:
    # Expect hello or full_snapshot quickly
    events = fetch_sse_events('127.0.0.1', port)
    if not any(e in ('hello','full_snapshot') for e in events):
        raise ReadinessError(f"SSE did not emit expected initial events: {events}")

# --- Metrics endpoint -----------------------------------------------------

def fetch_metrics(port: int = 9325, timeout: float = 3.0) -> str:
    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        conn.request('GET','/')
        r = conn.getresponse()
        if r.status != 200:
            raise ReadinessError(f"metrics status {r.status}")
        body = r.read().decode('utf-8','ignore')
        return body
    except OSError as e:
        raise ReadinessError(f"metrics fetch error: {e}")


def check_metrics_presence() -> None:
    body = fetch_metrics()
    missing = [m for m in REQUIRED_METRICS if m not in body]
    if missing:
        raise ReadinessError(f"Missing required metrics: {missing}")

# --- Optional benchmark smoke --------------------------------------------

def run_bench_smoke(cycles: int) -> None:
    from scripts.bench_sse_loop import run_bench  # type: ignore
    run_bench(cycles, panel_count=30, change_ratio=0.1, structured=False)

def bench_budget(p95_limit_ms: float, cycles: int, panels: int, change_ratio: float, structured: bool) -> None:
    """Invoke bench_sse_loop via subprocess (isolated) and enforce p95 budget."""
    cmd = [sys.executable, 'scripts/bench_sse_loop.py', '--cycles', str(cycles), '--panels', str(panels), '--change-ratio', str(change_ratio)]
    if structured:
        cmd.append('--structured')
    cmd.extend(['--json'])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0,2):
        raise ReadinessError(f"benchmark invocation failed rc={proc.returncode}: {proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ReadinessError('benchmark JSON parse failed')
    p95 = data['bench']['per_process_ms_p95']
    if p95 > p95_limit_ms:
        raise ReadinessError(f"bench p95 {p95:.2f}ms > budget {p95_limit_ms}ms")

# -------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description='Release readiness gate')
    ap.add_argument('--strict', action='store_true', help='Fail if any env doc missing')
    ap.add_argument('--check-env', action='store_true', help='Check env docs only')
    ap.add_argument('--check-deprecations', action='store_true')
    ap.add_argument('--check-sse', action='store_true', help='Check SSE endpoint (assumes unified server active)')
    ap.add_argument('--check-metrics', action='store_true', help='Verify metrics endpoint & required metrics')
    ap.add_argument('--bench', action='store_true', help='Run small benchmark smoke (not pass/fail)')
    ap.add_argument('--bench-cycles', type=int, default=80)
    ap.add_argument('--perf-budget-p95-ms', type=float, help='Enforce benchmark p95 per-process latency (ms)')
    ap.add_argument('--perf-budget-cycles', type=int, default=160)
    ap.add_argument('--perf-budget-panels', type=int, default=60)
    ap.add_argument('--perf-budget-change-ratio', type=float, default=0.12)
    ap.add_argument('--perf-budget-structured', action='store_true')
    args = ap.parse_args()

    try:
        if args.check_env or args.strict:
            check_env_docs(strict=args.strict)
        if args.check_deprecations:
            check_deprecations()
        if args.check_sse:
            check_sse_endpoint()
        if args.check_metrics:
            check_metrics_presence()
        if args.bench:
            run_bench_smoke(args.bench_cycles)
        if args.perf_budget_p95_ms is not None:
            bench_budget(args.perf_budget_p95_ms, args.perf_budget_cycles, args.perf_budget_panels, args.perf_budget_change_ratio, args.perf_budget_structured)
    except ReadinessError as e:
        print(f"[readiness:FAIL] {e}")
        return 1
    print('[readiness:OK]')
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
