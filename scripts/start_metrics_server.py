#!/usr/bin/env python3
"""Start a simple Prometheus metrics server on the given port and keep it running.

Intended for smoke/demo scenarios where the full orchestrator isn't running.
"""
from __future__ import annotations

import argparse
import importlib.util as _ils
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Start Prometheus metrics server")
    p.add_argument("--port", type=int, default=9108)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)

    # Ensure repo root on sys.path so `src` package is importable when executed directly
    try:
        if _ils.find_spec('src') is None:
            repo_root = Path(__file__).resolve().parent.parent
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
    except Exception:
        pass

    # Prefer platform server if available; fallback to raw prometheus_client
    try:
        from src.metrics.server import setup_metrics_server  # type: ignore
        setup_metrics_server(port=args.port, host=args.host)
        path = "platform"
    except Exception:
        try:
            from prometheus_client import start_http_server  # type: ignore
        except Exception as e:  # noqa: BLE001
            print(f"prometheus_client not available: {e}")
            return 2
        try:
            start_http_server(args.port, addr=args.host)
            path = "fallback"
            # Best-effort: seed governance hash gauges into default registry so g6_* names are visible
            try:  # pragma: no cover - simple wiring
                import src.metrics.generated  # type: ignore  # noqa: F401
            except Exception:
                # If src package not importable, silently continue (raw client only)
                pass
        except Exception as e:  # noqa: BLE001
            print(f"Failed to start metrics server on {args.host}:{args.port}: {e}")
            return 1

    try:
        print(f"Metrics server listening on http://{args.host}:{args.port}/metrics (path={path})")
    except Exception:
        print(f"Metrics server listening on http://{args.host}:{args.port}/metrics")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
