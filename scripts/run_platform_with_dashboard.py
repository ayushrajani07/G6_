#!/usr/bin/env python3
"""Unified launcher: metrics server + collection loop + web dashboard.

Permanent operational entrypoint to replace ad-hoc multi-shell startup.

Usage (PowerShell):
  python scripts/run_platform_with_dashboard.py --config config/config.json --port 9300 --metrics-port 9108

Environment Vars:
  G6_DASHBOARD_DEBUG=1  -> enable debug endpoints & banners
  G6_METRICS_ENDPOINT   -> override metrics scrape URL for dashboard (defaults to local server)

Stops cleanly on Ctrl+C.
"""
from __future__ import annotations
import os, sys, signal, threading, time, argparse, logging
import uvicorn

# Local imports
from src.metrics.metrics import setup_metrics_server
from src.collectors.unified_collectors import run_unified_collectors
from src.storage.csv_sink import CsvSink
try:
    from src.storage.influx_sink import InfluxSink  # type: ignore
except Exception:  # pragma: no cover
    InfluxSink = None
from src.collectors.providers_interface import Providers
from src.web.dashboard import app as dashboard_app  # FastAPI app
from src.utils.path_utils import resolve_path, data_subdir
from src.utils.market_hours import is_market_open, get_next_market_open, sleep_until_market_open
import datetime
import json

log = logging.getLogger("launcher")


def parse_args():
    p = argparse.ArgumentParser(description="Run G6 platform + dashboard")
    p.add_argument('--config', default='config/config.json')
    p.add_argument('--interval', type=int, default=60)
    p.add_argument('--metrics-port', type=int, default=9108)
    p.add_argument('--metrics-host', default='0.0.0.0')
    p.add_argument('--dashboard-port', type=int, default=9300)
    p.add_argument('--dashboard-host', default='0.0.0.0')
    p.add_argument('--log-level', default='INFO')
    return p.parse_args()


def setup_logging(level: str):
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def load_config(path: str, interval_override: int):
    if not os.path.exists(path):
        log.warning("Config %s not found – creating default", path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump({'indices': {'NIFTY': {'enable': True, 'expiries': ['this_week','next_week'], 'strikes_otm': 10, 'strikes_itm': 10}}, 'collection_interval': interval_override}, f, indent=2)
    with open(path,'r') as f:
        cfg = json.load(f)
    if interval_override:
        cfg['collection_interval'] = interval_override
    return cfg


def init_providers(cfg):
    prov_cfg = cfg.get('providers', {}).get('primary', {})
    ptype = (prov_cfg.get('type') or 'kite').lower()
    try:
        if ptype == 'kite':
            from src.broker.kite_provider import KiteProvider
            return Providers(primary_provider=KiteProvider(api_key=prov_cfg.get('api_key',''), access_token=prov_cfg.get('access_token','')))
        elif ptype == 'dummy':
            from src.broker.kite_provider import DummyKiteProvider
            return Providers(primary_provider=DummyKiteProvider())
    except Exception as e:
        log.error("Provider init failed: %s", e)
    return None


def init_storage(cfg):
    data_dir = resolve_path(cfg.get('data_dir', data_subdir('g6_data')), create=True)
    csv_sink = CsvSink(base_dir=data_dir)
    influx = None
    if cfg.get('influx',{}).get('enable') and InfluxSink:
        try:
            ic = cfg['influx']
            influx = InfluxSink(url=ic.get('url'), token=ic.get('token'), org=ic.get('org'), bucket=ic.get('bucket'))
        except Exception as e:
            log.warning("Influx init failed: %s", e)
    return csv_sink, influx


class State:
    running = True


def collection_loop(cfg, providers, csv_sink, influx, metrics):
    interval = cfg.get('collection_interval', 60)
    while State.running:
        if not is_market_open(market_type="equity", session_type="regular"):
            nxt = get_next_market_open(market_type="equity", session_type="regular")
            log.info("Market closed. Sleeping until %s", nxt)
            sleep_until_market_open(market_type="equity", session_type="regular", check_interval=15)
            if not State.running:
                break
            continue
        start = time.time()
        try:
            run_unified_collectors(cfg.get('indices', {}), providers, csv_sink, influx, metrics)
        except Exception:
            log.exception("Collector cycle failed")
        elapsed = time.time() - start
        sleep_for = max(0, interval - elapsed)
        end_at = datetime.datetime.now() + datetime.timedelta(seconds=sleep_for)
        log.info("Cycle done in %.2fs; next in %.2fs (at %s)", elapsed, sleep_for, end_at.strftime('%H:%M:%S'))
        for _ in range(int(sleep_for)):
            if not State.running:
                break
            time.sleep(1)
        if sleep_for % 1 and State.running:
            time.sleep(sleep_for % 1)


def launch_dashboard(host: str, port: int):
    # Point dashboard to local metrics if not overridden
    os.environ.setdefault('G6_METRICS_ENDPOINT', f'http://127.0.0.1:{args.metrics_port}/metrics')
    uvicorn.run(dashboard_app.app, host=host, port=port, log_level="info")  # type: ignore


def main():
    global args
    args = parse_args()
    setup_logging(args.log_level)
    log.info("Launching unified platform runner")

    # Metrics server
    metrics, _ = setup_metrics_server(port=args.metrics_port, host=args.metrics_host)

    # Config & components
    cfg = load_config(args.config, args.interval)
    providers = init_providers(cfg)
    if not providers:
        log.error("No providers initialized; exiting")
        return 1
    csv_sink, influx = init_storage(cfg)

    # Start collection thread
    t_collect = threading.Thread(target=collection_loop, args=(cfg, providers, csv_sink, influx, metrics), daemon=True)
    t_collect.start()

    # Start dashboard in main thread so Ctrl+C stops uvicorn cleanly
    def handle_sig(sig, frame):
        log.info("Signal %s received, shutting down", sig)
        State.running = False
    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        launch_dashboard(args.dashboard_host, args.dashboard_port)
    finally:
        State.running = False
        log.info("Waiting for collector thread")
        t_collect.join(timeout=5)
        log.info("Shutdown complete")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
