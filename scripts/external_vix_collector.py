#!/usr/bin/env python
"""External VIX (or equivalent volatility index) lightweight collector.

Initial version simulates / placeholder for real data source. Replace fetch_vix() logic
with actual HTTP API call (e.g., to NSE India, CBOE, or internal feed) returning the
current implied volatility index percent (e.g., 17.25 meaning 17.25%). The metric is
exported as a normalized fraction (percent / 100) for consistency with percentunit in Grafana.

Run:
  python -m scripts.external_vix_collector --listen :9109 --interval 30

Prometheus scrape target will expose:
  g6_external_vix{source="sim"} 0.1725

Design choices:
- Keep process stateless; rely on Prometheus for retention & alerting.
- Use --source to tag origin (e.g., "nse", "cboe", "vendorX").
- Graceful failure: on fetch error, skip update (no stale overwrite) to allow staleness alerts.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

log = logging.getLogger("vix_collector")

registry = CollectorRegistry()
VIX_GAUGE = Gauge(
    "g6_external_vix",
    "External implied volatility index (fraction; e.g., 0.1725 = 17.25%)",
    ["source"],
    registry=registry,
)

LAST_FETCH_TS = Gauge(
    "g6_external_vix_last_fetch_unixtime",
    "Unix timestamp of last successful external VIX fetch",
    ["source"],
    registry=registry,
)

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404); self.end_headers(); return
        output = generate_latest(registry)
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)
    def log_message(self, format, *args):  # noqa: A003 (shadow builtin)
        return  # quiet

@contextlib.contextmanager
def run_http_server(listen: str):
    host, port = ("0.0.0.0", 9109)
    if ":" in listen:
        host_part, port_part = listen.rsplit(":", 1)
        if host_part:
            host = host_part
        port = int(port_part)
    srv = HTTPServer((host, port), MetricsHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log.info("Serving metrics on %s:%d", host, port)
    try:
        yield srv
    finally:
        srv.shutdown()
        t.join(2)

# Placeholder fetch implementation.

def fetch_vix(source: str) -> float:
    # TODO: Replace with real API call. Provide retry/backoff & error classification.
    # Simulate plausible intraday drift between 12% and 24%.
    base = 18.0
    jitter = random.uniform(-6, 6)
    val = max(10.0, min(30.0, base + jitter))  # clamp
    return val / 100.0  # convert percent to fraction


def loop(interval: int, source: str):
    while True:
        try:
            v = fetch_vix(source)
            VIX_GAUGE.labels(source=source).set(v)
            LAST_FETCH_TS.labels(source=source).set(time.time())
        except Exception:
            log.exception("Failed to fetch VIX")
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default=":9109", help="Host:port (default :9109)")
    ap.add_argument("--interval", type=int, default=30, help="Fetch interval seconds")
    ap.add_argument("--source", default="sim", help="Source tag (e.g., nse, cboe)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    th = threading.Thread(target=loop, args=(args.interval, args.source), daemon=True)
    th.start()
    with run_http_server(args.listen):
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":  # pragma: no cover
    main()
