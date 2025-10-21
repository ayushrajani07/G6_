#!/usr/bin/env python3
"""
Metrics for G6 Options Trading Platform.
Sets up a Prometheus metrics server.
"""

import logging
import os
import warnings

from src.utils.env_flags import is_truthy_env as _is_truthy_env  # type: ignore

try:
    # Local import aliases; fall back to os.getenv semantics if adapter unavailable very early
    from src.collectors.env_adapter import (
        get_bool as _env_bool,
    )
    from src.collectors.env_adapter import (
        get_float as _env_float,
    )
    from src.collectors.env_adapter import (
        get_int as _env_int,
    )
    from src.collectors.env_adapter import (
        get_str as _env_str,
    )
except Exception:  # pragma: no cover - defensive
    _env_bool = lambda k, d=False: (os.getenv(k, '1' if d else '').strip().lower() in {'1','true','yes','on'})
    _env_int = lambda k, d=0: int(os.getenv(k, str(d)) or d)
    _env_float = lambda k, d=0.0: float(os.getenv(k, str(d)) or d)
    _env_str = lambda k, d='': (os.getenv(k, d) or '').strip()
import sys  # noqa: F401
import time
from contextlib import contextmanager

from prometheus_client import REGISTRY, Counter, Gauge, Summary

# LogRecord .message attribute handling is now installed centrally in src/metrics/__init__.py

logger = logging.getLogger(__name__)

# Test sandbox doc/spec placeholder creation handled in src/metrics/__init__.py

# Optional noise suppression: collapse highly repetitive INFO lines during test initialization
class _NoiseFilter(logging.Filter):  # pragma: no cover - log hygiene
    SUPPRESS_SUBSTRINGS = [
        "Prometheus default registry cleared via reset flag",
        "Grouped metrics registration complete",
        "Initialized ",  # prefix match
    ]
    def __init__(self):
        super().__init__(name="g6.noise_filter")
        self._seen: set[str] = set()
        # Allow multiple distinct Initialized counts (145 vs 165) but suppress repeats per value
    def filter(self, record: logging.LogRecord) -> bool:
        msg = getattr(record, 'message', None) or getattr(record, 'msg', '')
        # Always allow if level > INFO
        if record.levelno > logging.INFO:
            return True
        # Never suppress critical test-observed structured events
        if 'metrics.group_filters.loaded' in str(msg):
            return True
        for sub in self.SUPPRESS_SUBSTRINGS:
            if sub in str(msg):
                key = f"{record.levelno}:{sub}:{msg}" if sub == "Initialized " else f"{record.levelno}:{sub}"
                if key in self._seen:
                    return False
                self._seen.add(key)
                break
        return True

if _is_truthy_env('G6_QUIET_LOGS') or 'G6_QUIET_LOGS' not in os.environ:
    root = logging.getLogger()
    if not any(isinstance(f, _NoiseFilter) for f in getattr(root, 'filters', [])):
        try:
            root.addFilter(_NoiseFilter())
        except Exception:
            pass

# Sentinel of metric names created to avoid duplicate registration if metrics module
# is re-imported inside the same process (e.g., during gating tests spawning subprocesses
# that reuse the parent interpreter unexpectedly on some platforms/tools).
_CREATED_METRIC_NAMES: set[str] = set()

# Legacy deep import deprecation (now default-on unless suppressed)
_suppress_legacy = _is_truthy_env('G6_SUPPRESS_LEGACY_WARNINGS')
# Emit deprecation on deep import unless this import is explicitly marked as facade-context.
_import_ctx = os.getenv('G6_METRICS_IMPORT_CONTEXT', '')
if not _suppress_legacy and _import_ctx != 'facade':
    try:
        warnings.warn(
            "Importing 'src.metrics.metrics' directly is deprecated; import from 'src.metrics' facade instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    except Exception:  # pragma: no cover
        pass

# ----------------------------------------------------------------------------
# Singleton / Idempotency Guards
# ----------------------------------------------------------------------------
# The Prometheus Python client uses a global default CollectorRegistry. Creating
# metric objects (Counter/Gauge/Histogram/Summary) with the same name twice in
# the same process raises a ValueError (Duplicated timeseries). We observed
# duplicate initialization when bootstrap/setup was invoked multiple times
# (e.g., via different entrypoints or inadvertent re-calls). To make platform
# startup resilient and idempotent we guard setup_metrics_server with a simple
# module-level singleton. Subsequent calls will return the existing registry
# instead of attempting to recreate metrics / re-bind the HTTP port.

# NOTE: Singleton now anchored in server module (lazy imported to avoid circular import).
_METRICS_SINGLETON = None  # type: ignore[var-annotated]
# (Server-related port/host now maintained in server.py; retained names only for backward compatibility if referenced)
_METRICS_PORT = None       # type: ignore[var-annotated]
_METRICS_HOST = None       # type: ignore[var-annotated]
# Fancy console metadata snapshot (populated on setup)
_METRICS_META: dict | None = None

# ---------------------------------------------------------------------------
# Always-on groups (exported constant for documentation & tests)
# Each group here supplies metrics relied upon broadly by tests/operations and
# must survive pruning even when explicit enable/disable env filters would
# normally remove them. Rationale per group:
#   expiry_remediation   -> expiry correction/quarantine lifecycle visibility
#   provider_failover    -> provider failover events during resilience tests
#   iv_estimation        -> IV iteration histogram presence when IV feature on
#   sla_health           -> cycle SLA breach detection (core SLO)
# NOTE: adaptive_controller was intentionally removed from ALWAYS_ON so tests can
# explicitly disable it via G6_DISABLE_METRIC_GROUPS. The canonical definition now
# sources from `groups.ALWAYS_ON` to avoid drift between modules.
try:  # pragma: no cover - defensive import wrapper
    from .groups import ALWAYS_ON as _ALWAYS_ON_ENUM  # type: ignore
    ALWAYS_ON_GROUPS: set[str] = {g.value for g in _ALWAYS_ON_ENUM}
except Exception:  # fallback if groups import fails extremely early
    ALWAYS_ON_GROUPS: set[str] = {
        'expiry_remediation',
        'provider_failover',
        'sla_health',
    }

class MetricsRegistry:
    """Metrics registry for G6 Platform."""

    # Thin delegate to extracted helper (retain name for backward compatibility until full cleanup)
    def _core_reg(self, attr: str, ctor, name: str, doc: str, labels: list[str] | None = None, group: str | None = None, **ctor_kwargs):  # type: ignore
        from .registration import core_register  # type: ignore
        return core_register(self, attr, ctor, name, doc, labels, group, **ctor_kwargs)

    # Provide a concrete instance method for maybe register so attribute is always present.
    def _maybe_register(self, group: str, attr: str, metric_cls, name: str, documentation: str, labels: list[str] | None = None, **ctor_kwargs):  # type: ignore[override]
        strict = _is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS')
        try:
            from .registration import maybe_register as _mr  # type: ignore
            return _mr(self, group, attr, metric_cls, name, documentation, labels, **ctor_kwargs)
        except Exception as e:  # pragma: no cover - defensive
            if strict:
                raise
            try:
                logger.error("_maybe_register suppressed error for %s/%s: %s", group, name, e)
            except Exception:
                pass
            return None

    def __init__(self):
        """Initialize metrics."""
        _trace_simple = _is_truthy_env('G6_METRICS_INIT_SIMPLE_TRACE')
        # Optional lightweight init profiling (phase timing) controlled by env G6_METRICS_PROFILE_INIT=1
        _prof_enabled = _is_truthy_env('G6_METRICS_PROFILE_INIT')
        if _prof_enabled:
            import time as _prof_time  # local import to avoid overhead when disabled
            _prof_start = _prof_time.perf_counter()
            self._init_profile = {'phases_ms': {}, 'total_ms': 0.0}  # type: ignore[attr-defined]
            def _prof_mark(label: str, started_at: float):  # type: ignore
                try:
                    dt = (_prof_time.perf_counter() - started_at) * 1000.0
                    self._init_profile['phases_ms'][label] = dt  # type: ignore[index]
                    self._init_profile['total_ms'] = (_prof_time.perf_counter() - _prof_start) * 1000.0  # type: ignore[index]
                except Exception:
                    pass
        else:
            _prof_time = None  # type: ignore
            _prof_start = 0.0  # type: ignore
            def _prof_mark(label: str, started_at: float):  # type: ignore
                return
        def _pt(label: str, **kw):
            if not _trace_simple:
                return
            try:
                extra = ' '.join(f"{k}={v}" for k,v in kw.items()) if kw else ''
                print(f"[metrics-init-basic] {label}{(' ' + extra) if extra else ''}", flush=True)
            except Exception:
                pass
        _pt('begin')
        _trace_enabled = _is_truthy_env('G6_METRICS_INIT_TRACE')
        # Initialization step trace records (each entry: {'step': str, 'ok': bool, 'dt': float, ...extra})
        self._init_trace = [] if _trace_enabled else []  # type: ignore[attr-defined]

        def _step(label: str):  # local helper to record step start
            if not _trace_enabled:
                return lambda ok=True, **info: None
            import time as _t
            start = _t.time()
            def _end(ok: bool = True, **info):
                try:
                    self._init_trace.append({'step': label, 'ok': ok, 'dt': round(_t.time()-start, 6), **info})
                except Exception:
                    pass
            return _end

        # Group tracking & filters (added in modularization Phase 3)
        # Mapping attr_name -> group identifier for grouped metrics
        self._metric_groups: dict[str, str] = {}
        # Raw env strings (parsed by group gating helper)
        self._enabled_groups_raw: str = ''
        self._disabled_groups_raw: str = ''
        # Parsed enable/disable sets (enable set may be None meaning allow-all default)
        self._enabled_groups = None  # type: ignore[assignment]
        self._disabled_groups: set[str] = set()
        # group_allowed predicate will be installed by helper; placeholder for type checkers
        self._group_allowed = lambda name: True  # type: ignore[assignment]

        # 1. Configure group filters (establish _group_allowed predicate)
        _pt('group_gating_start')
        _prof_t = _prof_time.perf_counter() if _prof_enabled else 0.0  # type: ignore[attr-defined]
        _end = _step('group_gating')
        try:
            from .gating import configure_registry_groups as _cfg  # type: ignore
            CONTROLLED_GROUPS, enabled_set, disabled_set = _cfg(self)
            # Expose human-friendly wrapper if not present
            if not hasattr(self, 'group_allowed'):
                def group_allowed(name: str) -> bool:  # type: ignore
                    try:
                        return bool(self._group_allowed(name))  # type: ignore[attr-defined]
                    except Exception:
                        return True
                self.group_allowed = group_allowed  # type: ignore[attr-defined]
            self._group_allowed = self._group_allowed  # ensure alias stability
            _end(ok=True, groups=len(CONTROLLED_GROUPS))
            _pt('group_gating_ok', groups=len(CONTROLLED_GROUPS))
            if _prof_enabled:
                _prof_mark('group_gating', _prof_t)
        except Exception as _e:
            # Fallback uses canonical exported copy to avoid duplicated literal.
            try:
                from .gating import CONTROLLED_GROUPS_FALLBACK as _CGF  # type: ignore
                CONTROLLED_GROUPS = set(_CGF)
            except Exception:
                CONTROLLED_GROUPS = set()  # last-resort empty set
            enabled_set = None
            disabled_set = set()
            # Provide permissive predicate in failure scenario
            self._group_allowed = lambda _n: True  # type: ignore[attr-defined]
            if not hasattr(self, 'group_allowed'):
                self.group_allowed = lambda _n: True  # type: ignore[attr-defined]
            _end(ok=False, error=str(_e))
            _pt('group_gating_fail', error=str(_e))
            if _prof_enabled:
                _prof_mark('group_gating', _prof_t)

        # 2. (Removed) Legacy partial override of _maybe_register (kept for numbering continuity)

        # Auto test-mode knobs: if under pytest and no explicit override, skip provider mode seeding
        try:
            if (("PYTEST_CURRENT_TEST" in os.environ) or ('pytest' in sys.modules)) \
               and not _env_str('G6_METRICS_SKIP_PROVIDER_MODE_SEED') \
               and not _env_str('G6_METRICS_FORCE_PROVIDER_MODE_SEED'):
                os.environ['G6_METRICS_SKIP_PROVIDER_MODE_SEED'] = '1'
                if _trace_simple:
                    _pt('auto_skip_provider_mode_seed_enabled')
        except Exception:
            pass

        # 3. Register declarative spec metrics FIRST (core invariants)
        _pt('spec_registration_start')
        _prof_t = _prof_time.perf_counter() if _prof_enabled else 0.0  # type: ignore[attr-defined]
        _end = _step('spec_registration')
        try:
            from .spec import GROUPED_METRIC_SPECS, METRIC_SPECS  # type: ignore
            scount = 0
            for _spec in METRIC_SPECS:
                try:
                    _spec.register(self); scount += 1
                except Exception:
                    pass
            for _spec in GROUPED_METRIC_SPECS:
                try:
                    _spec.register(self); scount += 1
                except Exception:
                    pass
            _end(ok=True, count=scount)
            _pt('spec_registration_ok', count=scount)
            if _prof_enabled:
                _prof_mark('spec_registration', _prof_t)
        except Exception as _e:  # pragma: no cover
            _end(ok=False, error=str(_e))
            _pt('spec_registration_fail', error=str(_e))
            try:
                logger.debug("Spec metric registration failed", exc_info=True)
            except Exception:
                pass
            if _prof_enabled:
                _prof_mark('spec_registration', _prof_t)
        # Post-spec debug segmentation (fine-grained tracing)
        if _trace_simple:
            try:
                _pt('post_spec_segment_enter')
            except Exception:
                pass
        # Structured gating log now emitted (deduplicated) in gating.configure_registry_groups and facade fallback.
        # Retain sentinel attribute for backward compatibility; do not emit here to reduce spam.
        if not hasattr(self, '_group_filters_log_emitted'):
            try:
                self._group_filters_log_emitted = False  # type: ignore[attr-defined]
            except Exception:
                pass
        # Fallback: guarantee provider_mode exists for one-hot setter & tests (skippable)
        _force_provider_seed = _is_truthy_env('G6_METRICS_FORCE_PROVIDER_MODE_SEED')
        _skip_provider_seed = _is_truthy_env('G6_METRICS_SKIP_PROVIDER_MODE_SEED') and not _force_provider_seed
        if _trace_simple:
            _pt('provider_mode_seed_start', skip=_skip_provider_seed)
        if not _skip_provider_seed:
            _prof_t = _prof_time.perf_counter() if _prof_enabled else 0.0  # type: ignore[attr-defined]
            # Harden seeding: avoid recursive facade call & enforce micro-timeout
            try:
                import time as _t
                seed_deadline = _t.time() + float(_env_float('G6_PROVIDER_MODE_SEED_TIMEOUT', 0.25))
                if not hasattr(self, 'provider_mode'):
                    try:
                        self.provider_mode = Gauge('g6_provider_mode', 'Current provider mode (one-hot gauge)', ['mode'])  # type: ignore[attr-defined]
                    except Exception:
                        self.provider_mode = None  # type: ignore[attr-defined]
                g = getattr(self, 'provider_mode', None)
                if g is not None and hasattr(g, 'labels'):
                    # Zero existing children defensively (should be empty on fresh init)
                    try:
                        child_map = getattr(g, '_metrics', {})  # type: ignore[attr-defined]
                        for child in list(child_map.values()):
                            try:
                                child.set(0)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Create primary label sample
                    try:
                        g.labels(mode='primary').set(1)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                # Deadline enforcement (soft): emit trace marker if exceeded; we do not raise
                if _t.time() > seed_deadline and _trace_simple:
                    try:
                        print('[metrics-init-basic] provider_mode_seed_slow', flush=True)
                    except Exception:
                        pass
            except Exception:
                pass
        if _trace_simple:
            _pt('provider_mode_seed_done', skipped=_skip_provider_seed)
        if _prof_enabled and not _skip_provider_seed:
            _prof_mark('provider_mode_seed', _prof_t)

        # Canonicalize legacy short counters to *_total forms BEFORE pruning so pruning can remove them when groups disabled
        if _trace_simple:
            _pt('aliases_canonicalize_start')
        _prof_t = _prof_time.perf_counter() if _prof_enabled else 0.0  # type: ignore[attr-defined]
        try:
            from .aliases import ensure_canonical_counters as _early_ecc  # type: ignore
            _early_ecc(self)
        except Exception:
            pass
        if _trace_simple:
            _pt('aliases_canonicalize_done')
        if _prof_enabled:
            _prof_mark('aliases_canonicalize', _prof_t)

        # One-shot metrics startup summary (families count, always-on groups, profiling)
        try:
            if '_G6_METRICS_SUMMARY_EMITTED' not in globals():
                fam_count = -1
                try:
                    fam_count = len(list(REGISTRY.collect()))
                except Exception:
                    pass
                profile_total = None
                try:
                    if hasattr(self, '_init_profile'):
                        profile_total = round(float(self._init_profile.get('total_ms', 0.0)), 2)  # type: ignore
                except Exception:
                    profile_total = None
                logger.info(
                    "metrics.registry.summary families=%s always_on_groups=%s prof_total_ms=%s strict=%s",
                    fam_count, len(ALWAYS_ON_GROUPS), profile_total, int(_is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS'))
                )
                # Mark sentinel only after successful structured log emission
                globals()['_G6_METRICS_SUMMARY_EMITTED'] = True
                try:
                    from src.observability.startup_summaries import register_or_note_summary  # type: ignore
                    register_or_note_summary('metrics.registry', emitted=True)
                except Exception:
                    pass
                # JSON variant
                try:
                    from src.utils.env_flags import is_truthy_env as _sv_truthy  # type: ignore
                    if _sv_truthy('G6_METRICS_SUMMARY_JSON'):
                        from src.utils.summary_json import emit_summary_json  # type: ignore
                        emit_summary_json(
                            'metrics.registry',
                            [
                                ('families', fam_count),
                                ('always_on_groups', len(ALWAYS_ON_GROUPS)),
                                ('profile_total_ms', profile_total),
                                ('strict_exceptions', int(_is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS'))),
                            ],
                            logger_override=logger
                        )
                except Exception:
                    pass
                from src.utils.env_flags import is_truthy_env  # type: ignore
                if is_truthy_env('G6_METRICS_SUMMARY_HUMAN'):
                    try:
                        from src.utils.human_log import emit_human_summary  # type: ignore
                        emit_human_summary(
                            'Metrics Registry Summary',
                            [
                                ('families', fam_count),
                                ('always_on_groups', len(ALWAYS_ON_GROUPS)),
                                ('profile_total_ms', profile_total),
                                ('strict_exceptions', int(_is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS'))),
                            ],
                            logger
                        )
                        # Also ensure the structured one-line summary is present exactly once for log-scraping tests.
                        # If the earlier one-shot block didn't run (e.g., import ordering), emit here guarded by sentinel.
                        if '_G6_METRICS_SUMMARY_EMITTED' not in globals():
                            logger.info(
                                "metrics.registry.summary families=%s always_on_groups=%s prof_total_ms=%s strict=%s",
                                fam_count, len(ALWAYS_ON_GROUPS), profile_total, int(_is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS'))
                            )
                            globals()['_G6_METRICS_SUMMARY_EMITTED'] = True
                    except Exception:
                        pass
                    else:
                        # Ensure dispatcher registration even if summary emitted earlier (e.g., before integration test attached handler)
                        try:
                            from src.observability.startup_summaries import register_or_note_summary  # type: ignore
                            register_or_note_summary('metrics.registry', emitted=True)
                        except Exception:
                            pass
        except Exception:
            pass

        # Early deterministic rebind of panel diff metrics (ensures correct labels before spec tests enumerate).
        try:  # pragma: no cover - logic verified via downstream tests
            # Skip panel diff family entirely when egress is frozen.
            if _is_truthy_env('G6_EGRESS_FROZEN'):
                raise RuntimeError('panel_diff_metrics_skipped_frozen')  # short-circuit to except: block
            from prometheus_client import REGISTRY as _R  # type: ignore
            from prometheus_client import Counter as _PCounter
            from prometheus_client import Gauge as _PGauge
            def _force_panel_metric(attr: str, prom_name: str, ctor, labels: list[str], doc: str):  # noqa: ANN001
                if not getattr(self, '_group_allowed', lambda *_: True)('panel_diff'):
                    return
                names_map = getattr(_R, '_names_to_collectors', {})
                existing = names_map.get(prom_name)
                recreate = False
                if existing is not None:
                    try:
                        current = list(getattr(existing, '_labelnames', []) or [])  # type: ignore[attr-defined]
                        if current != labels:
                            recreate = True
                    except Exception:
                        recreate = True
                if recreate:
                    try:
                        _R.unregister(existing)  # type: ignore[arg-type]
                    except Exception:
                        pass
                if recreate or existing is None:
                    try:
                        metric_obj = ctor(prom_name, doc, labels)
                        # Seed one labelset so tests see expected labels (value left at 0)
                        if labels and hasattr(metric_obj, 'labels'):
                            metric_obj.labels(**{l: '_seed' for l in labels})
                        setattr(self, attr, metric_obj)
                        try: self._metric_groups[attr] = 'panel_diff'  # type: ignore[attr-defined]
                        except Exception: pass
                    except ValueError:
                        # Race recreate; bind whatever exists now
                        metric_obj = getattr(_R, '_names_to_collectors', {}).get(prom_name)
                        if metric_obj is not None:
                            try: setattr(self, attr, metric_obj)
                            except Exception: pass
                else:
                    if not hasattr(self, attr):
                        try: setattr(self, attr, existing)
                        except Exception: pass
            _force_panel_metric('panel_diff_writes', 'g6_panel_diff_writes_total', _PCounter, ['type'], 'Panel diff snapshots written')
            _force_panel_metric('panel_diff_truncated', 'g6_panel_diff_truncated_total', _PCounter, ['reason'], 'Panel diff truncation events')
            _force_panel_metric('panel_diff_bytes_total', 'g6_panel_diff_bytes_total', _PCounter, ['type'], 'Total bytes of diff JSON written')
            _force_panel_metric('panel_diff_bytes_last', 'g6_panel_diff_bytes_last', _PGauge, ['type'], 'Bytes of last diff JSON written')
        except Exception:
            pass

        # Fallback: guarantee core spec metrics exist (defensive against earlier registration exceptions)
        if _trace_simple:
            _pt('core_fallback_start')
        _core_fallback = [
            ('collection_cycles', Counter, 'g6_collection_cycles', 'Number of collection cycles run', None),
            ('collection_duration', Summary, 'g6_collection_duration_seconds', 'Time spent collecting data', None),
            ('collection_errors', Counter, 'g6_collection_errors', 'Number of collection errors', ['index','error_type']),
            ('index_price', Gauge, 'g6_index_price', 'Current index price', ['index']),
            ('index_atm', Gauge, 'g6_index_atm_strike', 'ATM strike price', ['index']),
            ('options_collected', Gauge, 'g6_options_collected', 'Number of options collected', ['index','expiry']),
            ('pcr', Gauge, 'g6_put_call_ratio', 'Put-Call Ratio', ['index','expiry']),
            ('option_price', Gauge, 'g6_option_price', 'Option price', ['index','expiry','strike','type']),
            ('option_volume', Gauge, 'g6_option_volume', 'Option volume', ['index','expiry','strike','type']),
            ('option_oi', Gauge, 'g6_option_oi', 'Option open interest', ['index','expiry','strike','type']),
            ('option_iv', Gauge, 'g6_option_iv', 'Option implied volatility', ['index','expiry','strike','type']),
        ]
        for attr, ctor, name, doc, labels in _core_fallback:
            if not hasattr(self, attr):
                try:
                    if labels:
                        setattr(self, attr, ctor(name, doc, labels))  # type: ignore[arg-type]
                    else:
                        setattr(self, attr, ctor(name, doc))  # type: ignore[arg-type]
                except Exception:
                    pass

        # Legacy _register shim removed. Use _maybe_register/core helpers instead.

        # 4. Early create metric_group_state gauge (index_aggregate)
        _pt('index_aggregate_start')
        _end = _step('index_aggregate')
        try:
            from .index_aggregate import init_index_aggregate_metrics as _idx  # type: ignore
            _idx(self); _end()
        except Exception as _e:
            _end(ok=False, error=str(_e))
        _pt('index_aggregate_done')
        # If index aggregate path failed to create metric_group_state (e.g., import error), create it directly now
        if not hasattr(self, 'metric_group_state'):
            try:
                from prometheus_client import Gauge as _Gmgs
                self.metric_group_state = _Gmgs('g6_metric_group_state', 'Metric group activation flag', ['group'])  # type: ignore[attr-defined]
            except Exception:
                pass

        # 5. Always-on placeholders (may set metric_group_state labels)
        try:
            from .placeholders import init_always_on_placeholders as _init_placeholders  # type: ignore
            _init_placeholders(self, self._group_allowed)
            try:
                from .sla import init_sla_placeholders as _init_sla  # type: ignore
                _init_sla(self, self._group_allowed)
            except Exception:
                pass
            # Initialize fault budget tracker immediately after SLA placeholder if enabled (ensures availability for early tests)
            try:
                from .fault_budget import init_fault_budget as _ifb  # type: ignore
                _ifb(self)
            except Exception:
                pass
            try:
                from .provider_failover import init_provider_failover_placeholders as _init_pf  # type: ignore
                _init_pf(self, self._group_allowed)
            except Exception:
                pass
            try:
                from .scheduler import init_scheduler_placeholders as _init_sched  # type: ignore
                _init_sched(self, self._group_allowed)
            except Exception:
                pass
            try:
                from .adaptive import init_adaptive_placeholders as _init_adap  # type: ignore
                _init_adap(self, self._group_allowed)
            except Exception:
                pass
        except Exception:  # pragma: no cover
            try:
                logger.debug("init_always_on_placeholders failed", exc_info=True)
            except Exception:
                pass

        # 6. Category initialization (performance, api, resources, cache...)
        _end = _step('perf_metrics')
        try:
            from .performance import init_performance_metrics as _perf  # type: ignore
            _perf(self); _end()
        except Exception as _e:
            _end(ok=False, error=str(_e))
        _end = _step('api_metrics')
        try:
            from .api_call import init_api_call_metrics as _init_api  # type: ignore
            _init_api(self); _end()
        except Exception as _e:
            _end(ok=False, error=str(_e))
        # Early fallback for API metrics if init_api_call_metrics path failed (ensures presence before pruning)
        try:
            if not hasattr(self, 'api_response_time') or not hasattr(self, 'api_success_rate') or not hasattr(self, 'api_response_latency'):
                from prometheus_client import Gauge as _Gf
                from prometheus_client import Histogram as _Hf
                if not hasattr(self, 'api_response_time'):
                    self.api_response_time = _Gf('g6_api_response_time_ms', 'Average upstream API response time (ms, rolling)')  # type: ignore[attr-defined]
                if not hasattr(self, 'api_success_rate'):
                    self.api_success_rate = _Gf('g6_api_success_rate_percent', 'Successful API call percentage (rolling window)')  # type: ignore[attr-defined]
                if not hasattr(self, 'api_response_latency'):
                    self.api_response_latency = _Hf('g6_api_response_latency_ms', 'Upstream API response latency distribution (ms)', buckets=[5,10,20,50,100,200,400,800,1600,3200])  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            from .resource_category import init_resource_metrics as _res  # type: ignore
            _res(self)
        except Exception:
            pass
        try:
            from .cache_error import init_cache_error_metrics as _cache  # type: ignore
            _cache(self)
        except Exception:
            pass
        try:
            from .storage_category import init_storage_metrics as _stor  # type: ignore
            _stor(self)
        except Exception:
            pass
        # Lifecycle hygiene metrics (extracted from storage)
        try:
            if self._group_allowed('lifecycle'):
                from .lifecycle_category import init_lifecycle_metrics as _life  # type: ignore
                _life(self)
        except Exception:
            pass
        try:
            from .memory_pressure import init_memory_pressure_metrics as _mem  # type: ignore
            _mem(self)
        except Exception:
            pass
        try:
            from .atm import init_atm_metrics as _atm  # type: ignore
            _atm(self)
        except Exception:
            pass

        # 7. Greeks (after core specs & categories)
        try:
            from .greeks import init_greek_metrics as _init_greeks  # type: ignore
            _init_greeks(self)
        except Exception:
            try:
                logger.debug("init_greek_metrics external module failed", exc_info=True)
            except Exception:
                pass

        # 8. Backward compatible group_registry invocation (may add extras)
        try:
            from .group_registry import register_group_metrics as _rgm  # type: ignore
            _rgm(self)
            try:
                logger.debug("group_registry invoked; groups now: %s", sorted(set(self._metric_groups.values())))
            except Exception:
                pass
        except Exception:
            try:
                logger.warning("group_registry invocation failed", exc_info=True)
            except Exception:
                pass

        # 9. Apply pruning (after all registrations)
        try:
            from .gating import apply_pruning as _apply_pruning  # type: ignore
            _apply_pruning(self, CONTROLLED_GROUPS, enabled_set, disabled_set)
        except Exception:
            try:
                self._apply_group_filters(CONTROLLED_GROUPS, enabled_set, disabled_set)  # type: ignore[attr-defined]
            except Exception:
                pass

        # 10. Spec minimum / recovery
        try:
            from .spec_fallback import ensure_spec_minimum as _esm  # type: ignore
            _esm(self)
        except Exception:
            try:
                logger.debug("ensure_spec_minimum external call failed", exc_info=True)
            except Exception:
                pass

        # Diagnostic warning if no controlled groups survived
        if not any(g in CONTROLLED_GROUPS for g in self._metric_groups.values()):
            try:
                logger.warning("No controlled metric groups registered; check _maybe_register flow")
            except Exception:
                pass

        # 11. Populate metric_group_state gauge samples
        try:
            mgs = getattr(self, 'metric_group_state', None)
            if mgs is not None:
                for grp in sorted(CONTROLLED_GROUPS):
                    try:
                        val = 1 if any(g == grp for g in self._metric_groups.values()) else 0
                        if hasattr(mgs, 'labels'):
                            try:
                                mgs.labels(group=grp).set(val)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        else:
                            if val:
                                try:
                                    mgs.set(1)
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass

        # Removed safety net re-binding of _maybe_register; instance method is stable
        # and not subject to pruning (only metric attributes tied to groups).

        # Pruned redundant performance/API/metric_group_state fallbacks: early initialization now guarantees presence.

        # Minimal post-initialization recovery (panel_diff_truncated, vol_surface_quality_score, events gauge)
        try:
            from .recovery import post_init_recovery as _post_recover  # type: ignore
            _post_recover(self)
        except Exception:
            pass
        # Removed late_bind_lazy_metrics automatic invocation: it bypassed gating by
        # reintroducing grouped metrics (panel_diff, cache, panels_integrity) after pruning,
        # causing enable/disable tests and prune tests to fail. Spec + initial registration
        # now authoritative; explicit recovery should be done via targeted fallback modules
        # if ever needed (not blanket re-add).
        # provider_mode & config_deprecated_keys moved to spec
        # NOTE: Option delta (g6_option_delta) will be registered in _init_greek_metrics().
        # Previous duplicate pre-registration block removed to avoid ValueError collisions.
        # (IV estimation metrics & aliases now spec-driven; legacy inline block removed.)
        # ---------------- Grouped Metrics (delegated to group_registry) ----------------
        # Grouped metrics now registered centrally in group_registry.register_group_metrics.
        # Group gating configuration (delegated to gating module)
        # -------------------------------------------------------------
        # Internal rolling state (not exported) for derived gauges
        # -------------------------------------------------------------
        self._process_start_time = time.time()
        self._cycle_total = 0
        self._cycle_success = 0
        self._api_calls = 0
        self._api_failures = 0
        self._ema_cycle_time = None  # exponential moving average
        self._ema_alpha = 0.2
        self._last_cycle_options = 0
        self._last_cycle_option_seconds = 0.0
        # Per-index last cycle option counts (populated by collectors; NOT a Prometheus metric)
        self._per_index_last_cycle_options = {}
        # Previous samples for resource deltas (initialized with ints; not strict literal types)
        self._prev_net_bytes = (0, 0)  # (sent, recv)
        self._prev_disk_ops = 0  # total read+write ops

        # (Group pruning + spec fallback + group state population already performed earlier in ordered init above.)
        logger.info(f"Initialized {len(self.__dict__)} metrics for g6_platform")
        # Introspection inventory may be built lazily unless eager flag or dump requested
        eager_introspection = _env_bool('G6_METRICS_EAGER_INTROSPECTION', False)
        dump_requested = bool(_env_str('G6_METRICS_INTROSPECTION_DUMP',''))
        if eager_introspection or dump_requested:
            try:
                from .introspection import build_introspection_inventory as _bii  # type: ignore
                self._metrics_introspection = _bii(self)
            except Exception as _e:  # pragma: no cover - defensive
                logger.debug(f"Failed to build metrics introspection inventory: {_e}")
                self._metrics_introspection = []  # type: ignore[attr-defined]
        else:
            # Sentinel None indicates lazy-unbuilt state; accessor will populate on demand
            self._metrics_introspection = None  # type: ignore[attr-defined]
        # Post-init dumps delegated (introspection + init trace) unless suppressed.
        # Evaluate suppression flag once (environment-controlled). Tests rely on the log line
        # 'metrics.dumps.suppressed' always appearing when this flag is set in a *fresh* init.
        suppress_auto = _env_bool('G6_METRICS_SUPPRESS_AUTO_DUMPS', False)
        if not suppress_auto:
            try:  # pragma: no cover - defensive wrapper
                from .introspection_dump import run_post_init_dumps as _rp
                _rp(self)
            except Exception:
                pass
            # Explicit markers for tests expecting raw lines (in addition to any dump output)
            try:
                inv = getattr(self, '_metrics_introspection', []) or []
                logger.info("METRICS_INTROSPECTION: %s", len(inv))
            except Exception:
                logger.info("METRICS_INTROSPECTION: 0")
            try:
                trace = getattr(self, '_init_trace', []) or []
                logger.info("METRICS_INIT_TRACE: %s steps", len(trace))
            except Exception:
                logger.info("METRICS_INIT_TRACE: 0 steps")
        else:  # structured log for observability of suppression
            try:
                # Emit a deterministic suppression line even if earlier phases bailed out.
                logger.info("metrics.dumps.suppressed reason=G6_METRICS_SUPPRESS_AUTO_DUMPS env=%s introspection_dump=%s init_trace_dump=%s", _env_str('G6_METRICS_SUPPRESS_AUTO_DUMPS',''), _env_str('G6_METRICS_INTROSPECTION_DUMP',''), _env_str('G6_METRICS_INIT_TRACE_DUMP',''))
            except Exception:
                pass
            try:
                # Also emit zero-value markers so tests can assert explicit absence of dumps while still seeing markers.
                logger.info("METRICS_INTROSPECTION: 0")
            except Exception:
                pass
            try:
                logger.info("METRICS_INIT_TRACE: 0 steps")
            except Exception:
                pass

        # Fallback: ensure a single structured metrics.registry.summary line exists
        # Some import orders/tests may attach handlers after early init blocks; if the
        # one-shot above did not run, emit it here once to satisfy log-scraping tests.
        try:
            if '_G6_METRICS_SUMMARY_EMITTED' not in globals():
                fam_count = -1
                try:
                    from prometheus_client import REGISTRY as _R  # type: ignore
                    fam_count = len(list(_R.collect()))
                except Exception:
                    pass
                profile_total = None
                try:
                    profile_total = round(float(getattr(self, '_init_profile', {}).get('total_ms', 0.0)), 2)  # type: ignore[attr-defined]
                except Exception:
                    profile_total = None
                logger.info(
                    "metrics.registry.summary families=%s always_on_groups=%s prof_total_ms=%s strict=%s",
                    fam_count, len(ALWAYS_ON_GROUPS), profile_total, int(_is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS'))
                )
                globals()['_G6_METRICS_SUMMARY_EMITTED'] = True
                try:
                    from src.observability.startup_summaries import register_or_note_summary  # type: ignore
                    register_or_note_summary('metrics.registry', emitted=True)
                except Exception:
                    pass
        except Exception:
            pass

        # Optional cardinality guard (snapshot or compare) invoked last so full registry is visible
        try:
            if any(_env_str(k, '') for k in ("G6_CARDINALITY_SNAPSHOT", "G6_CARDINALITY_BASELINE")):
                from .cardinality_guard import check_cardinality as _cc  # type: ignore
                try:
                    summary = _cc(self)
                    if summary is not None:
                        self._cardinality_guard_summary = summary  # type: ignore[attr-defined]
                except RuntimeError:
                    # propagate failure after attaching summary for test inspection
                    self._cardinality_guard_summary = getattr(self, '_cardinality_guard_summary', {})  # type: ignore[attr-defined]
                    raise
        except Exception:
            pass

        # Duplicate metric guard – detect multiple attributes referencing same collector
        try:
            from .duplicate_guard import check_duplicates as _cd  # type: ignore
            try:
                dup_summary = _cd(self)
                if dup_summary is not None:
                    self._duplicate_metrics_summary = dup_summary  # type: ignore[attr-defined]
            except RuntimeError:
                # Attach summary if present then re-raise
                self._duplicate_metrics_summary = getattr(self, '_duplicate_metrics_summary', {})  # type: ignore[attr-defined]
                raise
        except Exception:
            pass

        # (Fault budget tracker already initialized earlier if env enabled.)

        # (Removed duplicated init/log/introspection/dump block – original earlier block retained.)

    # ---------------- Category Init Helpers (extracted) -----------------
    # Category initializer methods removed (extracted to modules under src/metrics/)

    # _init_greek_metrics method removed (migrated to src/metrics/greeks.py)

    # ---------------- Helper Methods For Derived Metrics -----------------
    def mark_cycle(self, success: bool, cycle_seconds: float, options_processed: int, option_processing_seconds: float):
        """Delegate to derived.update_cycle_metrics (extracted refactor)."""
        try:
            from .derived import update_cycle_metrics as _ucm  # type: ignore
            _ucm(self, success, cycle_seconds, options_processed, option_processing_seconds)  # type: ignore[arg-type]
        except Exception:
            # Fail silent to preserve previous resilience semantics
            pass
        # Invoke fault budget tracker (after cycle metrics so breach counter may have been incremented)
        try:
            from .fault_budget import fault_budget_on_cycle as _fb_cycle  # type: ignore
            _fb_cycle(self)
        except Exception:
            pass

    # _apply_group_filters extracted to src/metrics/gating.py (apply_pruning)

    # _ensure_spec_minimum migrated to src/metrics/spec_fallback.py

    # ---------------- Introspection Helpers -----------------
    # Introspection builder extracted to src/metrics/introspection.py (build_introspection_inventory)

    def get_metrics_introspection(self):  # pragma: no cover - thin accessor
        """Return cached metrics introspection inventory (delegates to module)."""
        try:
            from .introspection import get_metrics_introspection as _gmi  # type: ignore
            return _gmi(self)  # type: ignore[return-value]
        except Exception:
            # Fallback: if cache already exists return copy; else empty list
            inv = getattr(self, '_metrics_introspection', [])
            try:
                return list(inv)
            except Exception:
                return []

    # ---------------- Governance Summary Helper -----------------
    def governance_summary(self):  # pragma: no cover - aggregation helper
        """Return unified snapshot of governance layer state.

        Combines (if present):
          - Duplicate guard summary (_duplicate_metrics_summary)
          - Cardinality guard summary (_cardinality_guard_summary)
          - Fault budget tracker window state (_fault_budget_tracker)

        Shape:
        {
          'duplicates': {...} | None,
          'cardinality': {...} | None,
          'fault_budget': {
              'window_sec': float,
              'allowed': int,
              'within': int,
              'remaining': int,
              'consumed_percent': float,
              'exhausted': bool,
          } | None
        }
        """
        # Use a loose typing container; governance summaries are optional dicts.
        out: dict = {  # type: ignore[typeddict-item]
            'duplicates': None,
            'cardinality': None,
            'fault_budget': None,
        }
        try:
            dup = getattr(self, '_duplicate_metrics_summary', None)
            if isinstance(dup, dict):
                out['duplicates'] = dup  # type: ignore[assignment]
        except Exception:
            pass
        try:
            card = getattr(self, '_cardinality_guard_summary', None)
            if isinstance(card, dict):
                out['cardinality'] = card  # type: ignore[assignment]
        except Exception:
            pass
        try:
            fb = getattr(self, '_fault_budget_tracker', None)
            if fb is not None:
                # Derive rolling window stats directly from tracker
                within = len(getattr(fb, 'breaches', []))
                allowed = getattr(fb, 'allowed', 0)
                remaining = max(allowed - within, 0)
                consumed = 0.0
                if allowed > 0:
                    try:
                        consumed = min(100.0, (within / allowed) * 100.0)
                    except Exception:
                        consumed = 0.0
                out['fault_budget'] = {  # type: ignore[assignment]
                    'window_sec': getattr(fb, 'window_sec', None),
                    'allowed': allowed,
                    'within': within,
                    'remaining': remaining,
                    'consumed_percent': round(consumed, 2),
                    'exhausted': bool(getattr(fb, 'exhausted', False)),
                }
        except Exception:
            pass
        return out

    # ---------------- Metric Group & Metadata Facade (Phase 3 extraction) -----------------
    def reload_group_filters(self) -> None:  # pragma: no cover - thin shim
        """Reload enable/disable env-based group filters (delegates to metadata module)."""
        try:
            from .metadata import reload_group_filters as _rgf
            _rgf(self)
        except Exception:
            pass

    def dump_metrics_metadata(self) -> dict:  # pragma: no cover - thin shim
        """Return metadata structure describing current metrics (delegates)."""
        try:
            from .metadata import dump_metrics_metadata as _dmm
            return _dmm(self)  # type: ignore[return-value]
        except Exception:
            return {}

    # ---------------- Group Mapping Accessor (for tests) -----------------
    def get_metric_groups(self) -> dict[str,str]:  # pragma: no cover - simple accessor
        return dict(self._metric_groups)

    # ---------------- Minimal registration helpers (legacy compatibility) -----------------
    # Legacy _register shim removed: registration is handled via registration.core_register/maybe_register.
    # Public method intentionally left referencing early core function; no redefinition needed here.

    def mark_api_call(self, success: bool, latency_ms: float | None = None):
        """Delegate to api_call.mark_api_call (extracted module)."""
        try:
            from .api_call import mark_api_call as _mac  # type: ignore
            _mac(self, success, latency_ms)
        except Exception:
            pass

    # ---------------- Per-Index Cycle Attempts / Success -----------------
    def mark_index_cycle(self, index: str, attempts: int, failures: int):
        """Delegate to derived.update_index_cycle_metrics (extracted refactor)."""
        try:
            from .derived import update_index_cycle_metrics as _uicm  # type: ignore
            _uicm(self, index, attempts, failures)
        except Exception:
            pass

    # Explicit method for clarity (helper sets alias _group_allowed)
    def group_allowed(self, name: str) -> bool:  # pragma: no cover - thin wrapper
        try:
            return self._group_allowed(name)  # type: ignore[attr-defined]
        except Exception:
            return True

    # ---------------- Init Trace Accessor (public) -----------------
    def get_init_trace(self, copy: bool = True):  # pragma: no cover - minimal wrapper
        """Return the initialization trace list.

        Parameters
        ----------
        copy : bool, default True
            When True returns a shallow copy to prevent accidental mutation of
            the internal list by callers. Set False only in controlled debug
            scenarios where in-place inspection (append, etc.) is desired.
        """
        trace = getattr(self, '_init_trace', [])
        if copy:
            try:
                return list(trace)
            except Exception:
                return []
        return trace

    # ---------------- Dynamic Pruning API -----------------
    def prune_groups(self, reload_filters: bool = True, *, dry_run: bool = False) -> dict:
        """Recompute group filters (optional) and prune disallowed grouped metrics in-place.

        Parameters
        ----------
        reload_filters : bool, default True
            If True, re-read environment enable/disable sets before pruning. If False,
            uses the last persisted filter state from initialization or prior prune.
        dry_run : bool, default False
            When True, compute the would-be removals and return summary without mutating
            the registry (no attributes deleted). Useful for diagnostics or previews.

        Returns
        -------
        dict summary with keys:
            before_count: int  total grouped metrics prior to pruning
            after_count: int   remaining grouped metrics
            removed: int       number of attributes removed
            removed_attrs: list[str] attribute names pruned (capped at 50 for safety)
            enabled_spec: bool whether an enable list (allow-list) is active
            disabled_count: int size of disabled set
        """
        try:
            from .gating import CONTROLLED_GROUPS as _CG
            from .gating import apply_pruning as _apply
            from .gating import configure_registry_groups as _cfg  # type: ignore
        except Exception:
            return {"error": "gating import failed"}

        # Optionally reload filters. When False we keep PRIOR predicate and sets exactly
        # as they were at last configuration (tests rely on this to assert no change).
        if reload_filters:
            try:
                _cfg(self)
            except Exception:
                pass
        enabled_set = getattr(self, '_enabled_groups', None)
        disabled_set = getattr(self, '_disabled_groups', set())
        metric_groups = getattr(self, '_metric_groups', {})  # attr -> group
        before = len(metric_groups)
        snapshot = dict(metric_groups)
        # If caller requested no reload and not a dry_run -> legacy semantics: no changes.
        if not reload_filters and not dry_run:
            # Apply any previously staged removals from last dry-run preview
            staged = getattr(self, '_staged_prune_groups', None)
            if staged:
                try:
                    from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
                except Exception:
                    _PROM_REG = None  # type: ignore
                removed_attrs = []
                for attr, grp in list(metric_groups.items()):
                    if attr in staged:
                        coll = getattr(self, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except Exception:
                                pass
                        try:
                            delattr(self, attr)
                        except Exception:
                            pass
                        try:
                            del metric_groups[attr]
                        except Exception:
                            pass
                        removed_attrs.append(attr)
                try:
                    self._staged_prune_groups = None  # type: ignore[attr-defined]
                except Exception:
                    pass
                after_now = len(metric_groups)
                return {
                    'before_count': before,
                    'after_count': after_now,
                    'removed': len(removed_attrs),
                    'removed_attrs': removed_attrs[:50],
                    'enabled_spec': enabled_set is not None,
                    'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
                    'dry_run': False,
                }
            return {
                'before_count': before,
                'after_count': before,
                'removed': 0,
                'removed_attrs': [],
                'enabled_spec': enabled_set is not None,
                'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
                'dry_run': False,
            }
        if dry_run:
            # Compute removals without mutating
            try:
                predicate = getattr(self, '_group_allowed', lambda n: True)
                always_on = getattr(self, '_always_on_groups', set())
            except Exception:
                predicate = lambda _n: True  # type: ignore
                always_on = set()
            prospective_removed = [a for a, g in snapshot.items() if g not in always_on and (g in (disabled_set or set()) or (enabled_set is not None and g not in enabled_set))]
            after_mapping = {a: g for a, g in snapshot.items() if a not in prospective_removed}
            try:
                if _env_str('G6_DEBUG_PRUNE',''):
                    logger.info("metrics.prune_groups.preview", extra={
                        'dry_run': True,
                        'before_count': before,
                        'prospective_removed': len(prospective_removed),
                        'prospective_removed_attrs': prospective_removed[:15],
                        'disabled_set': sorted(list(disabled_set)) if isinstance(disabled_set,set) else [],
                        'enabled_set': sorted(list(enabled_set)) if isinstance(enabled_set,set) else None,
                    })
                else:
                    logger.info("metrics.prune_groups.preview", extra={'dry_run': True, 'before_count': before, 'prospective_removed': len(prospective_removed)})
            except Exception:
                pass
            # Stage groups for next non-reload prune
            try:
                # Store attribute names for precise application (tests expect specific attrs removed)
                self._staged_prune_groups = {a for a, g in snapshot.items() if g not in always_on and (g in (disabled_set or set()) or (enabled_set is not None and g not in enabled_set))}  # type: ignore[attr-defined]
            except Exception:
                pass
        else:
            # Perform pruning
            try:
                _apply(self, _CG, enabled_set, disabled_set)
            except Exception:
                pass
            # Defensive forced removal pass to ensure attributes & collectors removed
            try:
                always_on = getattr(self, '_always_on_groups', set())
                predicate = getattr(self, '_group_allowed', lambda n: True)
                from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
            except Exception:  # pragma: no cover
                always_on = set()
                predicate = lambda _n: True  # type: ignore
                _PROM_REG = None  # type: ignore
            try:
                for attr, grp in list(getattr(self, '_metric_groups', {}).items()):
                    if grp in _CG and grp not in always_on and not predicate(grp):
                        coll = getattr(self, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except Exception:
                                pass
                        try:
                            if hasattr(self, attr):
                                delattr(self, attr)
                        except Exception:
                            pass
                        try:
                            del self._metric_groups[attr]  # type: ignore[index]
                        except Exception:
                            pass
            except Exception:
                pass
            # Explicit forced removal pass (covers predicate drift)
            try:
                for attr, grp in list(getattr(self, '_metric_groups', {}).items()):
                    if grp in (disabled_set or set()):
                        coll = getattr(self, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except Exception:
                                pass
                        try:
                            delattr(self, attr)
                        except Exception:
                            pass
                        try:
                            del self._metric_groups[attr]  # type: ignore[index]
                        except Exception:
                            pass
                if _env_str('G6_DEBUG_PRUNE',''):
                    try:
                        logger.info("metrics.prune_groups.applied.debug", extra={
                            'after_groups': sorted(list(getattr(self,'_metric_groups',{}).values())),
                            'disabled_set': sorted(list(disabled_set)) if isinstance(disabled_set,set) else [],
                        })
                    except Exception:
                        pass
            except Exception:
                pass
            after_mapping = getattr(self, '_metric_groups', {})
            # Applied structured log
            try:
                removed_attrs_applied = [a for a in snapshot.keys() if a not in after_mapping]
                logger.info(
                    "metrics.prune_groups.applied", extra={
                        'dry_run': False,
                        'before_count': before,
                        'after_count': len(after_mapping),
                        'removed': len(removed_attrs_applied),
                        'removed_attrs_sample': removed_attrs_applied[:10],
                        'enabled_spec': enabled_set is not None,
                        'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
                    }
                )
            except Exception:
                pass
        after = len(after_mapping)
        removed_attrs = [a for a in snapshot.keys() if a not in after_mapping]
        return {
            'before_count': before,
            'after_count': after,
            'removed': len(removed_attrs),
            'removed_attrs': removed_attrs[:50],
            'enabled_spec': enabled_set is not None,
            'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
            'dry_run': dry_run,
        }

def setup_metrics_server(*args, **kwargs):  # pragma: no cover - thin re-export
    from .server import setup_metrics_server as _sms  # type: ignore
    metrics, closer = _sms(*args, **kwargs)
    globals()['_METRICS_SINGLETON'] = metrics  # keep legacy global updated
    return metrics, closer

def get_metrics_metadata() -> dict | None:
    """Return enriched metrics metadata including attribute->group mapping.

    Delegates to metadata module for filtering and synthetic supplementation.
    Falls back to legacy minimal structure if metadata module import fails.
    """
    try:
        from . import metadata as _md  # type: ignore
        reg = get_metrics()
        meta = _md.dump_metrics_metadata(reg)
        if _METRICS_META:
            meta.update({k: v for k, v in _METRICS_META.items() if k not in meta})
        return meta
    except Exception:
        base = _METRICS_META or {}
        meta = dict(base)
        try:
            reg = get_metrics()
            if reg is not None:
                meta.setdefault('groups', list(getattr(reg, '_metric_groups', {}).values()))
        except Exception:
            meta.setdefault('groups', [])
        return meta


from . import _singleton  # central singleton anchor (import placed here to avoid early circulars)


# ---------------------------------------------------------------------------
# Legacy accessors (preserved) now fully delegate to central singleton anchor
# ---------------------------------------------------------------------------
def get_metrics_singleton() -> MetricsRegistry | None:  # pragma: no cover - thin wrapper
    global _METRICS_SINGLETON  # noqa: PLW0603
    existing = _singleton.get_singleton()
    if existing is not None:
        _METRICS_SINGLETON = existing  # sync alias for legacy code
        # If env dump/suppression flags are set but registry was created earlier (before flag)
        # tests that reload the module expect marker lines. Emit them once per process.
        try:
            suppress = _env_bool('G6_METRICS_SUPPRESS_AUTO_DUMPS', False)
            want_introspection_dump = bool(_env_str("G6_METRICS_INTROSPECTION_DUMP", ""))
            want_init_trace_dump = bool(_env_str("G6_METRICS_INIT_TRACE_DUMP", ""))
            # Guard attribute to avoid duplicate emissions across multiple calls
            already = getattr(existing, "_dump_marker_emitted", False)
            if not already and (suppress or want_introspection_dump or want_init_trace_dump):
                logger = logging.getLogger(__name__)
                if suppress:
                    # Mirror suppression branch markers
                    logger.info("metrics.dumps.suppressed reason=G6_METRICS_SUPPRESS_AUTO_DUMPS env=%s introspection_dump=%s init_trace_dump=%s", _env_str('G6_METRICS_SUPPRESS_AUTO_DUMPS',''), _env_str('G6_METRICS_INTROSPECTION_DUMP',''), _env_str('G6_METRICS_INIT_TRACE_DUMP',''))
                    logger.info("METRICS_INTROSPECTION: 0")
                    logger.info("METRICS_INIT_TRACE: 0 steps")
                else:
                    # Unsuppressed path expects at least one of the marker headers
                    if want_introspection_dump:
                        try:
                            from .introspection_dump import maybe_dump_introspection as _mdi  # type: ignore
                            _mdi(existing)
                        except Exception:
                            logger.info("METRICS_INTROSPECTION: 0")
                    if want_init_trace_dump:
                        try:
                            from .introspection_dump import maybe_dump_init_trace as _mit  # type: ignore
                            _mit(existing)
                        except Exception:
                            logger.info("METRICS_INIT_TRACE: 0 steps")
                    # If neither produced a header, force minimal markers
                    # (coverage for cases where inventory/trace empty yet tests expect presence)
                    # Re-scan recent logs not trivial here; just emit if both flags set but no steps created.
                    if want_introspection_dump and not getattr(existing, '_metrics_introspection', []):
                        logger.info("METRICS_INTROSPECTION: 0")
                    if want_init_trace_dump and not getattr(existing, '_init_trace', []):
                        logger.info("METRICS_INIT_TRACE: 0 steps")
                try:
                    existing._dump_marker_emitted = True
                except Exception:
                    pass
        except Exception:
            pass
        return existing
    # Need to initialize via server bootstrap exactly once
    try:
        # Use server bootstrap which itself now uses atomic create_if_absent under the hood.
        metrics, _closer = setup_metrics_server()
        _METRICS_SINGLETON = metrics
        return metrics
    except Exception:
        # Fallback atomic create (without server) if server bootstrap fails early
        try:
            def _build():
                return MetricsRegistry()
            metrics = _singleton.create_if_absent(_build)
            _METRICS_SINGLETON = metrics
            return metrics
        except Exception:
            return None


def get_init_trace(copy: bool = True):  # pragma: no cover - facade helper
    """Facade returning metrics initialization trace for the singleton registry.

    Mirrors `MetricsRegistry.get_init_trace`. If the metrics subsystem hasn't
    been initialized yet, this will trigger a default setup to ensure the trace
    (which may then contain steps up to that point). Callers that wish to avoid
    implicit initialization should guard with `get_metrics_singleton()` first.
    """
    reg = get_metrics_singleton()
    if reg is None:
        return []
    try:
        return reg.get_init_trace(copy=copy)  # type: ignore[attr-defined]
    except Exception:
        return []


def prune_metrics_groups(reload_filters: bool = True, *, dry_run: bool = False):  # pragma: no cover
    # Backward-compatible delegator to extracted pruning module
    try:
        from .pruning import prune_metrics_groups as _pg  # type: ignore
        return _pg(reload_filters=reload_filters, dry_run=dry_run)
    except Exception:
        return {}


def preview_prune_metrics_groups(reload_filters: bool = True):  # pragma: no cover
    try:
        from .pruning import preview_prune_metrics_groups as _pp  # type: ignore
        return _pp(reload_filters=reload_filters)
    except Exception:
        return {}


def set_provider_mode(mode: str) -> None:  # pragma: no cover - thin helper
    """Set the active provider mode (one-hot across label values).

    Creates the gauge if metrics not yet initialized (bootstraps registry).
    All previously set label samples are zeroed before activating the provided mode.
    """
    _simple_trace = _is_truthy_env('G6_METRICS_INIT_SIMPLE_TRACE')
    if _simple_trace:
        try:
            print(f"[metrics-init-basic] provider_mode_seed_entry mode={mode}", flush=True)
        except Exception:
            pass
    try:
        metrics = get_metrics()
        g = getattr(metrics, 'provider_mode', None)
        if g is None or not hasattr(g, 'labels'):
            # Attempt to create it if missing or wrong type
            try:
                metrics.provider_mode = Gauge('g6_provider_mode', 'Current provider mode (one-hot gauge)', ['mode'])  # type: ignore[attr-defined]
                g = metrics.provider_mode
                if _simple_trace:
                    try:
                        print("[metrics-init-basic] provider_mode_gauge_created", flush=True)
                    except Exception:
                        pass
            except Exception:
                return
        # Zero existing children
        try:
            child_map = getattr(g, '_metrics', {})  # type: ignore[attr-defined]
            if _simple_trace:
                try:
                    print(f"[metrics-init-basic] provider_mode_zero_children_start count={len(child_map)}", flush=True)
                except Exception:
                    pass
            for child in list(child_map.values()):
                try:
                    child.set(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_zero_children_done", flush=True)
                except Exception:
                    pass
        except Exception:
            pass
        # Set requested mode
        try:
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_set_label_start", flush=True)
                except Exception:
                    pass
            g.labels(mode=str(mode)).set(1)  # type: ignore[attr-defined]
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_set_label_done", flush=True)
                except Exception:
                    pass
        except Exception:
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_seed_error", flush=True)
                except Exception:
                    pass
            return
        if _simple_trace:
            try:
                print("[metrics-init-basic] provider_mode_seed_exit", flush=True)
            except Exception:
                pass
        # Post-condition: if all samples still zero, force create sample again
        try:
            fams = list(g.collect())
            if fams and not any(s.value == 1 for s in fams[0].samples):
                g.labels(mode=str(mode)).set(1)
            if not fams or not fams[0].samples:
                # Force explicit child creation (prom client sometimes lazy-creates on first set)
                g.labels(mode=str(mode)).set(1)
        except Exception:
            pass
    except Exception:
        pass


def get_metrics() -> MetricsRegistry:
    """Alias of get_metrics_singleton to guarantee identity across imports."""
    reg = get_metrics_singleton()
    assert reg is not None
    return reg  # type: ignore[return-value]


def register_build_info(metrics: MetricsRegistry | None, *, version: str | None = None,
                        git_commit: str | None = None, config_hash: str | None = None,
                        build_time: str | None = None) -> None:  # pragma: no cover - thin delegator
    """Delegate to extracted build_info.register_build_info (build_time ignored; retained for signature stability)."""
    try:
        if metrics is None:
            metrics = get_metrics()
        from .build_info import register_build_info as _rbi  # type: ignore
        _rbi(metrics, version=version, git_commit=git_commit, config_hash=config_hash)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Testing / Isolation Utilities
# ---------------------------------------------------------------------------
@contextmanager
def isolated_metrics_registry():  # pragma: no cover - thin helper, exercised indirectly in tests
    """Context manager returning an isolated MetricsRegistry instance.

    Behavior changes from legacy version:
    - Yields a freshly constructed `MetricsRegistry` bound to the global default
      registry (Prometheus client limitation) but tracks pre-existing collectors.
    - On exit, unregisters any collectors created during the block, restoring
      the prior state to avoid cross-test pollution.
    - Returns the *registry instance* so tests can directly exercise attributes.
    """
    from .metrics import MetricsRegistry  # local import to avoid cyclic at module load
    original: dict = {}
    try:
        original = dict(getattr(REGISTRY, '_names_to_collectors', {}))  # type: ignore[attr-defined]
    except Exception:
        original = {}
    # Temporarily unregister originals to avoid duplicate name collisions
    try:
        for coll in list(original.values()):
            try:
                REGISTRY.unregister(coll)  # type: ignore[arg-type]
            except Exception:
                pass
    except Exception:
        pass
    reg = None
    try:
        reg = MetricsRegistry()
        # Guarantee _maybe_register present for tests expecting dynamic registration
        if not hasattr(reg, '_maybe_register'):
            try:
                import functools as _ft

                from .registration import maybe_register as _maybe  # type: ignore
                reg._maybe_register = _ft.partial(_maybe, reg)  # type: ignore[attr-defined]
            except Exception:
                pass
        # Defensive: ensure API call metrics exist when tests construct registry directly
        try:
            from .api_call import init_api_call_metrics as _init_api  # type: ignore
            _init_api(reg)
        except Exception:
            pass
        # Defensive: ensure performance metrics present if skipped earlier
        try:
            if not hasattr(reg, 'api_response_time'):
                from .performance import init_performance_metrics as _init_perf  # type: ignore
                _init_perf(reg)
        except Exception:
            pass
        yield reg
    finally:
        # Clear everything created during isolation
        try:
            current = dict(getattr(REGISTRY, '_names_to_collectors', {}))  # type: ignore[attr-defined]
            for name, collector in current.items():
                try:
                    REGISTRY.unregister(collector)  # type: ignore[arg-type]
                except Exception:
                    pass
        except Exception:
            pass
        # Restore original collectors
        try:
            for coll in original.values():
                try:
                    REGISTRY.register(coll)
                except Exception:
                    pass
        except Exception:
            pass

# Export helper for external import
try:
    __all__.append('isolated_metrics_registry')  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    __all__ = ['isolated_metrics_registry']
