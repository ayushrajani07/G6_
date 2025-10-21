from __future__ import annotations

"""Developer convenience multi-tool replacing quick_* scripts.

Subcommands:
  import-check      Validate critical modules import without side effects.
  provider-check    Attempt provider bootstrap and basic quote/LTP retrieval.
  one-cycle         Run a single orchestrator cycle (writes status once).
  status-dump       Print current runtime status JSON with light normalization.

Deprecated single-purpose scripts:
  quick_import_test.py, quick_provider_check.py, quick_cycle.py
All now delegate here and emit deprecation warnings (suppressed via G6_SUPPRESS_DEPRECATIONS=1).
"""
import argparse
import importlib
import json
import os
import time
from typing import Any

_SUPPRESS = bool(os.getenv("G6_SUPPRESS_DEPRECATIONS"))


def _warn_once(tag: str, message: str) -> None:
    if _SUPPRESS:
        return
    emitted = getattr(_warn_once, "_emitted", set())  # type: ignore[attr-defined]
    if tag in emitted:
        return
    try:
        print(f"DEPRECATION: {message}")
    except Exception:
        pass
    emitted.add(tag)  # type: ignore[attr-defined]
    _warn_once._emitted = emitted  # type: ignore[attr-defined]


def cmd_import_check(_: argparse.Namespace) -> int:
    target = 'src.orchestrator.status_writer'
    try:
        m = importlib.import_module(target)
        ok = hasattr(m, 'write_runtime_status')
        print(json.dumps({"module": target, "import_ok": ok, "file": getattr(m, '__file__', None)}))
        return 0
    except Exception as e:
        print(json.dumps({"module": target, "import_ok": False, "error": str(e)}))
        return 1


def _ensure_env_defaults() -> None:
    os.environ.setdefault('KITE_API_KEY','dummy')
    os.environ.setdefault('KITE_ACCESS_TOKEN','dummy')


def cmd_provider_check(args: argparse.Namespace) -> int:
    _ensure_env_defaults()
    try:
        from src.broker.kite_provider import DummyKiteProvider, KiteProvider
        from src.utils.bootstrap import bootstrap
    except Exception as e:
        print(json.dumps({"bootstrap_import_error": str(e)}))
        return 1
    try:
        bootstrap(enable_metrics=True, log_level="WARNING")
    except Exception as e:  # bootstrap may rely on env not present
        print(json.dumps({"bootstrap_warning": str(e)}))
    instruments=[('NSE','NIFTY 50')]
    try:
        kp = KiteProvider.from_env()
        out: dict[str, Any] = {"real_provider": True}
        try:
            q = kp.get_quote(instruments)
            l = kp.get_ltp(instruments)
            out["quote_type"] = type(q).__name__
            out["ltp_type"] = type(l).__name__
            # Light summarization if dict-like
            if hasattr(q, 'keys'):
                try:
                    out["quote_keys"] = list(q.keys())[:5]  # type: ignore[arg-type]
                except Exception:
                    pass
            if hasattr(l, 'keys'):
                try:
                    out["ltp_keys"] = list(l.keys())[:5]  # type: ignore[arg-type]
                except Exception:
                    pass
        except Exception as e:
            out["real_provider_error"] = str(e)
        print(json.dumps(out))
        return 0
    except Exception as e:
        # Fallback to dummy provider
        try:
            from src.broker.kite_provider import DummyKiteProvider
            dp = DummyKiteProvider()
            instruments=[('NSE','NIFTY 50')]
            try:
                dq = dp.get_quote(instruments)
            except Exception as de:
                dq = {"dummy_error": str(de)}
            print(json.dumps({"real_provider": False, "dummy_quote": dq, "error": str(e)}))
            return 0
        except Exception as ie:
            print(json.dumps({"real_provider": False, "dummy_init_error": str(ie), "error": str(e)}))
            return 1


def cmd_one_cycle(args: argparse.Namespace) -> int:
    # Run orchestrator for a single cycle; respect interval if provided
    try:
        from scripts.run_orchestrator_loop import build_cycle_fn
    except Exception as e:
        print(json.dumps({"error": f"import_failure: {e}"}))
        return 1
    interval = max(1.0, float(args.interval))
    start = time.time()
    try:
        fn = build_cycle_fn(interval=interval, parallel=False)
        fn()  # one cycle
        elapsed = time.time() - start
        print(json.dumps({"cycle": "completed", "interval": interval, "elapsed_sec": round(elapsed,3)}))
        return 0
    except Exception as e:
        print(json.dumps({"cycle": "failed", "error": str(e)}))
        return 1


def cmd_status_dump(args: argparse.Namespace) -> int:
    path = args.status_file or os.getenv("G6_STATUS_FILE", "data/runtime_status.json")
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        # Light normalization: strip large volatile blocks optionally
        if not args.full:
            for k in list(data.keys()):
                if k.lower().startswith('debug') or k in ('raw', 'cache', 'internal_state'):
                    data.pop(k, None)
        print(json.dumps({"status_file": path, "keys": list(data.keys()), "sample": {k: data[k] for k in list(data.keys())[:5]}}))
        return 0
    except FileNotFoundError:
        print(json.dumps({"error": "status_file_missing", "status_file": path}))
        return 2
    except Exception as e:
        print(json.dumps({"error": str(e), "status_file": path}))
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Developer smoke / diagnostics multi-tool")
    sub = p.add_subparsers(dest='command', required=True)

    imp = sub.add_parser('import-check', help='Validate critical imports')
    imp.set_defaults(func=cmd_import_check)

    prov = sub.add_parser('provider-check', help='Probe provider and fetch minimal data')
    prov.set_defaults(func=cmd_provider_check)

    cyc = sub.add_parser('one-cycle', help='Run a single orchestrator cycle')
    cyc.add_argument('--interval', type=float, default=5.0)
    cyc.set_defaults(func=cmd_one_cycle)

    dump = sub.add_parser('status-dump', help='Print a summarized status file view')
    dump.add_argument('--status-file', help='Path to runtime status JSON')
    dump.add_argument('--full', action='store_true', help='Do not prune large debug/raw sections')
    dump.set_defaults(func=cmd_status_dump)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))  # type: ignore[arg-type]

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
