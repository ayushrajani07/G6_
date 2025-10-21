#!/usr/bin/env python3
"""Mock live updates server for overlay demo.

Serves a tiny JSON payload that overlay_live_updates.js can poll to update Plotly graphs.

Contract (response JSON):
{
  "panels": {
    "<divId>": {
      "x": ["2025-09-24T10:00:00Z", ...],
      "y": [123.4, ...],
      "layout": { "shapes": [], "annotations": [] }
    },
    ...
  }
}

Usage (PowerShell):
  python scripts/mock_live_updates.py --port 9109 --pairs NIFTY:this_week:ATM --pairs BANKNIFTY:this_week:ATM --interval 1.0
"""
from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


def iso_z(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


class State:
    def __init__(self, pairs: list[tuple[str, str, str]]):
        self.lock = threading.Lock()
        self.t0 = time.time()
        # simple walk per panel
        self.series: dict[str, list[tuple[float, float]]] = {}
        for idx, exp, off in pairs:
            key = f"panel-{idx}-{exp}-{off}"
            self.series[key] = []

    def tick(self):
        with self.lock:
            t = time.time()
            for key, seq in self.series.items():
                # produce a gentle sine walk with noise
                x = t
                base = 1000.0 + 100.0 * math.sin((t - self.t0) / 60.0)
                y = base + random.uniform(-10, 10)
                seq.append((x, y))
                # keep last N points
                if len(seq) > 600:
                    del seq[: len(seq) - 600]

    def payload(self) -> dict[str, dict]:
        with self.lock:
            panels = {}
            for key, seq in self.series.items():
                if not seq:
                    continue
                xs = [iso_z(s[0]) for s in seq]
                ys = [s[1] for s in seq]
                panels[key] = {"x": xs, "y": ys, "layout": {}}
            return {"panels": panels}


class Handler(BaseHTTPRequestHandler):
    state: State = None  # type: ignore

    def _cors(self):
        # Permissive CORS for local demos
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self._cors()
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path.startswith("/metrics"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self._cors()
            self.end_headers()
            self.wfile.write(b"g6_mock_live_updates_up 1\n")
            return
        if self.path.startswith("/live"):
            body = json.dumps(self.state.payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def log_message(self, format, *args):  # suppress noisy logs in tests
        return


def run_server(state: State, host: str, port: int, interval: float):
    Handler.state = state
    httpd = HTTPServer((host, port), Handler)

    def producer():
        while True:
            state.tick()
            time.sleep(max(0.05, interval))

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    print(f"[MOCK] live updates server on http://{host}:{port} (interval={interval}s)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def parse_pairs(vals: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for v in vals or []:
        parts = v.split(":")
        if len(parts) != 3:
            raise SystemExit(f"Invalid --pairs value: {v}. Expected format INDEX:EXPIRY:OFFSET")
        out.append((parts[0], parts[1], parts[2]))
    return out


def main():
    ap = argparse.ArgumentParser(description="Mock live updates server for overlays")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9109)
    ap.add_argument("--pairs", action="append", help="Triples as INDEX:EXPIRY:OFFSET; repeatable")
    ap.add_argument("--interval", type=float, default=1.0, help="Update interval seconds")
    args = ap.parse_args()
    pairs = parse_pairs(args.pairs or ["NIFTY:this_week:ATM"])  # default one panel
    state = State(pairs)
    run_server(state, args.host, args.port, args.interval)


if __name__ == "__main__":
    main()
