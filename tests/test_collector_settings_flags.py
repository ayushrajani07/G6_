#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for CollectorSettings consolidated flags (A23).

Focus (post synthetic removal):
- Foreign expiry salvage flag preference order (foreign_expiry_salvage > salvage_enabled)
- Recovery strategy legacy flag exposure
- Heartbeat / outage thresholds numeric parsing stability

Tests are lightweight and avoid full collection loops; they validate parsing + simple conditional use.
"""
from __future__ import annotations
import os
import importlib

from src.collector.settings import get_collector_settings, CollectorSettings


def _reload_with_env(env: dict):
    # Clear singleton then patch os.environ copy
    for k in list(os.environ.keys()):
        if k.startswith('G6_'):
            # do not erase existing unrelated variables; rely on passed env to override
            pass
    os.environ.update(env)
    import src.collector.settings as cs  # type: ignore
    if '_settings_singleton' in cs.__dict__:
        cs._settings_singleton = None  # type: ignore
    return get_collector_settings(force_reload=True)


def test_removed_synthetic_flag_absent():
    s = _reload_with_env({'G6_DISABLE_SYNTHETIC_FALLBACK': '1'})
    # Attribute should be fully removed; getattr fallback should return False
    assert not hasattr(s, 'disable_synthetic_fallback')


def test_salvage_flag_priority():
    # foreign_expiry_salvage should mirror G6_FOREIGN_EXPIRY_SALVAGE
    s = _reload_with_env({'G6_FOREIGN_EXPIRY_SALVAGE': '1'})
    assert s.foreign_expiry_salvage is True
    assert s.salvage_enabled is True  # both set currently


def test_recovery_strategy_legacy_flag():
    s = _reload_with_env({'G6_RECOVERY_STRATEGY_LEGACY': '1'})
    assert s.recovery_strategy_legacy is True
    s2 = _reload_with_env({'G6_RECOVERY_STRATEGY_LEGACY': '0'})
    assert s2.recovery_strategy_legacy is False


def test_outage_threshold_and_log_every_defaults_and_overrides():
    s = _reload_with_env({})
    assert s.provider_outage_threshold == 3
    assert s.provider_outage_log_every == 5
    s2 = _reload_with_env({'G6_PROVIDER_OUTAGE_THRESHOLD': '7', 'G6_PROVIDER_OUTAGE_LOG_EVERY': '9'})
    assert s2.provider_outage_threshold == 7
    assert s2.provider_outage_log_every == 9


def test_heartbeat_interval_parse():
    s = _reload_with_env({'G6_LOOP_HEARTBEAT_INTERVAL': '2.5'})
    assert abs(s.loop_heartbeat_interval - 2.5) < 1e-6

