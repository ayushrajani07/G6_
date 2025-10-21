#!/usr/bin/env python3
"""Collector settings & feature flag bootstrap (Phase 0).

Introduces a single-pass environment hydration object to replace scattered
os.environ lookups inside the collector / expiry processing pipeline.

Behavior: PURE DATA CONTAINER (no side-effects) except optional one-time
structured log when G6_COLLECTOR_SETTINGS_LOG=1 (off by default).

This file is safe to import early; heavy modules should not be imported here.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field

__all__ = ["CollectorSettings", "get_collector_settings", "PIPELINE_V2_ENABLED"]

@dataclass(slots=True)
class CollectorSettings:
    # Threshold / filtering knobs
    min_volume: int = 0
    min_oi: int = 0
    volume_percentile: float = 0.0

    # Feature toggles / behavior flags
    salvage_enabled: bool = False  # legacy foreign expiry salvage (broad)
    foreign_expiry_salvage: bool = False  # explicit salvage flag (preferred going forward)
    domain_models: bool = False
    trace_enabled: bool = False  # generic trace (legacy alias of trace_collector)
    trace_collector: bool = False  # explicit collector trace flag
    retry_on_empty: bool = True
    recovery_strategy_legacy: bool = False  # retain toggling of legacy RecoveryStrategy path

    # Loop / heartbeat & outage classification
    loop_heartbeat_interval: float = 0.0
    provider_outage_threshold: int = 3
    provider_outage_log_every: int = 5

    # Quiet / logging gating
    quiet_mode: bool = False
    quiet_allow_trace: bool = False

    # Logging / behavior overrides
    log_level_overrides: dict[str, str] = field(default_factory=dict)

    # Feature flag for pipeline shadow / activation (Phase 0 gate)
    pipeline_v2_flag: bool = False

    # Raw env snapshot (debug / diagnostics)
    _env_snapshot: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> CollectorSettings:
        e = env if env is not None else os.environ
        def _bool(name: str, default: bool = False) -> bool:
            return (e.get(name, str(int(default))).lower() in ("1","true","yes","on"))
        def _int(name: str, default: int = 0) -> int:
            try:
                return int(e.get(name, default))
            except Exception:
                return default
        def _float(name: str, default: float = 0.0) -> float:
            try:
                return float(e.get(name, default))
            except Exception:
                return default
        overrides_raw = e.get("G6_COLLECTOR_LOG_LEVEL_OVERRIDES","")
        overrides: dict[str,str] = {}
        if overrides_raw:
            # format: key=LEVEL,key2=LEVEL
            for part in overrides_raw.split(','):
                if '=' in part:
                    k,v = part.split('=',1)
                    k = k.strip(); v = v.strip().upper()
                    if k and v:
                        overrides[k]=v
        settings = cls(
            min_volume=_int('G6_FILTER_MIN_VOLUME', 0),
            min_oi=_int('G6_FILTER_MIN_OI', 0),
            volume_percentile=_float('G6_FILTER_VOLUME_PERCENTILE', 0.0),
            salvage_enabled=_bool('G6_FOREIGN_EXPIRY_SALVAGE', False),
            foreign_expiry_salvage=_bool('G6_FOREIGN_EXPIRY_SALVAGE', False),  # duplicate mapping for explicit name
            domain_models=_bool('G6_DOMAIN_MODELS', False),
            trace_enabled=_bool('G6_TRACE_COLLECTOR', False),
            trace_collector=_bool('G6_TRACE_COLLECTOR', False),
            retry_on_empty=_bool('G6_COLLECTOR_RETRY_ON_EMPTY', True),
            recovery_strategy_legacy=_bool('G6_RECOVERY_STRATEGY_LEGACY', False),
            loop_heartbeat_interval=_float('G6_LOOP_HEARTBEAT_INTERVAL', 0.0),
            provider_outage_threshold=_int('G6_PROVIDER_OUTAGE_THRESHOLD', 3),
            provider_outage_log_every=_int('G6_PROVIDER_OUTAGE_LOG_EVERY', 5),
            quiet_mode=_bool('G6_QUIET_MODE', False),
            quiet_allow_trace=_bool('G6_QUIET_ALLOW_TRACE', False),
            log_level_overrides=overrides,
            pipeline_v2_flag=_bool('G6_COLLECTOR_PIPELINE_V2', False),
            _env_snapshot={k:v for k,v in e.items() if k.startswith('G6_')}
        )
        if _bool('G6_COLLECTOR_SETTINGS_LOG', False):
            logging.getLogger(__name__).info(
                "collector.settings.init min_volume=%s min_oi=%s salvage=%s percentile=%.2f pipeline_v2=%s heartbeat=%.2f outage_thr=%s",
                settings.min_volume, settings.min_oi, settings.salvage_enabled,
                settings.volume_percentile, settings.pipeline_v2_flag, settings.loop_heartbeat_interval,
                settings.provider_outage_threshold
            )
        return settings

# Lazy singleton (thread-safe) to avoid repeated parsing
_settings_lock = threading.Lock()
_settings_singleton: CollectorSettings | None = None

def get_collector_settings(force_reload: bool = False) -> CollectorSettings:
    global _settings_singleton
    if _settings_singleton is not None and not force_reload:
        return _settings_singleton
    with _settings_lock:
        if _settings_singleton is None or force_reload:
            _settings_singleton = CollectorSettings.from_env()
            # One-shot structured summary emission for ops visibility
            try:
                if '_G6_SETTINGS_SUMMARY_EMITTED' not in globals():
                    globals()['_G6_SETTINGS_SUMMARY_EMITTED'] = True
                    s = _settings_singleton
                    log = logging.getLogger(__name__)
                    log.info(
                        "collector.settings.summary min_volume=%s min_oi=%s vol_pct=%.2f salvage=%s foreign_salvage=%s recovery_legacy=%s domain_models=%s trace=%s quiet=%s hb_interval=%.2f outage_thr=%s outage_log_every=%s retry_on_empty=%s overrides=%d pipeline_v2=%s",
                        s.min_volume, s.min_oi, s.volume_percentile,
                        int(bool(s.salvage_enabled)), int(bool(s.foreign_expiry_salvage)),
                        int(bool(s.recovery_strategy_legacy)),
                        int(bool(s.domain_models)), int(bool(s.trace_collector or s.trace_enabled)),
                        int(bool(s.quiet_mode)), s.loop_heartbeat_interval, s.provider_outage_threshold,
                        s.provider_outage_log_every, int(bool(s.retry_on_empty)), len(s.log_level_overrides),
                        int(bool(s.pipeline_v2_flag))
                    )
                    # Register (or note) with dispatcher state (best effort)
                    try:
                        from src.observability.startup_summaries import register_or_note_summary  # type: ignore
                        register_or_note_summary('collector.settings', emitted=True)
                    except Exception:
                        pass
                    # Optional JSON summary
                    try:
                        from src.utils.env_flags import is_truthy_env  # type: ignore
                        if is_truthy_env('G6_SETTINGS_SUMMARY_JSON'):
                            from src.utils.summary_json import emit_summary_json  # type: ignore
                            emit_summary_json(
                                'collector.settings',
                                [
                                    ('min_volume', s.min_volume),
                                    ('min_oi', s.min_oi),
                                    ('volume_percentile', s.volume_percentile),
                                    ('salvage_enabled', int(bool(s.salvage_enabled))),
                                    ('foreign_expiry_salvage', int(bool(s.foreign_expiry_salvage))),
                                    ('recovery_strategy_legacy', int(bool(s.recovery_strategy_legacy))),
                                    ('domain_models', int(bool(s.domain_models))),
                                    ('trace_collector', int(bool(s.trace_collector or s.trace_enabled))),
                                    ('quiet_mode', int(bool(s.quiet_mode))),
                                    ('quiet_allow_trace', int(bool(s.quiet_allow_trace))),
                                    ('heartbeat_interval', s.loop_heartbeat_interval),
                                    ('outage_threshold', s.provider_outage_threshold),
                                    ('outage_log_every', s.provider_outage_log_every),
                                    ('retry_on_empty', int(bool(s.retry_on_empty))),
                                    ('overrides_count', len(s.log_level_overrides)),
                                    ('pipeline_v2_flag', int(bool(s.pipeline_v2_flag))),
                                ],
                                logger_override=log
                            )
                    except Exception:
                        pass
                    # Optional human-readable multi-line block
                    try:
                        from src.utils.env_flags import is_truthy_env  # type: ignore
                        if is_truthy_env('G6_SETTINGS_SUMMARY_HUMAN'):
                            from src.utils.human_log import emit_human_summary  # type: ignore
                            emit_human_summary(
                                'Settings Summary',
                                [
                                    ('min_volume', s.min_volume),
                                    ('min_oi', s.min_oi),
                                    ('volume_percentile', s.volume_percentile),
                                    ('salvage_enabled', int(bool(s.salvage_enabled))),
                                    ('foreign_expiry_salvage', int(bool(s.foreign_expiry_salvage))),
                                    ('recovery_strategy_legacy', int(bool(s.recovery_strategy_legacy))),
                                    ('domain_models', int(bool(s.domain_models))),
                                    ('trace_collector', int(bool(s.trace_collector or s.trace_enabled))),
                                    ('quiet_mode', int(bool(s.quiet_mode))),
                                    ('quiet_allow_trace', int(bool(s.quiet_allow_trace))),
                                    ('heartbeat_interval', s.loop_heartbeat_interval),
                                    ('outage_threshold', s.provider_outage_threshold),
                                    ('outage_log_every', s.provider_outage_log_every),
                                    ('retry_on_empty', int(bool(s.retry_on_empty))),
                                    ('overrides_count', len(s.log_level_overrides)),
                                    ('pipeline_v2_flag', int(bool(s.pipeline_v2_flag))),
                                ],
                                logging.getLogger(__name__)
                            )
                    except Exception:
                        pass
            except Exception:
                pass
    return _settings_singleton

# Convenience helper for quick flag checks before deeper imports
def PIPELINE_V2_ENABLED() -> bool:
    try:
        return get_collector_settings().pipeline_v2_flag
    except Exception:
        return False
