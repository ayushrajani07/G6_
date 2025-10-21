"""Component initialization helpers for orchestrator refactor.

This file extracts logic from `unified_main.py` so that `bootstrap_runtime`
can incrementally construct providers, storage sinks, and health monitor.
Behavior is kept as close as possible to legacy code (no semantic changes) to
minimize regression risk.
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
import os
import time
from collections.abc import Callable
from typing import Any

from src.utils.env_flags import is_truthy_env

logger = logging.getLogger(__name__)

# Declare dynamic symbols up-front so mypy treats later assignments as value rebindings.
ProvidersFacadeT: Any
CompositeProviderT: Any | None = None
create_provider_fn: Callable[..., Any]
CsvSinkT: Any
HealthMonitorT: Any
HealthCheckT: Any
CircuitBreakerT: Any
retryable_fn: Callable[[Callable[..., Any]], Callable[..., Any]]
circuit_protected_fn: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]]
get_error_handler_fn: Callable[..., Any]
ErrorCategoryT: Any
ErrorSeverityT: Any
InfluxSinkT: Any | None = None
NullInfluxSinkT: Any

# Generic note: avoid module-level TypeVar usage in annotations for fallbacks; use Any.

try:  # optional imports preserved; fallbacks for early stages
    from src.collectors.providers_interface import Providers as _ProvidersFacade
    try:
        from src.providers.composite_provider import CompositeProvider as _CompositeProvider
    except Exception:  # pragma: no cover
        _CompositeProvider = None
    from src.health.monitor import HealthMonitor as _HealthMonitor
    from src.providers.factory import create_provider as _create_provider
    from src.storage.csv_sink import CsvSink as _CsvSink
    from src.utils.circuit_breaker import CircuitBreaker as _CircuitBreaker
    from src.utils.circuit_registry import circuit_protected as _circuit_protected
    from src.utils.resilience import HealthCheck as _HealthCheck
    from src.utils.retry import retryable as _retryable
    # Bind to declared names
    ProvidersFacadeT = _ProvidersFacade
    CompositeProviderT = _CompositeProvider
    create_provider_fn = _create_provider
    CsvSinkT = _CsvSink
    HealthMonitorT = _HealthMonitor
    HealthCheckT = _HealthCheck
    CircuitBreakerT = _CircuitBreaker
    retryable_fn = _retryable
    circuit_protected_fn = _circuit_protected
except Exception as _providers_import_err:  # pragma: no cover
    # We failed to import the real Providers facade and related modules. Capture
    # the root exception so operators understand we are in degraded mode.
    logger.warning("[fallback Providers] Import failure activating degraded provider facade: %s", _providers_import_err)
    class _ProvidersFallback:
        """Fallback Providers shim (imports failed).

        Provides a minimal surface so collectors don't crash with AttributeError('get_index_data').
        Implements lightweight price retrieval via primary_provider.get_ltp when available.
        """
        def __init__(self, primary_provider=None, secondary_provider=None):
            self.primary_provider = primary_provider
            self.secondary_provider = secondary_provider
            self.logger = logger
            self._degraded_warned_enrich = False
        # Minimal index data retrieval used by unified collectors
        def get_index_data(self, index_symbol):  # noqa: D401
            prov = self.primary_provider
            if not prov or not hasattr(prov, 'get_ltp'):
                self.logger.warning("[fallback Providers] No primary provider LTP available; returning 0 price for %s", index_symbol)
                return 0, {}
            try:
                ltp_obj = prov.get_ltp([( 'NSE', 'NIFTY 50')]) if index_symbol == 'NIFTY' else prov.get_ltp([(index_symbol,)])  # permissive
                # Accept either mapping or scalar
                if isinstance(ltp_obj, (int, float)):
                    price = float(ltp_obj)
                elif isinstance(ltp_obj, dict) and ltp_obj:
                    first_val = next(iter(ltp_obj.values()))
                    if isinstance(first_val, dict):
                        raw_price = first_val.get('last_price', 0)
                        try:
                            price = float(raw_price) if raw_price is not None else 0.0
                        except Exception:
                            price = 0.0
                    else:
                        try:
                            price = float(first_val)
                        except Exception:
                            price = 0.0
                else:
                    price = 0.0
                return price, {}
            except Exception:
                self.logger.debug("[fallback Providers] get_index_data failure for %s", index_symbol, exc_info=True)
                return 0, {}
        def get_ltp(self, index_symbol):  # noqa: D401
            price, _ = self.get_index_data(index_symbol)
            return price
        def get_atm_strike(self, index_symbol):  # noqa: D401
            try:
                price = self.get_ltp(index_symbol)
                try:
                    from src.utils.index_registry import get_index_meta
                    meta_step = float(get_index_meta(index_symbol).step)
                except Exception:
                    meta_step = 100.0 if index_symbol in ("BANKNIFTY","SENSEX") else 50.0
                if meta_step <= 0:
                    meta_step = 50.0
                return round(price/meta_step)*meta_step
            except Exception:
                return 0
        def resolve_expiry(self, index_symbol, expiry_rule):  # noqa: D401
            """Synthetic expiry resolver (very naive).

            Supports tokens: this_week, next_week, this_month, next_month or ISO date.
            Falls back to today + offsets; purely to satisfy enhanced collector gate.
            """
            try:
                import datetime as _d
                if isinstance(expiry_rule, str) and len(expiry_rule) == 10 and expiry_rule[4] == '-' and expiry_rule[7] == '-':
                    y,m,d = expiry_rule.split('-'); return _d.date(int(y), int(m), int(d))
                today = _d.date.today()
                if expiry_rule == 'this_week':
                    return today + _d.timedelta(days=1)
                if expiry_rule == 'next_week':
                    return today + _d.timedelta(days=8)
                if expiry_rule == 'this_month':
                    nxt = (today.replace(day=28) + _d.timedelta(days=4)).replace(day=1) - _d.timedelta(days=1)
                    return nxt
                if expiry_rule == 'next_month':
                    first_next = (today.replace(day=28) + _d.timedelta(days=4)).replace(day=1)
                    nxt = (first_next.replace(day=28) + _d.timedelta(days=4)).replace(day=1) - _d.timedelta(days=1)
                    return nxt
                return today + _d.timedelta(days=5)
            except Exception:
                return _dt.date.today()
        def get_option_instruments(self, index_symbol, expiry_date, strikes):  # noqa: D401
            synthetic = []
            try:
                lot = 50 if index_symbol == 'NIFTY' else 25
                if not hasattr(strikes, '__iter__'):
                    return []
                import datetime as _d
                if not isinstance(expiry_date, _d.date):
                    expiry_date = _d.date.today()
                exp_str = expiry_date.strftime('%y%b').upper()
                for s in strikes:
                    try:
                        k = int(s)
                        ce = {
                            'instrument_token': k*10+1,
                            'tradingsymbol': f"{index_symbol}{exp_str}{k}CE",
                            'name': index_symbol,
                            'last_price': 0.0,
                            'expiry': expiry_date,
                            'strike': float(k),
                            'instrument_type': 'CE',
                            'segment': 'NFO-OPT',
                            'exchange': 'NFO'
                        }
                        pe = ce.copy()
                        pe.update({'instrument_token': k*10+2, 'tradingsymbol': f"{index_symbol}{exp_str}{k}PE", 'instrument_type': 'PE'})
                        synthetic.append(ce); synthetic.append(pe)
                    except Exception:
                        continue
            except Exception:
                return []
            return synthetic
        def enrich_with_quotes(self, instruments):  # noqa: D401
            """Best-effort enrichment used when real Providers facade failed to import.

            Produces a dict keyed by tradingsymbol with baseline zero metrics so the
            unified collectors downstream can proceed (they may apply synthetic quote
            fallback anyway). Real market data will not be available in this mode.
            """
            if not self._degraded_warned_enrich:
                self.logger.warning("[fallback Providers] enrich_with_quotes using degraded stub (no real quote API).")
                self._degraded_warned_enrich = True
            out = {}
            enriched_count = 0
            for inst in instruments:
                sym = inst.get('tradingsymbol', '') if isinstance(inst, dict) else ''
                if not sym:
                    continue
                enriched = inst.copy() if isinstance(inst, dict) else {'tradingsymbol': sym}
                enriched.setdefault('last_price', 0.0)
                enriched.setdefault('volume', 0)
                enriched.setdefault('oi', 0)
                enriched.setdefault('avg_price', 0)
                enriched['synthetic_quote'] = True
                out[sym] = enriched
                enriched_count += 1
            # Emit minimal counters so dashboards are not empty in degraded mode
            try:  # switch to generated metric helpers (lazy registration)
                from src.metrics.generated import (
                    m_api_calls_total_labels,
                    m_quote_enriched_total_labels,
                )
                def _safe_inc(lbl, amt=1):
                    try:
                        if lbl:
                            lbl.inc(amt)
                    except Exception:
                        pass
                if enriched_count:
                    lbl_q = m_quote_enriched_total_labels('fallback'); _safe_inc(lbl_q, enriched_count)
                if instruments:  # one synthetic API call per enrich invocation
                    lbl_api = m_api_calls_total_labels('fallback_enrich','success'); _safe_inc(lbl_api)
            except Exception:
                pass
            return out
        def __getattr__(self, name):  # final fallback for unimplemented attrs
            raise AttributeError(name)
    # Annotate dynamic shims as Any/Callable so mypy accepts later rebinding.
    ProvidersFacadeT = _ProvidersFallback
    create_provider_fn = (lambda *a, **k: None)
    CsvSinkT = object
    HealthMonitorT = object
    HealthCheckT = object
    CircuitBreakerT = object
    def _identity_retryable(func: Callable[..., Any]) -> Callable[..., Any]:
        return func
    retryable_fn = _identity_retryable
    def _noop_circuit_protected(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _dec(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn
        return _dec
    circuit_protected_fn = _noop_circuit_protected

# --- Defensive re-imports -------------------------------------------------
# The broad optional import block above is intentionally coarse to keep the
# initial refactor low‑risk. However, if ANY of those imports fail (including
# optional providers/health modules), CsvSink gets replaced by a bare
# 'object' sentinel, causing TypeError("object() takes no arguments") inside
# init_storage(). Here we attempt a targeted re-import of CsvSink so that a
# non-critical import failure (e.g. provider plugin missing) does not disable
# storage initialization entirely.
try:
    if 'CsvSinkT' in globals() and getattr(CsvSinkT, '__name__', '') == 'object':
        from src.storage.csv_sink import CsvSink as _RecoveredCsvSink
        CsvSinkT = _RecoveredCsvSink
        logger.debug("Recovered real CsvSink after broad optional import fallback")
    # Attempt recovery of create_provider if it was downgraded to lambda None
    if 'create_provider_fn' in globals() and getattr(create_provider_fn, '__name__', '') == '<lambda>':
        try:
            from src.providers.factory import create_provider as _RecoveredCreate
            create_provider_fn = _RecoveredCreate
            logger.debug("Recovered real create_provider after broad optional import fallback")
        except Exception:
            logger.debug("create_provider recovery attempt failed", exc_info=True)
except Exception as _csv_reimport_err:  # pragma: no cover
    # Provide a minimal no-op CsvSink to preserve downstream logic; metrics &
    # providers can still function and orchestrator will fall back to unified
    # collectors with synthetic provider if necessary.
    class _NullCsvSink:
        def __init__(self, base_dir: str):  # mimic signature
            self.base_dir = base_dir
            self.logger = logger
            self.metrics = None
            logger.warning("Using _NullCsvSink placeholder (CsvSink import failed: %s)", _csv_reimport_err)
        def attach_metrics(self, m):  # noqa: D401 - simple passthrough
            self.metrics = m
    CsvSinkT = _NullCsvSink

try:
    from src.error_handling import ErrorCategory as _EC
    from src.error_handling import ErrorSeverity as _ES
    from src.error_handling import get_error_handler as _geh
    get_error_handler_fn = _geh
    ErrorCategoryT = _EC
    ErrorSeverityT = _ES
except Exception:  # pragma: no cover
    def _get_error_handler_fallback():
        class _EH:
            def handle_error(self, *a, **k):
                pass
        return _EH()
    class _ErrorCategoryFallback:
        INITIALIZATION = 'init'
        FILE_IO = 'file'
        DATABASE = 'db'
        PROVIDER_API = 'provider'
    class _ErrorSeverityFallback:
        HIGH = 'high'
        MEDIUM = 'med'
        LOW = 'low'
    get_error_handler_fn = _get_error_handler_fallback
    ErrorCategoryT = _ErrorCategoryFallback
    ErrorSeverityT = _ErrorSeverityFallback

try:  # influx optional
    from src.storage.influx_sink import InfluxSink as _RealInfluxSink
    from src.storage.influx_sink import NullInfluxSink as _RealNullInfluxSink
    InfluxSinkT = _RealInfluxSink
    NullInfluxSinkT = _RealNullInfluxSink
except Exception:  # pragma: no cover
    InfluxSinkT = None
    class _NullInfluxSink:
        def __init__(self):
            self._fallback = True
        # No-op writer methods expected by collectors
        def write_options_data(self, *_, **__):  # returns count written (0 in degraded mode)
            return 0
        def write_index_overview(self, *_, **__):  # compatibility no-op
            return 0
    NullInfluxSinkT = _NullInfluxSink

# --- Late resilience patches for missing health modules ----------------------
# If the broad optional import block earlier downgraded HealthMonitor/HealthCheck
# to the 'object' sentinel, provide lightweight stubs so that bootstrap does not
# fail partway (which previously prevented ctx.providers from being assigned).
if 'HealthMonitorT' in globals() and HealthMonitorT is object:
    class _NullHealthMonitor:
        def __init__(self, check_interval: int = 60, *_, **__):
            self.check_interval = check_interval
            self._components: dict[str, Any] = {}
        def register_component(self, name, component):
            self._components[name] = component
        def register_health_check(self, name, fn):  # pragma: no cover - minimal
            pass
        def __repr__(self):  # pragma: no cover
            return f"<NullHealthMonitor interval={self.check_interval}>"
    HealthMonitorT = _NullHealthMonitor
    logger.debug("HealthMonitor module missing; using _NullHealthMonitor stub")

if 'HealthCheckT' in globals() and HealthCheckT is object:
    class _NullHealthCheck:
        @staticmethod
        def check_storage(csv_sink):  # pragma: no cover - simple always-OK
            return True
    HealthCheckT = _NullHealthCheck
    logger.debug("HealthCheck module missing; using _NullHealthCheck stub")


def init_providers(config) -> Any:
    if os.environ.get('G6_USE_MOCK_PROVIDER'):
        import random
        class MockProvider:  # minimal facade-compatible surface
            def __init__(self):
                self._start = time.time()
                random.seed(int(self._start))
                try:
                    from src.utils.index_registry import get_index_meta
                    self._bases = {s: float(get_index_meta(s).synthetic_atm) for s in ['NIFTY','BANKNIFTY','FINNIFTY','SENSEX']}
                except Exception:
                    self._bases = {'NIFTY': 20000.0, 'BANKNIFTY': 45000.0, 'FINNIFTY': 21000.0, 'SENSEX': 66000.0}
                self._prices = dict(self._bases)
            def _symbol(self, name):
                u = str(name).upper()
                for k in self._bases.keys():
                    if u.startswith(k):
                        return k
                return 'NIFTY'
            def _tick(self, sym):
                base = self._bases.get(sym, 10000.0)
                cur = self._prices.get(sym, base)
                t = time.time() - self._start
                wave = math.sin(t/30.0) * base * 0.0015
                noise = random.uniform(-1,1) * base * 0.0005
                pull = (base - cur) * 0.01
                nxt = cur + pull + wave + noise
                low, high = base*0.99, base*1.01
                nxt = max(low, min(high, nxt))
                self._prices[sym] = nxt
                return nxt
            def get_ltp(self, instruments):  # pragma: no cover
                if isinstance(instruments, (list, tuple)):
                    out = {}
                    for inst in instruments:
                        sym = self._symbol(inst if isinstance(inst, str) else inst[1] if isinstance(inst, (list, tuple)) and len(inst)>=2 else inst)
                        out[inst] = {"last_price": round(self._tick(sym),2)}
                    return out
                return round(self._tick(self._symbol(instruments)), 2)
            logger.warning("[MOCK] Using synthetic MockProvider (no external API calls / auth).")
        return ProvidersFacadeT(primary_provider=MockProvider())
    pconf = config.get('providers', {}).get('primary', {})
    ptype = pconf.get('type', 'kite').lower()
    provider = create_provider_fn(ptype, pconf)
    if provider is None:
        class _SyntheticProvider:  # lightweight placeholder
            def __init__(self):
                self._start = time.time()
                # Precompute a simple rolling set of future expiries (next 12 calendar days)
                # so that rule-based resolution (this_week, next_week, etc.) and explicit
                # get_expiry_dates calls do not fail in synthetic mode.
                import datetime as _dt
                today = _dt.date.today()
                self._expiries = [today + _dt.timedelta(days=i) for i in range(1, 15)]
            def get_expiry_dates(self, index_symbol: str):  # pragma: no cover - simple deterministic list
                return list(self._expiries)
            def resolve_expiry(self, index_symbol: str, expiry_rule: str):  # basic rule mapping
                try:
                    rule = (expiry_rule or '').lower()
                    exp_list = self.get_expiry_dates(index_symbol)
                    if not exp_list:
                        raise ValueError('no expiries')
                    if rule in ('this_week','thismonth','this_month','thisweek'):
                        return exp_list[0]
                    if rule in ('next_week','nextweek') and len(exp_list) >= 2:
                        return exp_list[1]
                    if rule in ('this_month','this_month'):  # already handled above but kept for clarity
                        return exp_list[min(len(exp_list)-1, 3)]
                    if rule in ('next_month','nextmonth'):
                        return exp_list[min(len(exp_list)-1, 7)]
                    # Fallback: treat as explicit ISO date if format matches
                    if len(rule) == 10 and rule[4] == '-' and rule[7] == '-':
                        y,m,d = rule.split('-')
                        import datetime as _dt
                        return _dt.date(int(y),int(m),int(d))
                    return exp_list[0]
                except Exception:
                    # Final fallback: first future expiry
                    exp_list = self.get_expiry_dates(index_symbol)
                    return exp_list[0] if exp_list else None
            def get_ltp(self, instruments):  # very basic increasing counter
                base = 10000 + int((time.time() - self._start) * 10)
                if isinstance(instruments, (list, tuple)):
                    return {inst: {"last_price": base} for inst in instruments}
                return {instruments: {"last_price": base}}
        logger.warning("Provider factory returned None; using synthetic placeholder provider (no real market data).")
        provider = _SyntheticProvider()
    providers_wrapper = ProvidersFacadeT(primary_provider=provider)
    metrics: Any = None  # optional metrics not wired here
    # Optional composite provider integration (env gated)
    try:
        if is_truthy_env('G6_COMPOSITE_PROVIDER'):
            extra = []
            # Placeholder: attempt to load secondary provider if configured via env (dynamically import path)
            sec_path = os.environ.get('G6_SECONDARY_PROVIDER_PATH')
            if sec_path:
                try:
                    module_name, class_name = sec_path.rsplit(':',1)
                    mod = __import__(module_name, fromlist=[class_name])
                    cls = getattr(mod, class_name)
                    extra.append(cls())
                except Exception:
                    logger.warning("Failed loading secondary provider from %s", sec_path)
            if extra and (CompositeProviderT is not None):
                try:
                    cp = CompositeProviderT([provider] + extra, metrics=metrics, name='primary_cluster')
                    # Wrap composite under Providers facade for downstream compatibility
                    providers_wrapper.primary_provider = cp
                except Exception:
                    logger.debug("CompositeProvider construction failed", exc_info=True)
    except Exception:
        pass
    return providers_wrapper


def init_storage(config) -> tuple[Any, Any]:
    from src.utils.path_utils import resolve_path  # local import to mirror legacy
    data_dir = resolve_path(config.data_dir(), create=True)
    try:
        storage_cfg = config.get('storage', {})
        os.environ.setdefault('G6_CSV_BUFFER_SIZE', str(storage_cfg.get('csv_buffer_size', 0)))
        os.environ.setdefault('G6_CSV_MAX_OPEN_FILES', str(storage_cfg.get('csv_max_open_files', 64)))
        os.environ.setdefault('G6_CSV_FLUSH_INTERVAL', str(storage_cfg.get('csv_flush_interval_seconds', 2.0)))
    except Exception:
        pass
    csv_sink_ctor: Any = CsvSinkT
    csv_sink = csv_sink_ctor(base_dir=data_dir)
    influx: Any = None  # ensure defined for all control paths
    influx_cfg = config.get('influx', {})
    try:
        sc = config.get('storage', {})
        if isinstance(sc.get('influx'), dict):
            influx_cfg = sc.get('influx')
    except Exception:
        pass
    # Support both top-level influx and nested storage.influx and legacy 'enabled' key
    enabled_flag = bool(influx_cfg.get('enable') or influx_cfg.get('enabled'))
    # Test-friendly override: when G6_INFLUX_OPTIONAL is truthy (set by sitecustomize under pytest),
    # allow running with a NullInfluxSink even if Influx is disabled or client import is missing.
    try:
        influx_optional = is_truthy_env('G6_INFLUX_OPTIONAL')
    except Exception:
        influx_optional = False
    # Influx is mandatory for the platform; enforce enablement and client availability unless optional flag is set.
    if not influx_optional:
        if InfluxSinkT is None:
            raise RuntimeError("InfluxDB client not available; install influxdb-client and ensure import is working (Influx is mandatory).")
        if not enabled_flag:
            raise RuntimeError("InfluxDB is mandatory but disabled in config; set storage.influx.enable=true.")
    else:
        # Optional mode: proceed with a NullInfluxSink if disabled or client missing.
        if (not enabled_flag) or (InfluxSinkT is None):
            try:
                influx = NullInfluxSinkT()
                return csv_sink, influx
            except Exception:
                # Fallback to no influx reference; downstream code should handle gracefully in tests
                influx = None
                return csv_sink, influx
    if enabled_flag and (InfluxSinkT is not None):
        try:
            # Allow environment substitution for token if provided as ${VAR}
            _token_raw = influx_cfg.get('token') or os.environ.get('INFLUX_TOKEN', '')
            if isinstance(_token_raw, str) and _token_raw.startswith('${') and _token_raw.endswith('}'):
                _env_key = _token_raw[2:-1]
                _token = os.environ.get(_env_key, '')
            else:
                _token = _token_raw
            # Allow env override for URL to support runtime port changes without editing config
            _url = os.environ.get('G6_INFLUX_URL') or influx_cfg.get('url', 'http://localhost:8086')
            influx = InfluxSinkT(
                url=_url,
                token=_token,
                org=influx_cfg.get('org', ''),
                bucket=influx_cfg.get('bucket', 'g6_options'),
                batch_size=int(influx_cfg.get('batch_size', 500)),
                flush_interval=float(influx_cfg.get('flush_interval_seconds', 1.0)),
                max_queue_size=int(influx_cfg.get('max_queue_size', 10000)),
                max_retries=int(influx_cfg.get('max_retries', 3)),
                backoff_base=float(influx_cfg.get('backoff_base', 0.25)),
                breaker_fail_threshold=int(influx_cfg.get('breaker_failure_threshold', 5)),
                breaker_reset_timeout=float(influx_cfg.get('breaker_reset_timeout', 30.0)),
                pool_min_size=int(influx_cfg.get('pool_min_size', 1)),
                pool_max_size=int(influx_cfg.get('pool_max_size', 2)),
            )
        except Exception as e:
            # Hard fail: Influx mandatory
            raise RuntimeError(f"InfluxDB initialization failed (mandatory): {e}")
    return csv_sink, influx


def init_health(config, providers, csv_sink, influx_sink) -> Any:
    hcfg = config.get('health', {})
    hm_ctor: Any = HealthMonitorT
    hm = hm_ctor(check_interval=hcfg.get('check_interval', 60))
    try:
        fn = getattr(hm, 'register_component', None)
        if callable(fn):
            try: fn('providers', providers)
            except Exception: pass
            try: fn('csv_sink', csv_sink)
            except Exception: pass
            if influx_sink:
                try: fn('influx_sink', influx_sink)
                except Exception: pass
        rhc = getattr(hm, 'register_health_check', None)
        if callable(rhc):
            try:
                rhc('csv_storage', lambda: getattr(HealthCheckT, 'check_storage', lambda *_: True)(csv_sink))
            except Exception:
                pass
    except Exception:
        pass
    return hm


def apply_circuit_breakers(config, providers):
    try:
        adaptive_on = is_truthy_env('G6_ADAPTIVE_CB_PROVIDERS')
    except Exception:
        adaptive_on = False
    try:
        retries_on = is_truthy_env('G6_RETRY_PROVIDERS')
    except Exception:
        retries_on = False
    prov = getattr(providers, 'primary_provider', None)
    if adaptive_on and prov:
        if hasattr(prov, 'get_quote'):
            base = prov.get_quote
            if retries_on:
                base = retryable_fn(base)
            prov.get_quote = circuit_protected_fn('provider.primary.get_quote')(base)
        if hasattr(prov, 'get_ltp'):
            base = prov.get_ltp
            if retries_on:
                base = retryable_fn(base)
            prov.get_ltp = circuit_protected_fn('provider.primary.get_ltp')(base)
        sec = getattr(providers, 'secondary_provider', None)
        if sec:
            if hasattr(sec, 'get_quote'):
                base = sec.get_quote
                if retries_on:
                    base = retryable_fn(base)
                sec.get_quote = circuit_protected_fn('provider.secondary.get_quote')(base)
            if hasattr(sec, 'get_ltp'):
                base = sec.get_ltp
                if retries_on:
                    base = retryable_fn(base)
                sec.get_ltp = circuit_protected_fn('provider.secondary.get_ltp')(base)
        return
    # legacy simple breaker
    circuit_cfg = config.get('health', {}).get('circuit_breaker', {})
    if not circuit_cfg:
        return
    failure_threshold = circuit_cfg.get('failure_threshold', 5)
    reset_timeout = circuit_cfg.get('reset_timeout', 300)
    if prov:
        if hasattr(prov, 'get_quote'):
            cb_ctor: Any = CircuitBreakerT
            prov.get_quote = cb_ctor('api_quote', failure_threshold, reset_timeout)(prov.get_quote)
        if hasattr(prov, 'get_ltp'):
            cb_ctor2: Any = CircuitBreakerT
            prov.get_ltp = cb_ctor2('api_ltp', failure_threshold, reset_timeout)(prov.get_ltp)

__all__ = [
    'init_providers',
    'init_storage',
    'init_health',
    'apply_circuit_breakers',
]
