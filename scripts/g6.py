#!/usr/bin/env python3
"""Unified G6 CLI (Phase B Roadmap – initial scaffold).

Subcommands:
  summary          Launch summary view (wraps summary_view.py)
  simulate         Run status simulator (wraps status_simulator.py)
  panels-bridge    Run legacy status->panels bridge (wraps status_to_panels.py)
  integrity        Run one-shot panels integrity check (wraps panels_integrity_check.py)
  bench            Run a lightweight benchmark placeholder (stub)
  retention-scan   Run retention scan (stub placeholder)
  version          Show CLI + panel schema versions

Environment:
  Uses existing scripts; this CLI is a veneer to consolidate discoverability.

Future Enhancements:
  - Native implementations replacing subprocess calls for faster startup.
  - JSON output mode for machine consumption.
  - Deprecation integration for legacy script direct usage.
"""
from __future__ import annotations
import argparse, os, sys, subprocess, textwrap
from pathlib import Path
import time, json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import panel schema version if available
try:  # pragma: no cover - optional import
    from src.panels.version import PANEL_SCHEMA_VERSION as _PANEL_SCHEMA_VERSION  # type: ignore
except Exception:  # pragma: no cover
    _PANEL_SCHEMA_VERSION = 1

CLI_VERSION = "0.1.0"


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd)


def cmd_summary(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(ROOT / 'scripts' / 'summary_view.py')]
    if args.no_rich:
        cmd.append('--no-rich')
    if args.compact:
        cmd.append('--compact')
    if args.low_contrast:
        cmd.append('--low-contrast')
    cmd += ['--status-file', args.status_file, '--metrics-url', args.metrics_url, '--refresh', str(args.refresh)]
    return _run(cmd)


def cmd_simulate(args: argparse.Namespace) -> int:
    base = [sys.executable, str(ROOT / 'scripts' / 'status_simulator.py'), '--status-file', args.status_file,
            '--indices', ','.join(args.indices), '--interval', str(args.interval), '--refresh', str(args.refresh)]
    if args.cycles:
        base += ['--cycles', str(args.cycles)]
    if args.open_market:
        base.append('--open-market')
    if args.with_analytics:
        base.append('--with-analytics')
    return _run(base)


def cmd_panels_bridge(args: argparse.Namespace) -> int:
    base = [sys.executable, str(ROOT / 'scripts' / 'status_to_panels.py'), '--status-file', args.status_file, '--refresh', str(args.refresh)]
    if args.once:
        base.append('--once')
    return _run(base)


def cmd_integrity(args: argparse.Namespace) -> int:
    base = [sys.executable, str(ROOT / 'scripts' / 'panels_integrity_check.py')]
    if args.strict:
        base.append('--strict')
    if args.quiet:
        base.append('--quiet')
    if args.panels_dir:
        base += ['--panels-dir', args.panels_dir]
    if args.json:
        base.append('--json')
    return _run(base)


def cmd_bench(args: argparse.Namespace) -> int:
    """Lightweight benchmark: import cost + registry instantiation timing.

    Phases measured:
      - import_src: time to import src.metrics facade
      - registry_init: MetricsRegistry() construction
    """
    t0 = time.time()
    try:
        import importlib
        importlib.invalidate_caches()
        t_i0 = time.time()
        from src.metrics import MetricsRegistry  # type: ignore
        t_i1 = time.time()
        reg = MetricsRegistry()  # noqa: F841
        t_r1 = time.time()
    except Exception as e:  # noqa: BLE001
        if args.json:
            print(json.dumps({"error": str(e), "phase": "bench"}))
        else:
            print(f"[bench] ERROR: {e}")
        return 2
    import_src = t_i1 - t_i0
    registry_init = t_r1 - t_i1
    total = t_r1 - t0
    result = {"import_src_sec": round(import_src, 4), "registry_init_sec": round(registry_init,4), "total_sec": round(total,4)}
    if args.json:
        print(json.dumps(result))
    else:
        print(f"[bench] import_src={result['import_src_sec']}s registry_init={result['registry_init_sec']}s total={result['total_sec']}s")
    return 0


def cmd_diagnostics(args: argparse.Namespace) -> int:
    """Emit governance summary + build info (JSON only unless --pretty)."""
    try:
        from src.metrics import MetricsRegistry  # type: ignore
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"import_failed:{e}"}))
        return 2
    reg = MetricsRegistry()
    gov = {}
    try:
        if hasattr(reg, 'governance_summary'):
            gov = reg.governance_summary()  # type: ignore
    except Exception:
        gov = {"error": "governance_summary_failed"}
    out = {
        "governance": gov,
        "panel_schema_version": _PANEL_SCHEMA_VERSION,
        "cli_version": CLI_VERSION,
    }
    if args.pretty:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(json.dumps(out))
    return 0


def cmd_version(args: argparse.Namespace) -> int:  # noqa: ARG001
    print(f"g6 CLI version: {CLI_VERSION}")
    print(f"panel schema_version: {_PANEL_SCHEMA_VERSION}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='g6', description='Unified G6 operational CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('summary', help='Launch summary view UI')
    sp.add_argument('--status-file', default='data/runtime_status.json')
    sp.add_argument('--metrics-url', default='http://127.0.0.1:9108/metrics')
    sp.add_argument('--refresh', type=float, default=1.0)
    sp.add_argument('--no-rich', action='store_true')
    sp.add_argument('--compact', action='store_true')
    sp.add_argument('--low-contrast', action='store_true')
    sp.set_defaults(func=cmd_summary)

    sim = sub.add_parser('simulate', help='Run status simulator')
    sim.add_argument('--status-file', default='data/runtime_status.json')
    sim.add_argument('--indices', nargs='*', default=['NIFTY','BANKNIFTY','FINNIFTY','SENSEX'])
    sim.add_argument('--interval', type=int, default=60)
    sim.add_argument('--refresh', type=float, default=1.0)
    sim.add_argument('--cycles', type=int, default=0)
    sim.add_argument('--open-market', action='store_true')
    sim.add_argument('--with-analytics', action='store_true')
    sim.set_defaults(func=cmd_simulate)

    pb = sub.add_parser('panels-bridge', help='Legacy status->panels bridge (temporary)')
    pb.add_argument('--status-file', default='data/runtime_status.json')
    pb.add_argument('--refresh', type=float, default=0.5)
    pb.add_argument('--once', action='store_true')
    pb.set_defaults(func=cmd_panels_bridge)

    integ = sub.add_parser('integrity', help='Run one-shot panels integrity check')
    integ.add_argument('--panels-dir', default='data/panels')
    integ.add_argument('--strict', action='store_true')
    integ.add_argument('--quiet', action='store_true')
    integ.add_argument('--json', action='store_true')
    integ.set_defaults(func=cmd_integrity)

    bench = sub.add_parser('bench', help='Benchmark import + registry init timing')
    bench.add_argument('--json', action='store_true')
    bench.set_defaults(func=cmd_bench)

    diag = sub.add_parser('diagnostics', help='Emit governance + version diagnostics JSON')
    diag.add_argument('--pretty', action='store_true')
    diag.set_defaults(func=cmd_diagnostics)

    ver = sub.add_parser('version', help='Show CLI and schema version info')
    ver.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)  # type: ignore[misc]


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
