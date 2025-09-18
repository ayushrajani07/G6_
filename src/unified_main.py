#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified G6 Platform Entry Point
Combines legacy main + advanced features:
- Basic + enhanced collectors
- Market hours gating (optional)
- Run-once capability
- Analytics (PCR, max pain, support/resistance) optional
- Circuit breakers & health monitor (from basic main)
- Metrics server startup
"""
from __future__ import annotations

import os
import sys
import time
import json
import signal
import logging
import argparse
import datetime as _dt
import threading
import math
from typing import Any, Dict, Optional

from src.utils.path_utils import ensure_sys_path, data_subdir, resolve_path
ensure_sys_path()

# Imports (local project)
from src.collectors.providers_interface import Providers
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.enhanced_collector import run_enhanced_collectors
from src.storage.csv_sink import CsvSink
try:  # Prefer real implementations
    from src.storage.influx_sink import InfluxSink, NullInfluxSink  # type: ignore
except Exception:  # Fallback lightweight stand-ins
    InfluxSink = None  # type: ignore
    class NullInfluxSink:  # type: ignore
        def __init__(self):
            ...
from src.health.monitor import HealthMonitor
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.resilience import HealthCheck
from src.utils.market_hours import (
    is_market_open, get_next_market_open, sleep_until_market_open, DEFAULT_MARKET_HOURS
)
from src.metrics.metrics import setup_metrics_server
from src.utils.logging_utils import setup_logging  # legacy remain for compatibility if needed
from src.analytics.option_chain import OptionChainAnalytics
from src.config.config_wrapper import ConfigWrapper
from src.utils.bootstrap import bootstrap, BootContext
from src.utils.color import colorize, FG_GREEN, FG_RED, FG_YELLOW
try:
    from src.logstream.pretty_startup import build_startup_panel  # type: ignore
except Exception:  # pragma: no cover
    build_startup_panel = None  # type: ignore

# Unified ASCII sanitation map for non-UTF consoles
ASCII_SAN_MAP = str.maketrans({
    '╔':'+','╗':'+','╚':'+','╝':'+','═':'=','║':'|','─':'-','┌':'+','┐':'+','└':'+','┘':'+','│':'|'
})

def sanitize_console_text(text: str) -> str:
    try:
        enc = getattr(sys.stdout, 'encoding', '') or ''
        # Honor override to force unicode
        if os.environ.get('G6_FORCE_UNICODE','').lower() in ('1','true','yes','on'):
            return text
        if enc.lower() in ('utf-8','utf8','utf_8'):
            return text
        return text.translate(ASCII_SAN_MAP)
    except Exception:
        return text

__version__ = "2.0.0-unified"

# Metrics gauge placeholder (set once when metrics subsystem active)
_PROVIDER_READY_GAUGE = None  # lazily created

## Logging handled by utils.logging_utils.setup_logging

# ---------------- Config -----------------

def load_config(path: str) -> ConfigWrapper:
    """Load and normalize configuration into ConfigWrapper.

    Backward compatible: if file missing, writes a default base config.
    """
    raw: Dict[str, Any]
    if not os.path.exists(path):
        raw = create_default_config(path)
    else:
        try:
            with open(path, 'r') as f:
                raw = json.load(f)
        except Exception as e:
            logging.error(f"Failed loading config %s: %s; using defaults", path, e)
            raw = create_default_config()
    return ConfigWrapper(raw)

def create_default_config(save_path: Optional[str] = None) -> Dict[str, Any]:
    cfg = {
        "data_dir": data_subdir("g6_data"),
        "collection_interval": 60,
        "orchestration": {"run_interval_sec": 60, "prometheus_port": 9108},
        "indices": {
            "NIFTY": {"enable": True, "expiries": ["this_week"], "strikes_otm": 10, "strikes_itm": 10},
            "BANKNIFTY": {"enable": True, "expiries": ["this_week"], "strikes_otm": 10, "strikes_itm": 10},
        },
        "providers": {"primary": {"type": "kite"}},
        "influx": {"enable": False},
        "health": {"check_interval": 60, "circuit_breaker": {"failure_threshold": 5, "reset_timeout": 300}},
        "index_params": {"NIFTY": {"expiries": ["this_week"], "strikes": 10}},
        "features": {"analytics_startup": False},
        "console": {"fancy_startup": False, "live_panel": False, "startup_banner": True},
    }
    if save_path:
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(cfg, f, indent=2)
            logging.info(f"Wrote default config to {save_path}")
        except Exception as e:
            logging.error(f"Could not save default config: {e}")
    return cfg

# ---------------- Providers -----------------

def init_providers(config: ConfigWrapper) -> Providers:
    """Initialize providers.

    Supports native providers plus an environment-gated synthetic mock provider for
    off-market development / demos. To enable mock provider WITHOUT modifying JSON
    config set either CLI flag --mock-data (preferred) or export G6_USE_MOCK_PROVIDER=1.
    """
    # Synthetic mock provider (env override) ---------------------------------
    if os.environ.get('G6_USE_MOCK_PROVIDER'):
        import random
        class MockProvider:  # minimal facade-compatible surface
            def __init__(self):
                self._start = time.time()
                random.seed(int(self._start))
                # Base levels approximating spot values
                self._bases = {
                    'NIFTY': 20000.0,
                    'BANKNIFTY': 45000.0,
                    'FINNIFTY': 21000.0,
                    'SENSEX': 66000.0,
                }
                # Maintain a mutable price map for random walk
                self._prices = dict(self._bases)
            def _tick(self, symbol: str):
                base = self._bases.get(symbol, 10000.0)
                cur = self._prices.get(symbol, base)
                # Random walk with gentle drift using sin for smooth wave + random noise
                t = time.time() - self._start
                wave = math.sin(t / 30.0) * base * 0.0015  # ±0.15%
                noise = random.uniform(-1, 1) * base * 0.0005  # ±0.05%
                # Mean-reverting pull towards base
                pull = (base - cur) * 0.01
                new_price = cur + pull + (wave + noise)
                # Clamp within ±1% band just in case
                low, high = base * 0.99, base * 1.01
                if new_price < low: new_price = low
                if new_price > high: new_price = high
                self._prices[symbol] = new_price
                return new_price
            # Legacy collector expects .get_ltp(symbol)
            def get_ltp(self, symbol: str):  # pragma: no cover (dev utility)
                return round(self._tick(symbol), 2)
            # Some code paths may ask for quote
            def get_quote(self, symbol: str):  # pragma: no cover
                ltp = self.get_ltp(symbol)
                now_iso = _dt.datetime.now(_dt.UTC).isoformat()
                # Provide minimal fields some analytics might introspect
                return {
                    "last_price": ltp,
                    "instrument_token": 0,
                    "timestamp": now_iso,
                    "depth": {"buy": [], "sell": []},
                }
            # Expiry resolution helper (very rough)
            def resolve_expiry(self, symbol: str, rule: str):  # pragma: no cover
                today = _dt.date.today()
                # Next Thursday for weekly style rules
                for i in range(1, 8):
                    d = today + _dt.timedelta(days=i)
                    if d.weekday() == 3:  # Thursday
                        return d
                return today + _dt.timedelta(days=7)
            def close(self):  # pragma: no cover
                pass
        logging.warning("[MOCK] Using synthetic MockProvider (no external API calls / auth).")
        return Providers(primary_provider=MockProvider())

    # Real providers ---------------------------------------------------------
    pconf = config.get('providers', {}).get('primary', {})  # type: ignore[index]
    ptype = pconf.get('type', 'kite').lower()
    if ptype == 'kite':
        from src.broker.kite_provider import KiteProvider
        provider = KiteProvider.from_env()
    elif ptype == 'dummy':
        from src.broker.kite_provider import DummyKiteProvider
        provider = DummyKiteProvider()
    else:
        raise ValueError(f"Unsupported provider type: {ptype}")
    return Providers(primary_provider=provider)

# ---------------- Storage -----------------

def init_storage(config: ConfigWrapper):
    data_dir = resolve_path(config.data_dir(), create=True)
    csv_sink = CsvSink(base_dir=data_dir)
    influx_cfg = config.get('influx', {})
    if influx_cfg.get('enable') and InfluxSink:
        try:
            influx = InfluxSink(
                url=influx_cfg.get('url', 'http://localhost:8086'),
                token=influx_cfg.get('token', ''),
                org=influx_cfg.get('org', ''),
                bucket=influx_cfg.get('bucket', 'g6_options')
            )
        except Exception as e:
            logging.error(f"Influx init failed: {e}")
            influx = NullInfluxSink()
    else:
        influx = NullInfluxSink()
    return csv_sink, influx

# ---------------- Health -----------------

def init_health(config: ConfigWrapper, providers: Providers, csv_sink: CsvSink, influx_sink: Any) -> HealthMonitor:
    hcfg = config.get('health', {})  # type: ignore[index]
    hm = HealthMonitor(check_interval=hcfg.get('check_interval', 60))
    hm.register_component('providers', providers)
    hm.register_component('csv_sink', csv_sink)
    if influx_sink:
        hm.register_component('influx_sink', influx_sink)
    hm.register_health_check('csv_storage', lambda: HealthCheck.check_storage(csv_sink))
    return hm

# ---------------- Circuit Breakers -----------------

def apply_circuit_breakers(config: ConfigWrapper, providers: Providers):
    circuit_cfg = config.get('health', {}).get('circuit_breaker', {})  # type: ignore[index]
    if not circuit_cfg:
        return
    failure_threshold = circuit_cfg.get('failure_threshold', 5)
    reset_timeout = circuit_cfg.get('reset_timeout', 300)
    prov = providers.primary_provider
    if hasattr(prov, 'get_quote'):
        prov.get_quote = CircuitBreaker('api_quote', failure_threshold, reset_timeout)(prov.get_quote)  # type: ignore
    if hasattr(prov, 'get_ltp'):
        prov.get_ltp = CircuitBreaker('api_ltp', failure_threshold, reset_timeout)(prov.get_ltp)  # type: ignore

# ---------------- Analytics -----------------

def run_analytics_block(providers: Providers, config: ConfigWrapper):
    try:
        oc = OptionChainAnalytics(providers)
        for index_symbol in config.index_params().keys():
            try:
                expiry = providers.resolve_expiry(index_symbol, 'this_week')
                expiries = config.index_params()[index_symbol].get('expiries', ['this_week'])
                expiry_rule = expiries[0]
                try:
                    if hasattr(providers.primary_provider, 'resolve_expiry'):
                        resolved_expiry = providers.primary_provider.resolve_expiry(index_symbol, expiry_rule)  # type: ignore
                        logging.debug(f"Analytics expiry resolved: index={index_symbol} rule={expiry_rule} -> {resolved_expiry}")
                    else:
                        resolved_expiry = _dt.date.today()
                except Exception as e:
                    logging.warning(f"Analytics expiry resolution failed for {index_symbol} {expiry_rule}: {e}")
                    resolved_expiry = _dt.date.today()
                pcr = oc.calculate_pcr(index_symbol, expiry)
                logging.info(f"Analytics {index_symbol} PCR: OI={pcr['oi_pcr']:.2f} Vol={pcr['volume_pcr']:.2f}")
                mp = oc.calculate_max_pain(index_symbol, expiry)
                logging.info(f"Analytics {index_symbol} Max Pain: {mp}")
                levels = oc.calculate_support_resistance(index_symbol, expiry)
                logging.info(f"Analytics {index_symbol} Support={levels['support']} Resistance={levels['resistance']}")
            except Exception as ie:
                logging.error(f"Analytics error {index_symbol}: {ie}")
    except Exception as e:
        logging.error(f"Analytics block failed: {e}")

# ---------------- Collection Loop -----------------

def run_collection_cycle(config: ConfigWrapper, providers: Providers, csv_sink: CsvSink, influx_sink: Any, metrics: Any, use_enhanced: bool, index_params: Dict[str, Any]):
    if use_enhanced:
        run_enhanced_collectors(
            index_params=index_params,
            providers=providers,
            csv_sink=csv_sink,
            influx_sink=influx_sink,
            metrics=metrics,
            only_during_market_hours=False,
        )
    else:
        greeks_cfg = config.get('greeks', {})  # type: ignore[index]
        run_unified_collectors(
            index_params,
            providers,
            csv_sink,
            influx_sink,
            metrics,
            compute_greeks=bool(greeks_cfg.get('enabled')),
            risk_free_rate=float(greeks_cfg.get('risk_free_rate', 0.05)),
            estimate_iv=bool(greeks_cfg.get('estimate_iv', False)),
            iv_max_iterations=int(greeks_cfg.get('iv_max_iterations', 100)),
            iv_min=float(greeks_cfg.get('iv_min', 0.01)),
            iv_max=float(greeks_cfg.get('iv_max', 5.0)),
        )

# ---------------- Market Hours Wrapper -----------------

def collection_loop(config: ConfigWrapper, providers: Providers, csv_sink: CsvSink, influx_sink: Any, metrics: Any, use_enhanced: bool, market_hours_only: bool, run_once: bool, index_params: Dict[str, Any], runtime_status_file: Optional[str] = None, readiness_ok: Optional[bool] = None, readiness_reason: str = "", health_monitor: Any = None):
    interval = (
        config.get('collection', {}).get('interval_seconds')  # type: ignore[index]
        or config.get('orchestration', {}).get('run_interval_sec', 60)  # type: ignore[index]
    )

    def wait_for_open():
        next_open = get_next_market_open()
        wait_secs = (next_open - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
        logging.info(f"Market closed. Waiting {wait_secs/60:.1f} minutes until {next_open}")
        sleep_until_market_open(
            market_type="equity",
            session_type="regular",
            check_interval=10,
            on_wait_start=lambda dt: logging.info(f"Waiting for market open at {dt}"),
            on_wait_tick=lambda rem: (logging.info(f"Still waiting: {rem/60:.1f}m") if rem % 300 == 0 else True)
        )

    # Live panel precedence: ENV > config.console.live_panel (bool) > default False
    live_panel_cfg = False
    try:
        live_panel_cfg = bool(config.get('console', {}).get('live_panel'))  # type: ignore[index]
    except Exception:
        pass
    live_panel_env = os.environ.get('G6_LIVE_PANEL','').lower() in ('1','true','yes','on')
    live_panel_enabled = live_panel_env or live_panel_cfg
    panel_builder = None
    if live_panel_enabled:
        try:
            from src.logstream.live_panel import build_live_panel  # type: ignore
            panel_builder = build_live_panel
        except Exception:
            live_panel_enabled = False

    cycle_count = 0
    # Allow test/dev environment to bound cycles without --run-once by setting G6_MAX_CYCLES
    try:
        _max_cycles_env = int(os.environ.get('G6_MAX_CYCLES','0'))
    except Exception:  # pragma: no cover
        _max_cycles_env = 0
    while True:
        if market_hours_only and not is_market_open():
            wait_for_open()
            if run_once:
                break
        start = time.time()
        run_collection_cycle(config, providers, csv_sink, influx_sink, metrics, use_enhanced, index_params)
        elapsed = time.time() - start
        cycle_count += 1
        # Live panel output
        if live_panel_enabled and panel_builder:
            try:
                # Gather metrics snapshot (best effort; rely on internal attributes where available)
                success_rate = None
                per_min = None
                api_success = None
                api_latency = getattr(metrics, '_api_latency_ema', None) if metrics else None
                options_last = 0
                if metrics:
                    try:
                        total = getattr(metrics, '_cycle_total', 0)
                        succ = getattr(metrics, '_cycle_success', 0)
                        if total > 0:
                            success_rate = (succ / total) * 100.0
                    except Exception:
                        pass
                    options_last = getattr(metrics, '_last_cycle_options', 0)
                    try:
                        per_min = getattr(metrics, 'options_per_minute')._value.get() if hasattr(metrics.options_per_minute, '_value') else None  # type: ignore[attr-defined]
                    except Exception:
                        per_min = None
                    try:
                        api_success = getattr(metrics, 'api_success_rate')._value.get() if hasattr(metrics.api_success_rate, '_value') else None  # type: ignore[attr-defined]
                    except Exception:
                        api_success = None
                # System resource snapshot
                mem_mb = None
                cpu_pct = None
                try:
                    if metrics and hasattr(metrics, 'memory_usage_mb') and hasattr(metrics.memory_usage_mb, '_value'):
                        mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore[attr-defined]
                    if metrics and hasattr(metrics, 'cpu_usage_percent') and hasattr(metrics.cpu_usage_percent, '_value'):
                        cpu_pct = metrics.cpu_usage_percent._value.get()  # type: ignore[attr-defined]
                except Exception:
                    pass
                # Per-index attempt/failure snapshot (approximation)
                index_data = {}
                try:
                    for idx in index_params.keys():
                        attempts = None
                        failures = None
                        # Access underlying counters if present (best effort)
                        # We maintain last cycle attempts via gauge index_cycle_attempts
                        try:
                            if metrics and hasattr(metrics, 'index_cycle_attempts') and hasattr(metrics.index_cycle_attempts, '_metrics'):  # type: ignore[attr-defined]
                                # Prometheus client internal; skip heavy parsing
                                pass
                        except Exception:
                            pass
                        index_data[idx] = {'attempts': attempts, 'failures': failures, 'options': options_last, 'atm': None}
                except Exception:
                    pass
                # Build kwargs based on builder signature (duck-type for enhanced vs legacy)
                panel_text = panel_builder(
                    cycle=cycle_count,
                    cycle_time=elapsed,
                    success_rate=success_rate,
                    options_processed=options_last,
                    per_min=per_min,
                    api_success=api_success,
                    api_latency_ms=api_latency,
                    memory_mb=mem_mb,
                    cpu_pct=cpu_pct,
                    indices=index_data,
                    concise=True,
                )
                logging.info(sanitize_console_text(panel_text))
            except Exception:
                # Fall back silently
                pass
        # Downgrade noisy message when concise structured logs are default
        try:
            from src.broker.kite_provider import _CONCISE as _PROV_CONCISE  # type: ignore
            if _PROV_CONCISE:
                logging.debug(f"Cycle completed in {elapsed:.2f}s")
            else:
                logging.info(f"Cycle completed in {elapsed:.2f}s")
        except Exception:
            logging.info(f"Cycle completed in {elapsed:.2f}s")
        # Write runtime status snapshot (atomic) for attach-mode terminal UI
        # Predefine variables reused by optional sinks
        success_rate = None
        options_last = None
        if runtime_status_file:
            try:
                # Import time helpers early so names are defined for status dict
                try:
                    from src.utils.timeutils import ensure_utc_helpers  # type: ignore
                    utc_now, isoformat_z = ensure_utc_helpers()  # type: ignore[misc]
                except Exception:
                    from datetime import datetime, timezone
                    def utc_now():  # type: ignore
                        return datetime.now(timezone.utc)
                    def isoformat_z(d):  # type: ignore
                        return d.isoformat().replace('+00:00','Z')
                # Metrics derived values (best-effort)
                per_min = None
                api_success = None
                mem_mb = None
                cpu_pct = None
                if metrics:
                    try:
                        total = getattr(metrics, '_cycle_total', 0)
                        succ = getattr(metrics, '_cycle_success', 0)
                        if total > 0:
                            success_rate = round((succ / total) * 100.0, 2)
                    except Exception:  # pragma: no cover
                        pass
                    options_last = getattr(metrics, '_last_cycle_options', None)
                    try:
                        per_min = getattr(metrics, 'options_per_minute')._value.get() if hasattr(metrics.options_per_minute, '_value') else None  # type: ignore[attr-defined]
                    except Exception:
                        per_min = None
                    try:
                        api_success = getattr(metrics, 'api_success_rate')._value.get() if hasattr(metrics.api_success_rate, '_value') else None  # type: ignore[attr-defined]
                    except Exception:
                        api_success = None
                    try:
                        if hasattr(metrics, 'memory_usage_mb') and hasattr(metrics.memory_usage_mb, '_value'):
                            mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore[attr-defined]
                        if hasattr(metrics, 'cpu_usage_percent') and hasattr(metrics.cpu_usage_percent, '_value'):
                            cpu_pct = metrics.cpu_usage_percent._value.get()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                # Per-index quick snapshot (best-effort LTP)
                indices_info = {}
                indices_detail = {}
                try:
                    for idx in index_params.keys():
                        ltp_val = None
                        options_ct = None
                        try:
                            ltp_val = providers.get_ltp(idx)  # type: ignore[union-attr]
                        except Exception:
                            pass
                        # Fetch per-index last-cycle option count from internal map if available
                        try:
                            if metrics and hasattr(metrics, '_per_index_last_cycle_options'):
                                options_ct = metrics._per_index_last_cycle_options.get(idx)
                            if options_ct is None:
                                # Fallback to aggregate if specific not yet populated
                                options_ct = getattr(metrics, '_last_cycle_options', None)
                        except Exception:
                            pass
                        # Age calculation using csv sink last write (if available)
                        age_sec = None
                        try:
                            per_idx = getattr(csv_sink, 'last_write_per_index', {}) or {}
                            ts = per_idx.get(idx)
                            if ts:
                                age_sec = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds()
                        except Exception:
                            pass
                        indices_info[idx] = {"ltp": ltp_val, "options": options_ct}
                        indices_detail[idx] = {"status": "OK" if ltp_val is not None else "STALE", "ltp": ltp_val, "age": age_sec, "age_sec": age_sec}
                except Exception:
                    pass
                # Health summary snapshot
                health_snapshot = {}
                try:
                    components = getattr(health_monitor, 'components', {}) if health_monitor else {}
                    for cname, cdata in components.items():
                        hw = {"status": cdata.get('status','unknown')}
                        try:
                            last = cdata.get('last_check')
                            hw['last_check'] = last.isoformat() if last else None
                        except Exception:
                            pass
                        # Augment with last_write if sink components
                        try:
                            if cname == 'csv_sink':
                                ts = getattr(csv_sink, 'last_write_ts', None)
                                hw['last_write'] = ts.isoformat() if ts else None
                            if cname == 'influx_sink':
                                ts = getattr(influx_sink, 'last_write_ts', None)
                                hw['last_write'] = ts.isoformat() if ts else None
                        except Exception:
                            pass
                        health_snapshot[cname] = hw
                except Exception:
                    pass
                # Provider info best-effort
                provider_info = {"name": None, "auth": {"valid": None, "expiry": None}, "latency_ms": None}
                try:
                    pname = type(providers.primary_provider).__name__ if providers and providers.primary_provider else None
                    provider_info["name"] = pname
                    # Latency estimate from metrics if exposed
                    try:
                        provider_info["latency_ms"] = getattr(metrics, '_api_latency_ema', None)
                    except Exception:
                        pass
                    # No direct expiry unless provider exposes; leave None
                except Exception:
                    pass
                # Sinks last_write snapshot
                sinks_snapshot = {}
                try:
                    ts_csv = getattr(csv_sink, 'last_write_ts', None)
                    sinks_snapshot['csv_sink'] = {"last_write": ts_csv.isoformat() if ts_csv else None}
                    ts_influx = getattr(influx_sink, 'last_write_ts', None)
                    if ts_influx is not None:
                        sinks_snapshot['influx_sink'] = {"last_write": ts_influx.isoformat() if hasattr(ts_influx, 'isoformat') else str(ts_influx)}
                except Exception:
                    pass
                # Market and loop blocks for richer summary
                market_block = {"status": "OPEN" if is_market_open() else "CLOSED"}
                loop_block = {
                    "cycle": cycle_count,
                    "last_run": isoformat_z(utc_now()),
                    "last_duration": round(elapsed, 3),
                    "next_run_in_sec": max(0, interval - elapsed),
                    "target_interval": interval,
                }
                resources_block = {}
                if cpu_pct is not None or mem_mb is not None:
                    try:
                        rss_bytes = int(mem_mb * 1024 * 1024) if isinstance(mem_mb, (int, float)) else None
                    except Exception:
                        rss_bytes = None
                    resources_block = {k: v for k, v in {
                        "cpu": cpu_pct,
                        "rss": rss_bytes,
                    }.items() if v is not None}
                app_block = {"name": "G6 Unified", "version": __version__}

                status = {
                    # Use aware UTC timestamp helper for consistency
                    "timestamp": isoformat_z(utc_now()),
                    "cycle": cycle_count,
                    "elapsed": round(elapsed, 3),
                    "interval": interval,
                    "sleep_sec": max(0, interval - elapsed),
                    "app": app_block,
                    "market": market_block,
                    "loop": loop_block,
                    "resources": resources_block,
                    "success_rate_pct": success_rate,
                    "options_last_cycle": options_last,
                    "options_per_minute": per_min,
                    "api_success_rate": api_success,
                    "memory_mb": mem_mb,
                    "cpu_pct": cpu_pct,
                    "readiness_ok": bool(readiness_ok) if readiness_ok is not None else None,
                    "readiness_reason": readiness_reason,
                    "indices": list(index_params.keys()),
                    "indices_info": indices_info,
                    "indices_detail": indices_detail,
                    "health": health_snapshot,
                    "provider": provider_info,
                    "analytics": {},
                    "sinks": sinks_snapshot,
                }
                # Atomic write
                os.makedirs(os.path.dirname(runtime_status_file), exist_ok=True)
                tmp_path = runtime_status_file + '.tmp'
                with open(tmp_path, 'w') as f:
                    json.dump(status, f)
                os.replace(tmp_path, runtime_status_file)
            except Exception:  # pragma: no cover
                pass
        # Publish per-panel JSON for Summary View (best-effort, env-gated)
        try:
            if os.environ.get('G6_ENABLE_PANEL_PUBLISH','').lower() in ('1','true','yes','on'):
                try:
                    from src.summary.publisher import publish_cycle_panels  # type: ignore
                    publish_cycle_panels(
                        indices=index_params.keys() if index_params else [],
                        cycle=cycle_count,
                        elapsed_sec=elapsed,
                        interval_sec=interval,
                        success_rate_pct=success_rate,
                        metrics=metrics,
                        csv_sink=csv_sink,
                        influx_sink=influx_sink,
                        providers=providers,
                    )
                except Exception:
                    pass
        except Exception:
            pass
        # Influx cycle stats (best-effort / optional)
        try:
            if influx_sink and hasattr(influx_sink, 'write_cycle_stats'):
                per_index_counts = None
                try:
                    if metrics and hasattr(metrics, '_per_index_last_cycle_options'):
                        per_index_counts = dict(metrics._per_index_last_cycle_options)
                except Exception:
                    per_index_counts = None
                # reuse success_rate/options_last gathered above if available
                influx_sink.write_cycle_stats(
                    cycle=cycle_count,
                    elapsed=elapsed,
                    success_rate=success_rate,
                    options_last=options_last,
                    per_index=per_index_counts,
                )
        except Exception:
            pass
        if run_once:
            break
        if _max_cycles_env and cycle_count >= _max_cycles_env:
            break
        sleep_time = max(0, interval - elapsed)
        time.sleep(sleep_time)
    # Fallback: if run_once and status file requested but never written (e.g., early failures), emit minimal status
    if run_once and runtime_status_file and not os.path.exists(runtime_status_file):
        try:
            from src.utils.timeutils import ensure_utc_helpers  # type: ignore
            utc_now, isoformat_z = ensure_utc_helpers()  # type: ignore[misc]
        except Exception:
            from datetime import datetime, timezone
            def utc_now():  # type: ignore
                return datetime.now(timezone.utc)
            def isoformat_z(d):  # type: ignore
                return d.isoformat().replace('+00:00','Z')
        minimal = {
            "timestamp": isoformat_z(utc_now()),
            "cycle": cycle_count,
            "elapsed": 0.0,
            "interval": interval,
            "sleep_sec": 0,
            "success_rate_pct": None,
            "options_last_cycle": None,
            "indices": list(index_params.keys()),
            "indices_info": {i: {"ltp": None, "options": None} for i in index_params.keys()},
            "readiness_ok": bool(readiness_ok) if readiness_ok is not None else None,
            "readiness_reason": readiness_reason,
        }
        try:
            os.makedirs(os.path.dirname(runtime_status_file), exist_ok=True)
            tmp_path = runtime_status_file + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(minimal, f)
            os.replace(tmp_path, runtime_status_file)
            logging.debug("Fallback minimal runtime status written")
        except Exception:
            pass

# ---------------- CLI -----------------

def parse_args():
    p = argparse.ArgumentParser(description="Unified G6 Platform")
    p.add_argument('--config', default='config/g6_config.json')
    p.add_argument('--log-level', default='INFO')
    p.add_argument('--log-file', default='logs/g6_platform.log')
    p.add_argument('--interval', type=int, help='Override collection interval')
    p.add_argument('--data-dir', help='Override data directory')
    p.add_argument('--use-enhanced', action='store_true', help='Use enhanced collectors')
    p.add_argument('--market-hours-only', action='store_true', help='Restrict to market hours')
    p.add_argument('--run-once', action='store_true', help='Run a single cycle and exit')
    p.add_argument('--analytics', action='store_true', help='Run analytics block at startup')
    p.add_argument('--validate-auth', action='store_true', help='Fail fast if provider auth/quotes unavailable')
    p.add_argument('--auto-refresh-token', action='store_true', help='Attempt automatic token refresh via token_manager if auth invalid')
    p.add_argument('--interactive-token', action='store_true', help='Allow interactive/manual token acquisition if automated refresh fails')
    p.add_argument('--runtime-status-file', help='Write per-cycle runtime status JSON (for terminal attach UI)')
    p.add_argument('--mock-data', action='store_true', help='Use synthetic mock data provider (skips external API auth)')
    p.add_argument('--version', action='version', version=f'G6 Unified {__version__}')
    # Deprecated: greeks/IV runtime tuning now must come from JSON config 'greeks' block.
    p.add_argument('--compute-greeks', action='store_true', help='[DEPRECATED] Previously toggled local Greek computation (use config.greek.enabled)')
    p.add_argument('--risk-free-rate', type=float, default=0.05, help='[DEPRECATED] Use config.greeks.risk_free_rate')
    p.add_argument('--estimate-iv', action='store_true', help='[DEPRECATED] Use config.greeks.estimate_iv')
    p.add_argument('--iv-max-iterations', type=int, default=100, help='[DEPRECATED] Use config.greeks.iv_max_iterations')
    p.add_argument('--iv-min', type=float, default=0.01, help='[DEPRECATED] Use config.greeks.iv_min')
    p.add_argument('--iv-max', type=float, default=5.0, help='[DEPRECATED] Use config.greeks.iv_max')
    p.add_argument('--metrics-reset', action='store_true', help='Force reset of Prometheus default registry before initializing metrics (dev/debug)')
    p.add_argument('--metrics-custom-registry', action='store_true', help='Use an isolated custom CollectorRegistry (avoids global collisions)')
    p.add_argument('--concise-logs', action='store_true', help='Enable concise option chain logging (single-line summaries)')
    p.add_argument('--verbose-logs', action='store_true', help='Force legacy verbose option/expiry logging (overrides default concise)')
    p.add_argument('--status-poll', type=float, default=0.0, help='If >0, poll the runtime status file internally every N seconds and log a concise summary (requires --runtime-status-file)')
    return p.parse_args()

# ---------------- Main -----------------

def main():
    args = parse_args()
    # No enhanced UI feature flags; pure legacy behavior

    # Mock provider opt-in (before bootstrap to skip auth flow later)
    if args.mock_data:
        os.environ['G6_USE_MOCK_PROVIDER'] = '1'

    # Rich logging hook for attach terminal mode (opt-in via env)
    # Must be before heavy startup logs for best effect
    try:
        if os.environ.get('G6_TERMINAL_MODE', '').lower() == 'attach':
            from rich.logging import RichHandler  # type: ignore
            root = logging.getLogger()
            if not any(isinstance(h, RichHandler) for h in root.handlers):
                rich_handler = RichHandler(rich_tracebacks=False, show_time=False, markup=False)
                rich_handler.setLevel(logging.getLevelName(args.log_level.upper()))
                root.addHandler(rich_handler)
    except Exception:  # pragma: no cover
        pass

    boot = bootstrap(
        config_path=args.config,
        log_level=args.log_level,
        log_file=args.log_file,
        enable_metrics=True,
        metrics_reset=args.metrics_reset,
        metrics_use_custom_registry=args.metrics_custom_registry,
    )
    logging.info(f"Starting G6 Unified Platform v{__version__}")

    config = boot.config
    # Console ASCII enforcement (config default -> env override if not explicitly set)
    try:
        console_cfg = config.get('console', {})  # type: ignore[index]
        if console_cfg.get('force_ascii', True):
            # Only set env if user hasn't explicitly forced unicode
            if os.environ.get('G6_FORCE_UNICODE', '').lower() not in ('1','true','yes','on'):
                os.environ.setdefault('G6_FORCE_ASCII', '1')
    except Exception:
        pass
    # CLI overrides
    if args.interval:
        config['collection'] = {**config.get('collection', {}), 'interval_seconds': args.interval}  # type: ignore[index]
    if args.data_dir:
        config['data_dir'] = args.data_dir  # type: ignore[index]
    # Greeks configuration now sourced ONLY from JSON config; CLI flags ignored (compat logging)
    if 'greeks' not in config:
        config['greeks'] = {}
    deprecated_flags_used = any([
        args.compute_greeks, args.estimate_iv,
        args.risk_free_rate != 0.05,
        args.iv_max_iterations != 100,
        args.iv_min != 0.01,
        args.iv_max != 5.0,
    ])
    if deprecated_flags_used:
        logging.warning("Greeks/IV CLI flags are deprecated and ignored; update your JSON config 'greeks' block instead.")

    # Determine intended provider type from raw config (default kite)
    provider_type = config.get('providers', {}).get('primary', {}).get('type', 'kite')  # type: ignore[index]
    if os.environ.get('G6_USE_MOCK_PROVIDER'):
        provider_type = 'mock'

    # --- Mandatory Kite token acquisition (before ANY provider init) ---
    if str(provider_type).lower() == 'kite':
        try:
            from src.tools.token_manager import acquire_or_refresh_token  # type: ignore
            logging.info("[AUTH] Starting mandatory Kite token validation/acquisition phase...")
            token_ok = acquire_or_refresh_token(auto_open_browser=True, interactive=True, validate_after=True)
            if not token_ok:
                logging.error("[AUTH] Unable to obtain a valid Kite token. Aborting startup.")
                logging.error("Hint: run: python -m src.tools.token_manager --interactive-token")
                return 1
            logging.info("[AUTH] Valid Kite token confirmed. Proceeding with provider initialization.")
        except Exception as e:  # pragma: no cover
            logging.error(f"[AUTH] Unexpected error during token acquisition: {e}")
            return 1
    else:
        logging.info(f"Provider type '{provider_type}' does not require Kite auth flow.")

    def obtain_providers():
        return init_providers(config)

    providers = None
    attempted_refresh = False
    while providers is None:
        try:
            providers = obtain_providers()
        except Exception as e:
            logging.error(f"Provider init failed after successful auth: {e}")
            # At this point auth was mandatory; retrying provider instantiation briefly may help
            if attempted_refresh is False and str(provider_type).lower() == 'kite':
                # One short retry (no extra token refresh; token already validated)
                attempted_refresh = True
                time.sleep(1.5)
                continue
            logging.error("Provider initialization irrecoverable. Exiting.")
            return 1

    # Determine concise default / overrides precedence:
    # verbose flag > env explicit off > explicit concise flag > default on
    try:
        from src.broker.kite_provider import enable_concise_logs  # type: ignore
        if args.verbose_logs:
            enable_concise_logs(False)
        elif args.concise_logs:
            enable_concise_logs(True)
        else:
            # No explicit flag; leave provider's default (already true unless env disabled)
            pass
    except Exception:  # pragma: no cover
        pass

    # -------- Early Readiness Probe (auth / live quote) --------
    def _provider_readiness() -> tuple[bool, str]:
        try:
            # Use facade LTP which internally may call quote path
            ltp = providers.get_ltp('NIFTY')  # type: ignore[union-attr]
            if isinstance(ltp, (int, float)) and ltp > 0:
                return True, f"LTP={ltp}"
            return False, f"Non-positive LTP={ltp}"
        except Exception as e:  # pragma: no cover (exceptional path)
            return False, f"Exception {e}"

    readiness_ok = False
    readiness_reason = ''
    skip_readiness = os.environ.get('G6_SKIP_PROVIDER_READINESS','').lower() in ('1','true','yes','on')
    # Prepare optional internal status polling (thread started later once runtime_status_file known)
    status_poll_thread = None
    status_poll_stop = None
    probe_attempt = 0
    max_probe_attempts = 3  # inclusive attempts
    refresh_used = False  # retained for metrics logic; token already validated earlier
    if skip_readiness:
        readiness_ok = True
        readiness_reason = 'skip-env'
        logging.info("Provider readiness probe skipped via G6_SKIP_PROVIDER_READINESS")
    else:
        while probe_attempt < max_probe_attempts and not readiness_ok:
            readiness_ok, readiness_reason = _provider_readiness()
            if readiness_ok:
                break
            probe_attempt += 1
            logging.warning(
                f"Provider readiness probe failed ({readiness_reason}) attempt {probe_attempt}/{max_probe_attempts}" )
            # Try a one-off token refresh if allowed and not yet tried
            if args.auto_refresh_token and not refresh_used:
                try:
                    from src.tools.token_manager import acquire_or_refresh_token  # type: ignore
                    logging.info("Attempting token refresh due to failed readiness probe...")
                    if acquire_or_refresh_token(auto_open_browser=True, interactive=args.interactive_token):
                        refresh_used = True
                        # Reprobe immediately without sleeping
                        continue
                except Exception as te:  # pragma: no cover
                    logging.error(f"Token refresh during readiness probe failed: {te}")
            if probe_attempt < max_probe_attempts:
                time.sleep(2)

    # Metrics gauge update (safe guarded)
    try:
        if boot.metrics is not None:
            global _PROVIDER_READY_GAUGE  # noqa: PLW0603
            if _PROVIDER_READY_GAUGE is None:
                from prometheus_client import Gauge  # type: ignore
                _PROVIDER_READY_GAUGE = Gauge(
                    'g6_provider_auth_ready',
                    'Provider authentication / live-quote readiness flag',
                    ['provider']
                )
            _PROVIDER_READY_GAUGE.labels(provider='kite').set(1 if readiness_ok else 0)
    except Exception:  # pragma: no cover
        pass

    if not readiness_ok:
        msg = (f"Provider auth/quote readiness NOT confirmed after {probe_attempt} attempts: "
               f"{readiness_reason}")
        if args.validate_auth:
            logging.error(msg + "; exiting due to --validate-auth")
            logging.error("Hint: run: python -m src.tools.token_manager --interactive-token")
            return 1
        logging.warning(msg)
        logging.warning("Continuing. Live quotes may be synthetic or zero until token fixed.")
        logging.info("Remediation steps: 1) export KITE_API_KEY & KITE_ACCESS_TOKEN or .env 2) run token_manager 3) verify system clock.")
    else:
        logging.info(f"Provider readiness confirmed ({readiness_reason})")
    # Early auth validation (before spinning up storage/health threads) if requested
    if providers is not None and args.validate_auth:
        try:
            test_ltp = providers.get_ltp('NIFTY')  # type: ignore[union-attr]
            if not test_ltp or (isinstance(test_ltp, (int, float)) and test_ltp <= 0):
                raise RuntimeError('Received non-positive LTP during auth validation')
            logging.info(f"Auth validation (pre-init) succeeded: NIFTY LTP={test_ltp}")
        except Exception as e:
            logging.error(f"Auth validation failed before startup: {e}")
            logging.error("Tip: refresh token via: python -m src.tools.token_manager --no-autorun")
            return 1

    csv_sink, influx_sink = init_storage(config)
    metrics = boot.metrics
    stop_metrics = boot.stop_metrics
    if providers is None:
        logging.error("Providers initialization failed; exiting.")
        return 1

    apply_circuit_breakers(config, providers)
    # Register health monitor BEFORE starting (we will override provider health check logic)
    health = init_health(config, providers, csv_sink, influx_sink)
    # Replace provider health check with facade-level validation to avoid signature mismatch
    def provider_health():
        try:
            ltp = providers.get_ltp('NIFTY')  # type: ignore[union-attr]
            if not ltp or (isinstance(ltp, (int, float)) and ltp <= 0):
                return {'status': 'unhealthy', 'message': 'Non-positive LTP for NIFTY'}
            return {'status': 'healthy', 'message': 'Provider responsive', 'data': {'ltp': ltp}}
        except Exception as e:
            return {'status': 'unhealthy', 'message': f'Provider error: {e}'}
    # Remove any previously registered 'primary_provider_responsive' to prevent duplicates
    health.health_checks = [hc for hc in health.health_checks if hc.get('name') != 'primary_provider_responsive']
    health.register_health_check('primary_provider_responsive', provider_health)
    health.start()

    # (Validation already performed earlier if flag set)

    # Optional analytics
    # Analytics startup block precedence:
    # 1) CLI --analytics forces True
    # 2) config.features.analytics_startup if True
    analytics_cfg = False
    try:
        analytics_cfg = bool(config.get('features', {}).get('analytics_startup'))  # type: ignore[index]
    except Exception:
        pass
    if args.analytics or analytics_cfg:
        run_analytics_block(providers, config)

    index_params = config.index_params()
    if not index_params:
        logging.warning("index_params is empty - no indices will be collected. Check your config normalization.")
    else:
        logging.info(f"Collecting indices: {', '.join(index_params.keys())}")
    # Emit START structured line for machine/human parse
    try:
        from src.logstream.formatter import format_start
        concise_active = False  # ensure defined for later banner
        try:
            from src.broker.kite_provider import _CONCISE as _PROV_CONCISE  # type: ignore
            concise_active = bool(_PROV_CONCISE)
        except Exception:
            pass
        interval_eff = (
            config.get('collection', {}).get('interval_seconds')
            or config.get('orchestration', {}).get('run_interval_sec', 60)
        )
        logging.info(format_start(version=__version__, indices=len(index_params or {}), interval_s=int(interval_eff), concise=concise_active))
    except Exception:
        concise_active = False
        interval_eff = config.get('orchestration', {}).get('run_interval_sec', 60)
    # ---- Startup Banner (condensed) ----
    try:
        # Fancy console precedence: ENV > config.console.fancy_startup
        fancy_cfg = False
        try:
            fancy_cfg = bool(config.get('console', {}).get('fancy_startup'))  # type: ignore[index]
        except Exception:
            pass
        fancy_env = os.environ.get('G6_FANCY_CONSOLE','').lower() in ('1','true','yes','on')
        fancy = fancy_env or fancy_cfg
        # Unicode / ASCII fallback: if stdout encoding not UTF and unicode not forced, disable fancy & enforce ASCII
        force_unicode = os.environ.get('G6_FORCE_UNICODE','').lower() in ('1','true','yes','on')
        if not force_unicode:
            try:
                _enc = (getattr(sys.stdout, 'encoding', '') or '').lower()
            except Exception:  # pragma: no cover
                _enc = ''
            if _enc and 'utf' not in _enc:
                os.environ.setdefault('G6_FORCE_ASCII','1')
                if fancy:
                    logging.info("Console encoding %s not UTF; disabling fancy Unicode banner", _enc)
                fancy = False
        # Explicit ASCII env wins unless unicode forced
        if os.environ.get('G6_FORCE_ASCII','').lower() in ('1','true','yes','on') and not force_unicode:
            fancy = False
        # If config requests fancy but env not set, export env for downstream modules expecting it
        if fancy_cfg and not fancy_env:
            os.environ['G6_FANCY_CONSOLE'] = '1'
        # Banner enabled precedence: ENV disable overrides; else config.console.startup_banner (default True)
        banner_env_disable = os.environ.get('G6_DISABLE_STARTUP_BANNER', '').lower() in ('1','true','yes','on')
        banner_cfg = True
        try:
            banner_cfg = bool(config.get('console', {}).get('startup_banner', True))  # type: ignore[index]
        except Exception:
            pass
        if not banner_env_disable and banner_cfg:
            # Gather health snapshot
            comp_map = {}
            try:
                for cname, cdata in health.components.items():
                    comp_map[cname] = cdata.get('status','unknown')
            except Exception:
                pass
            chk_map = {}
            try:
                for chk in health.health_checks:
                    chk_map[chk.get('name','?')] = chk.get('status','unknown')
            except Exception:
                pass
            # Debug evaluation of fancy panel conditions
            logging.debug(
                "Fancy panel eval: fancy_cfg=%s fancy_env=%s fancy=%s build_available=%s banner_cfg=%s env_disable=%s",
                fancy_cfg, fancy_env, fancy, bool(build_startup_panel), banner_cfg, banner_env_disable
            )
            # Info-level echo to surface in environments where DEBUG may be suppressed
            logging.info(
                "Startup banner mode: fancy=%s (cfg=%s env=%s) banner_enabled=%s (cfg=%s env_disable=%s)",
                fancy, fancy_cfg, fancy_env, (not banner_env_disable and banner_cfg), banner_cfg, banner_env_disable
            )
            if fancy and build_startup_panel:
                try:
                    # Retrieve metrics metadata if available
                    metrics_meta = None
                    try:
                        from src.metrics.metrics import get_metrics_metadata  # type: ignore
                        metrics_meta = get_metrics_metadata()
                    except Exception:
                        pass
                    panel = build_startup_panel(
                        version=__version__,
                        indices=index_params.keys() if index_params else [],
                        interval=int(interval_eff),
                        concise=concise_active,
                        provider_readiness=readiness_reason,
                        readiness_ok=readiness_ok,
                        components=comp_map,
                        checks=chk_map,
                        metrics_meta=metrics_meta,
                    )
                    logging.info(sanitize_console_text(panel))
                except Exception as e:
                    logging.warning(
                        "Fancy startup panel build failed; falling back to basic banner: %s", e,
                        exc_info=True
                    )
                    fancy = False  # force fallback
            if (not fancy) or (not build_startup_panel):
                # Fallback original simple banner (colored)
                comp_summary = []
                for cname, status in comp_map.items():
                    col = FG_GREEN if status == 'healthy' else FG_RED
                    comp_summary.append(colorize(cname, col, bold=(status!='healthy')))
                checks_summary = []
                for cname, status in chk_map.items():
                    col = FG_GREEN if status == 'healthy' else FG_RED
                    checks_summary.append(colorize(cname, col, bold=(status!='healthy')))
                concise_flag = 'on' if concise_active else 'off'
                now_disp = _dt.datetime.now().strftime('%d-%b-%Y %H:%M:%S')  # local-ok
                indices_list = ', '.join(index_params.keys()) if index_params else 'NONE'
                lines = []
                border = '=' * 70
                lines.append(border)
                lines.append(f" G6 UNIFIED STARTUP  v{__version__}  {now_disp}")
                lines.append(border)
                lines.append(f" Indices: {indices_list}")
                lines.append(f" Interval: {interval_eff}s  Concise: {concise_flag}")
                if comp_summary:
                    lines.append(f" Components: {' '.join(comp_summary)}")
                if checks_summary:
                    lines.append(f" Health Checks: {' '.join(checks_summary)}")
                if readiness_ok:
                    lines.append(colorize(f" Provider readiness: {readiness_reason}", FG_GREEN))
                else:
                    lines.append(colorize(f" Provider readiness: {readiness_reason}", FG_RED, bold=True))
                banner_text = "\n" + "\n".join(lines) + "\n" + border
                logging.info(banner_text)
    except Exception as be:  # pragma: no cover
        logging.debug(f"Startup banner failed: {be}")
    try:
        # Resolve runtime status file path precedence: CLI > ENV > config.console.runtime_status_file
        runtime_status_file = args.runtime_status_file or os.environ.get('G6_RUNTIME_STATUS')
        if not runtime_status_file:
            try:
                runtime_status_file = config.get('console', {}).get('runtime_status_file')  # type: ignore[index]
            except Exception:
                runtime_status_file = None
        if runtime_status_file:
            try:
                os.makedirs(os.path.dirname(runtime_status_file), exist_ok=True)
                logging.info(f"Runtime status file enabled: {runtime_status_file}")
            except Exception as e:
                logging.warning(f"Could not prepare runtime status file directory: {e}")
                runtime_status_file = None
        # Start status poll thread if requested and file path defined
        if args.status_poll and args.status_poll > 0 and runtime_status_file:
            status_poll_stop = threading.Event()
            interval_poll = float(args.status_poll)
            def _status_poll_loop():  # pragma: no cover
                last_cycle_seen = None
                local_stop = status_poll_stop  # capture to avoid closure on mutable
                path = runtime_status_file  # local alias for type narrowing
                while local_stop is not None and not local_stop.is_set():
                    try:
                        if path and os.path.exists(path):
                            import json as _json
                            with open(path,'r') as f:
                                data = _json.load(f)
                            cyc = data.get('cycle')
                            if cyc != last_cycle_seen:
                                last_cycle_seen = cyc
                                ts = data.get('timestamp')
                                sr = data.get('success_rate_pct')
                                opt = data.get('options_last_cycle')
                                elapsed_c = data.get('elapsed')
                                logging.info(f"[status-poll] cycle={cyc} elapsed={elapsed_c}s success={sr}% options={opt} ts={ts}")
                    except Exception:
                        pass
                    if local_stop is not None:
                        local_stop.wait(interval_poll)
            status_poll_thread = threading.Thread(target=_status_poll_loop, name='status-poll', daemon=True)
            status_poll_thread.start()

        collection_loop(
            config,
            providers,  # type: ignore[arg-type]
            csv_sink,
            influx_sink,
            metrics,
            use_enhanced=args.use_enhanced,
            market_hours_only=args.market_hours_only,
            run_once=args.run_once,
            index_params=index_params,
            runtime_status_file=runtime_status_file,
            readiness_ok=readiness_ok,
            readiness_reason=readiness_reason,
            health_monitor=health,
        )
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    finally:
        try:
            health.stop()
        except Exception:
            pass
        try:
            if providers:
                providers.close()  # type: ignore[union-attr]
        except Exception:
            pass
        if callable(stop_metrics):
            stop_metrics()
        # Stop status poll thread
        try:
            if status_poll_stop:
                status_poll_stop.set()
            if status_poll_thread:
                status_poll_thread.join(timeout=1.0)
        except Exception:
            pass
        logging.info("Shutdown complete")

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
