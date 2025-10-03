#!/usr/bin/env python3
"""Unified developer tooling CLI for G6 platform.
(DEPRECATION NOTICE) Prefer `python scripts/g6.py` for new workflows.
Set G6_SUPPRESS_LEGACY_CLI=1 to silence this warning.

Subcommands:
    run-once        Run a single mock collection cycle (orchestrator path)
    dashboard       Continuous mock dashboard run using orchestrator cycle
  view-status     Pretty-print a runtime status JSON file continuously (tail)
  validate-status Validate a runtime status JSON blob against lightweight schema
  full-tests      Convenience wrapper to run core + optional test suites
    summary         Launch the Rich/ASCII summarizer view
    simulate-status Generate a realistic runtime_status.json for demo/testing
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path

_warned = False

def _warn():
    global _warned
    if _warned:
        return
    if os.getenv('G6_SUPPRESS_LEGACY_CLI','').lower() in ('1','true','yes','on'):
        return
    print('[DEPRECATED] dev_tools.py will migrate into g6 CLI. Use `g6 summary` / `g6 simulate` etc. Set G6_SUPPRESS_LEGACY_CLI=1 to silence.', file=sys.stderr)
    _warned = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.schema.runtime_status_validator import validate_runtime_status  # noqa: E402
from src.orchestrator.bootstrap import bootstrap_runtime  # type: ignore  # noqa: E402
from src.orchestrator.cycle import run_cycle  # type: ignore  # noqa: E402
from src.orchestrator.context import RuntimeContext  # type: ignore  # noqa: E402

DEFAULT_CONFIG = 'config/g6_config.json'


def _common_status_args(p: argparse.ArgumentParser):
    p.add_argument('--status-file', default='runtime_status.json', help='Path to runtime status JSON file')
    p.add_argument('--interval', type=int, default=3, help='Collection interval seconds')


def _bootstrap(config_path: str) -> tuple[RuntimeContext, callable]:  # type: ignore[name-defined]
    ctx, metrics_stop = bootstrap_runtime(config_path)
    # Derive index_params heuristic if missing
    try:
        raw_cfg = ctx.config.raw if hasattr(ctx.config, 'raw') else {}
        if ctx.index_params is None:
            idx_params = raw_cfg.get('index_params') or raw_cfg.get('indices') or {}
            if isinstance(idx_params, dict) and idx_params:
                ctx.index_params = idx_params  # type: ignore[assignment]
    except Exception:
        pass
    return ctx, metrics_stop


def cmd_run_once(args: argparse.Namespace) -> int:
    os.environ.setdefault('G6_FORCE_MARKET_OPEN', '1')  # ensure cycle executes in mock context
    try:
        ctx, metrics_stop = _bootstrap(args.config)
    except Exception as e:  # noqa: BLE001
        print(f"Bootstrap failed: {e}")
        return 2
    try:
        run_cycle(ctx)
    except Exception as e:  # noqa: BLE001
        print(f"Cycle error: {e}")
        return 3
    finally:
        try:
            metrics_stop()
        except Exception:
            pass
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    os.environ.setdefault('G6_FORCE_MARKET_OPEN', '1')
    try:
        ctx, metrics_stop = _bootstrap(args.config)
    except Exception as e:  # noqa: BLE001
        print(f"Bootstrap failed: {e}")
        return 2
    cycles = args.cycles
    try:
        for i in range(cycles if cycles > 0 else 1_000_000):
            start = time.time()
            try:
                run_cycle(ctx)
            except Exception as e:  # noqa: BLE001
                print(f"Cycle error: {e}")
                return 3
            if not args.no_view:
                try:
                    data = json.loads(Path(args.status_file).read_text())
                    print(f"Cycle {i}: cycle={data.get('cycle')} elapsed={data.get('elapsed')}s indices={data.get('indices')}")
                except Exception:
                    print(f'Cycle {i}: (status read failed)')
            if cycles > 0 and i + 1 >= cycles:
                break
            elapsed = time.time() - start
            sleep_for = max(0.0, args.sleep_between - elapsed)
            if sleep_for:
                time.sleep(sleep_for)
    finally:
        try:
            metrics_stop()
        except Exception:
            pass
    return 0


def cmd_view_status(args: argparse.Namespace) -> int:
    path = Path(args.status_file)
    if not path.exists():
        print(f"Status file {path} does not exist yet. Waiting...")
    last = None
    try:
        while True:
            if path.exists():
                try:
                    raw = path.read_text()
                    if raw != last:
                        last = raw
                        data = json.loads(raw)
                        print(json.dumps(data, indent=2))
                except Exception as e:  # noqa: BLE001
                    print(f"Read/parse error: {e}")
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        return 0


def cmd_validate_status(args: argparse.Namespace) -> int:
    payload: str
    if args.file:
        payload = Path(args.file).read_text()
    else:
        payload = sys.stdin.read()
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as e:  # noqa: BLE001
        print(f"Invalid JSON: {e}")
        return 2
    errors = validate_runtime_status(obj)
    if errors:
        print("INVALID:")
        for e in errors:
            print(f" - {e}")
        return 1
    print("VALID")
    return 0


def cmd_full_tests(args: argparse.Namespace) -> int:
    # Run core tests first
    import subprocess
    env = os.environ.copy()
    base_cmd = [sys.executable, '-m', 'pytest', '-q']
    print('Running core test suite...')
    r1 = subprocess.run(base_cmd, env=env)
    if r1.returncode != 0:
        return r1.returncode
    print('Running optional/slow tests...')
    env['G6_ENABLE_OPTIONAL_TESTS'] = '1'
    env['G6_ENABLE_SLOW_TESTS'] = '1'
    r2 = subprocess.run(base_cmd, env=env)
    return r2.returncode


def cmd_summary(args: argparse.Namespace) -> int:
    """Launch the summarizer UI (Rich if available, else ASCII)."""
    cmd = [sys.executable, str(ROOT / 'scripts' / 'summary_view.py')]
    if args.no_rich:
        cmd.append('--no-rich')
    cmd += ['--status-file', args.status_file, '--metrics-url', args.metrics_url, '--refresh', str(args.refresh)]
    if args.compact:
        cmd.append('--compact')
    if args.low_contrast:
        cmd.append('--low-contrast')
    return subprocess.call(cmd)


def cmd_simulate_status(args: argparse.Namespace) -> int:
    """Run a lightweight simulator that writes runtime_status.json periodically."""
    cmd = [sys.executable, str(ROOT / 'scripts' / 'status_simulator.py'),
           '--status-file', args.status_file,
           '--indices', ','.join(args.indices),
           '--interval', str(args.interval),
           '--refresh', str(args.refresh)]
    if args.cycles:
        cmd += ['--cycles', str(args.cycles)]
    if args.open_market:
        cmd.append('--open-market')
    if args.with_analytics:
        cmd.append('--with-analytics')
    return subprocess.call(cmd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='dev_tools', description='Unified developer tooling for G6')
    p.add_argument('--config', default=DEFAULT_CONFIG, help='Path to platform config file (default: %(default)s)')
    sub = p.add_subparsers(dest='cmd', required=True)

    rp = sub.add_parser('run-once', help='Execute a single mock cycle')
    _common_status_args(rp)
    rp.set_defaults(func=cmd_run_once)

    dp = sub.add_parser('dashboard', help='Repeated mock cycles printing summary')
    _common_status_args(dp)
    dp.add_argument('--cycles', type=int, default=5, help='Number of cycles (0=unbounded)')
    dp.add_argument('--sleep-between', type=float, default=1.0, help='Sleep between cycles (seconds)')
    dp.add_argument('--no-view', action='store_true', help='Suppress inline status printing')
    dp.set_defaults(func=cmd_dashboard)

    vp = sub.add_parser('view-status', help='Continuously pretty-print a status file')
    vp.add_argument('--status-file', default='runtime_status.json')
    vp.add_argument('--refresh', type=float, default=1.5, help='Polling refresh seconds')
    vp.set_defaults(func=cmd_view_status)

    sp = sub.add_parser('validate-status', help='Validate runtime status JSON (file or stdin)')
    sp.add_argument('--file', help='Path to JSON file (otherwise read stdin)')
    sp.set_defaults(func=cmd_validate_status)

    tp = sub.add_parser('full-tests', help='Run core then optional+slow test suites')
    tp.set_defaults(func=cmd_full_tests)

    sp = sub.add_parser('summary', help='Launch terminal summarizer')
    sp.add_argument('--status-file', '--runtime-status-file', dest='status_file', default='data/runtime_status.json')
    sp.add_argument('--metrics-url', default='http://127.0.0.1:9108/metrics')
    sp.add_argument('--refresh', type=float, default=1.0)
    sp.add_argument('--no-rich', action='store_true')
    sp.add_argument('--compact', action='store_true', help='Compact layout with fewer details')
    sp.add_argument('--low-contrast', action='store_true', help='Use neutral borders/colors for low-contrast terminals')
    sp.set_defaults(func=cmd_summary)

    sim = sub.add_parser('simulate-status', help='Write a realistic runtime_status.json for demo/testing')
    sim.add_argument('--status-file', '--runtime-status-file', dest='status_file', default='data/runtime_status.json')
    sim.add_argument('--indices', nargs='+', default=['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX'])
    sim.add_argument('--interval', type=int, default=60)
    sim.add_argument('--refresh', type=float, default=1.0)
    sim.add_argument('--cycles', type=int, default=0, help='Number of updates (0=infinite)')
    sim.add_argument('--open-market', action='store_true', help='Mark market as open')
    sim.add_argument('--with-analytics', action='store_true', help='Include dummy analytics PCR/Max Pain')
    sim.set_defaults(func=cmd_simulate_status)

    return p


def main():  # add explicit main wrapper for deprecation warn
    _warn()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
