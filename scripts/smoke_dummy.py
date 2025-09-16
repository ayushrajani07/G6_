#!/usr/bin/env python3
"""Smoke test runner for G6 Platform.

Purpose:
  - Runs unified_main with a dummy provider (no real API calls)
  - Executes exactly one collection cycle
  - Verifies config translation (indices -> index_params)
  - Suitable for CI or pre-deployment quick health check

Usage (PowerShell):
  python scripts/smoke_dummy.py

Exit Codes:
  0 success
  1 failure (exception or missing indices)
"""
from __future__ import annotations
import sys
import logging
import argparse

from src.unified_main import bootstrap, init_storage, apply_circuit_breakers, collection_loop, run_analytics_block
from src.config.config_wrapper import ConfigWrapper
from src.collectors.providers_interface import Providers


def build_dummy_config(base: ConfigWrapper) -> ConfigWrapper:
    # Ensure indices exist for translation
    if not base.index_params():
        base['indices'] = {
            "NIFTY": {"enable": True, "expiries": ["this_week"], "strikes_otm": 5, "strikes_itm": 5},
        }
    # Force dummy provider
    base['providers'] = {"primary": {"type": "dummy"}}
    # One short interval
    base['collection'] = {"interval_seconds": 1}
    return base


def init_dummy_providers() -> Providers:
    from src.broker.kite_provider import DummyKiteProvider  # type: ignore
    return Providers(primary_provider=DummyKiteProvider())


def main():
    ap = argparse.ArgumentParser(description="G6 Smoke Test (Dummy Provider)")
    ap.add_argument('--config', default='config/g6_config.json')
    ap.add_argument('--analytics', action='store_true')
    args = ap.parse_args()

    boot = bootstrap(config_path=args.config, log_level='INFO', log_file='logs/smoke.log', enable_metrics=False)
    cfg = build_dummy_config(boot.config)

    logging.info("Starting smoke test (dummy provider)")

    providers = init_dummy_providers()
    csv_sink, influx_sink = init_storage(cfg)
    apply_circuit_breakers(cfg, providers)

    index_params = cfg.index_params()
    if not index_params:
        logging.error("Smoke test failed: index_params empty after translation")
        return 1

    if args.analytics:
        run_analytics_block(providers, cfg)

    try:
        collection_loop(
            cfg,
            providers,
            csv_sink,
            influx_sink,
            metrics=None,
            use_enhanced=False,
            market_hours_only=False,
            run_once=True,
            index_params=index_params,
        )
    except Exception as e:
        logging.error(f"Smoke test collection failed: {e}")
        return 1
    finally:
        try:
            providers.close()
        except Exception:
            pass

    logging.info("Smoke test completed successfully")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(1)
