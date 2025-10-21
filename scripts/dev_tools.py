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
        uds-cache-stats Print UnifiedDataSource cache stats (hits/misses/reads)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_warned = False

def _warn() -> None:
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

from src.data_access.unified_source import UnifiedDataSource  # noqa: E402
from src.orchestrator.bootstrap import bootstrap_runtime  # type: ignore  # noqa: E402
from src.orchestrator.context import RuntimeContext  # type: ignore  # noqa: E402
from src.orchestrator.cycle import run_cycle  # type: ignore  # noqa: E402
from src.schema.runtime_status_validator import validate_runtime_status  # noqa: E402

DEFAULT_CONFIG = 'config/g6_config.json'


def _common_status_args(p: argparse.ArgumentParser) -> None:
    p.add_argument('--status-file', default='runtime_status.json', help='Path to runtime status JSON file')
    p.add_argument('--interval', type=int, default=3, help='Collection interval seconds')


from collections.abc import Callable
from typing import cast


def _bootstrap(config_path: str) -> tuple[RuntimeContext, Callable[[], None]]:  # type: ignore[name-defined]
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
                # Prefer StatusReader or cached JSON to avoid repeated disk reads
                try:
                    try:
                        from src.utils.status_reader import get_status_reader  # type: ignore
                        reader = get_status_reader(args.status_file)
                        data = reader.get_raw_status()
                    except Exception:
                        from pathlib import Path as _Path

                        from src.utils.csv_cache import read_json_cached as _read_json_cached
                        data = _read_json_cached(_Path(args.status_file))
                    if isinstance(data, dict):
                        print(f"Cycle {i}: cycle={data.get('cycle')} elapsed={data.get('elapsed')}s indices={data.get('indices')}")
                    else:
                        print(f'Cycle {i}: (status read failed)')
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
        from src.utils.status_reader import get_status_reader  # type: ignore
    except Exception:
        get_status_reader = None  # type: ignore
    try:
        while True:
            if path.exists():
                try:
                    if get_status_reader is not None:
                        reader = get_status_reader(str(path))
                        data = reader.get_raw_status()
                    else:
                        from src.utils.csv_cache import read_json_cached as _read_json_cached
                        data = _read_json_cached(path)
                    if data != last and isinstance(data, dict):
                        last = data
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
        for err in errors:
            print(f" - {err}")
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
    """Launch the summarizer UI (Rich if available, else ASCII). Uses unified summary/app.py."""
    cmd = [sys.executable, str(ROOT / 'scripts' / 'summary' / 'app.py')]
    if args.no_rich:
        cmd.append('--no-rich')
    cmd += ['--status-file', args.status_file, '--metrics-url', args.metrics_url, '--refresh', str(args.refresh)]
    if args.compact:
        cmd.append('--compact')
    if args.low_contrast:
        cmd.append('--low-contrast')
    return subprocess.call(cmd)


def cmd_simulate_status(args: argparse.Namespace) -> int:
    """Run the status simulator and optionally inject demo metrics for dashboards.

    When --inject-empty-quotes / --inject-csv-activity are supplied we keep a lightweight
    background thread that periodically increments Prometheus counters so Grafana panels
    (Empty Quote Fields, CSV Write Errors, CSV Records Written) show activity during demos.
    """
    base_cmd = [sys.executable, str(ROOT / 'scripts' / 'status_simulator.py'),
                '--status-file', args.status_file,
                '--indices', ','.join(args.indices),
                '--interval', str(args.interval),
                '--refresh', str(args.refresh)]
    if args.cycles:
        base_cmd += ['--cycles', str(args.cycles)]
    if args.open_market:
        base_cmd.append('--open-market')
    if args.with_analytics:
        base_cmd.append('--with-analytics')

    inject = args.inject_empty_quotes or args.inject_csv_activity
    # Optionally start Prometheus metrics server in this process so any injected counters are exposed on 9108
    if args.start_metrics_server:
        try:
            from src.utils.metrics_utils import init_metrics  # type: ignore
            init_metrics(port=9108)
            print('[simulate-status] metrics server started on 127.0.0.1:9108')
        except Exception as e:  # noqa: BLE001
            print(f'[simulate-status] failed to start metrics server: {e}')
    if not inject:
        return subprocess.call(base_cmd)

    try:
        from prometheus_client import Counter  # type: ignore
    except Exception:
        print('[simulate-status] prometheus_client not available; skipping metric injection.')
        return subprocess.call(base_cmd)

    # Register required counters (ignore errors if already exist in shared registry)
    empty_counter = None
    csv_records = None
    csv_errors = None
    try:
        if args.inject_empty_quotes:
            empty_counter = Counter('g6_empty_quote_fields_total', 'Count of expiries where all quotes missing volume/oi/avg_price', ['index','expiry_rule'])
        if args.inject_csv_activity:
            csv_records = Counter('g6_csv_records_written_total', 'CSV records written')
            csv_errors = Counter('g6_csv_write_errors_total', 'CSV write errors')
    except Exception as e:  # noqa: BLE001
        # Likely duplicate registration. Attempt to locate existing collectors instead of re-registering.
        print(f'[simulate-status] counter registration issue (reuse existing if possible): {e}')
        try:
            from prometheus_client import REGISTRY  # type: ignore
            # Build a name->sample mapping to confirm existence; direct object retrieval is not public API.
            existing_names = {c.name for c in REGISTRY.collect()}  # type: ignore[attr-defined]
            if 'g6_empty_quote_fields_total' in existing_names:
                # We can't easily get the original Counter object; skip injection for this metric to avoid double counting risk.
                empty_counter = None
            if 'g6_csv_records_written_total' in existing_names:
                csv_records = None
            if 'g6_csv_write_errors_total' in existing_names:
                csv_errors = None
        except Exception:
            pass

    import random
    import threading
    stop_evt = threading.Event()

    def _loop() -> None:
        expiry_rules = ['weekly','monthly']
        while not stop_evt.is_set():
            try:
                if empty_counter is not None:
                    idx = random.choice(args.indices)
                    rule = random.choice(expiry_rules)
                    empty_counter.labels(index=idx, expiry_rule=rule).inc()
                if csv_records is not None:
                    csv_records.inc(random.randint(40, 120))
                    if csv_errors is not None and random.random() < 0.07:
                        csv_errors.inc()
            except Exception:
                pass
            stop_evt.wait(args.interval)

    t = threading.Thread(target=_loop, name='metric-injector', daemon=True)
    t.start()
    try:
        return subprocess.call(base_cmd)
    finally:
        stop_evt.set()
        t.join(timeout=2)


def cmd_uds_cache_stats(args: argparse.Namespace) -> int:
    """Print UnifiedDataSource cache statistics.

    Optionally enable stats collection before printing and/or reset after print.
    """
    uds = UnifiedDataSource()
    # Optionally enable stats collection on the fly
    try:
        if args.enable:
            try:
                uds.config.enable_cache_stats = True  # type: ignore[assignment]
            except Exception:
                pass
    except Exception:
        pass
    stats = uds.get_cache_stats(reset=args.reset)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


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
    sim.add_argument('--start-metrics-server', action='store_true', help='Start Prometheus metrics server on 9108 in this process')
    sim.add_argument('--inject-empty-quotes', action='store_true', help='Inject demo increments for g6_empty_quote_fields_total')
    sim.add_argument('--inject-csv-activity', action='store_true', help='Inject demo CSV records plus occasional write errors')
    sim.set_defaults(func=cmd_simulate_status)

    uc = sub.add_parser('uds-cache-stats', help='Print UnifiedDataSource cache stats (hits/misses/reads)')
    uc.add_argument('--enable', action='store_true', help='Enable cache stats collection before printing')
    uc.add_argument('--reset', action='store_true', help='Reset counters after printing')
    uc.set_defaults(func=cmd_uds_cache_stats)

    return p


def main() -> int:  # add explicit main wrapper for deprecation warn
    _warn()
    parser = build_parser()
    args = parser.parse_args()
    handler = cast(Callable[[argparse.Namespace], int], getattr(args, 'func', None))
    if handler is None:
        return 2
    return handler(args)

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
