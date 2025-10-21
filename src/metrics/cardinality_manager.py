#!/usr/bin/env python3
"""
CardinalityManager: adaptive gate for high-cardinality per-option metrics.

This module provides a lightweight, env-configurable controller that decides
whether to emit per-option Prometheus metrics for a given labelset
(index, expiry, strike, type) to mitigate time-series explosion.

Defaults are conservative: manager is disabled unless explicitly enabled via
environment variables. When disabled, should_emit always returns True.

Environment variables (all optional):
  - G6_METRICS_CARD_ENABLED: '1'|'true' enables manager (default: off)
  - G6_METRICS_CARD_ATM_WINDOW: integer number of strike steps to allow
      around ATM (0 disables ATM gating). Default: 0
  - G6_METRICS_CARD_RATE_LIMIT_PER_SEC: maximum accepted emissions per second
      across all options (0 disables rate limiting). Default: 0
  - G6_METRICS_CARD_CHANGE_THRESHOLD: minimum absolute change in price required
      since last seen for same (index, expiry, strike, type) to emit, expressed
      as absolute (not percent). Set 0.0 to disable. Default: 0.0

Minimal implementation note: We intentionally keep state simple and
process-local to avoid invasive changes. More advanced per-expiry/global limits
or memory-pressure coupling can be layered on later.
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default

def _get_adaptive_mode(metrics_obj) -> int | None:
    """Best-effort fetch of adaptive current detail mode stored on metrics singleton.
    Adaptive logic persists '_adaptive_current_mode'; return int or None."""
    try:
        if metrics_obj is None:
            return None
        val = getattr(metrics_obj, '_adaptive_current_mode', None)
        if val is None:
            return None
        return int(val)
    except Exception:
        return None


@dataclass
class CardinalityConfig:
    enabled: bool = False
    atm_window: int = 0  # accept strikes within +/- window of ATM (0 disables)
    rate_limit_per_sec: int = 0  # 0 disables
    change_threshold: float = 0.0  # absolute value change required to emit (0 disables)


class CardinalityManager:
    """Decides whether to emit per-option metrics.

    State tracked:
      - token bucket for global per-second rate limit
      - last observed value per key for change-threshold gating
    """

    def __init__(self, cfg: CardinalityConfig | None = None):
        self.cfg = cfg or CardinalityConfig()
        # rate limit bucket: holds timestamps of accepted events in the last 1s
        self._recent_accepts: deque[float] = deque()
        # last observed price per (index, expiry, strike, type)
        self._last_value: dict[tuple[str, str, str, str], float] = {}
        # optional metrics registry (set via set_metrics)
        self._metrics = None

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled)

    def set_metrics(self, metrics) -> None:
        """Optionally attach metrics registry for sampling counters."""
        self._metrics = metrics
        # If registry exposes configured rate limit gauge, set it
        try:
            if hasattr(metrics, 'metric_sampling_rate_limit_per_sec'):
                metrics.metric_sampling_rate_limit_per_sec.labels(category='option').set(float(self.cfg.rate_limit_per_sec))
        except Exception:
            pass

    def _rate_limited(self, now: float) -> bool:
        limit = int(self.cfg.rate_limit_per_sec or 0)
        if limit <= 0:
            return False
        # Pop timestamps older than 1s from the left
        window_start = now - 1.0
        while self._recent_accepts and self._recent_accepts[0] < window_start:
            self._recent_accepts.popleft()
        if len(self._recent_accepts) >= limit:
            return True
        return False

    def _record_decision(self, decision: str, reason: str) -> None:
        m = self._metrics
        if not m:
            return
        try:
            if hasattr(m, 'metric_sampling_events'):
                m.metric_sampling_events.labels(category='option', decision=decision, reason=reason).inc()
        except Exception:
            pass

    def should_emit(self, index: str, expiry: str, strike: int | float, opt_type: str,
                    atm_strike: int | float | None = None,
                    value: float | None = None) -> bool:
        """Return True if per-option metrics should be emitted.

        Parameters
        ----------
        index, expiry, strike, opt_type : labels for the option
        atm_strike : optional ATM strike to apply window gating
        value : representative value for change-threshold comparison (e.g., last_price)
        """
        # --- Adaptive detail mode gating ALWAYS evaluated (even if manager disabled) ---
        # Rationale: Forward-looking design expects adaptive controller to demote detail mode
        # as a graceful degradation independent of whether legacy cardinality manager feature
        # toggles are enabled. Tests rely on band window rejections even when manager disabled.
        m_mode = _get_adaptive_mode(self._metrics)
        if m_mode == 2:  # aggregate mode suppresses all per-option metrics
            self._record_decision('reject', 'detail_mode_agg')
            return False
        # Load config-based fallback first (ensures monkeypatched get_loaded_config visible even when env set later)
        band_window = None
        try:
            cfg = None
            local_glc = globals().get('get_loaded_config')
            if callable(local_glc):
                cfg = local_glc()  # type: ignore[misc]
            else:
                from src.config.loader import get_loaded_config as _glc  # type: ignore
                cfg = _glc()
            if isinstance(cfg, dict):
                val = None
                adaptive = cfg.get('adaptive')
                if isinstance(adaptive, dict):
                    dm = adaptive.get('detail_mode')
                    if isinstance(dm, dict):
                        val = dm.get('band_window')
                if val is None:
                    val = cfg.get('band_window')
                if isinstance(val, (int,float)) and int(val) > 0:
                    band_window = int(val)
        except Exception:
            band_window = None
        # Env override always wins when positive
        try:
            env_bw = _env_int('G6_DETAIL_MODE_BAND_ATM_WINDOW', 0)
            if int(env_bw) > 0:
                band_window = int(env_bw)
        except Exception:
            pass
        if band_window is None:
            band_window = 0
        if m_mode == 1 and (band_window or 0) > 0 and atm_strike is not None:
            try:
                if abs(float(strike) - float(atm_strike)) > float(band_window):
                    self._record_decision('reject', 'detail_mode_band_window')
                    try:
                        if self._metrics and hasattr(self._metrics, 'option_detail_band_rejections'):
                            self._metrics.option_detail_band_rejections.labels(index=index).inc()
                    except Exception:
                        pass
                    return False
            except Exception:
                # If comparison fails, fall through (do not accept early yet)
                pass

        # If manager disabled and not rejected by adaptive gating, auto-accept
        if not self.enabled:
            self._record_decision('accept', 'disabled')
            return True

        now = time.time()

        # ATM window gating
        w = int(self.cfg.atm_window or 0)
        if w > 0 and atm_strike is not None:
            try:
                if abs(float(strike) - float(atm_strike)) > w * 1.0:  # treat 1.0 as step; callers pick w accordingly
                    self._record_decision('reject', 'atm_window')
                    return False
            except Exception:
                # If comparison fails, fall through without gating
                pass

        # Rate limit gating (global per second)
        if self._rate_limited(now):
            self._record_decision('reject', 'rate_limit')
            return False

        # Change-threshold gating
        thr = float(self.cfg.change_threshold or 0.0)
        if thr > 0.0 and value is not None:
            key = (str(index), str(expiry), str(strike), str(opt_type).upper())
            last = self._last_value.get(key)
            try:
                v = float(value)
                if last is not None and abs(v - last) < thr:
                    self._record_decision('reject', 'no_significant_change')
                    return False
                # Record new value on accept path later
            except Exception:
                pass

        # Accept: record
        if thr > 0.0 and value is not None:
            try:
                key = (str(index), str(expiry), str(strike), str(opt_type).upper())
                self._last_value[key] = float(value)
            except Exception:
                pass
        # Token bucket: push timestamp
        if int(self.cfg.rate_limit_per_sec or 0) > 0:
            self._recent_accepts.append(now)
        self._record_decision('accept', 'passed')
        return True


_SINGLETON: CardinalityManager | None = None


def get_cardinality_manager() -> CardinalityManager:
    """Return process singleton CardinalityManager using env-configured settings."""
    global _SINGLETON  # noqa: PLW0603
    env_enabled = _env_bool('G6_METRICS_CARD_ENABLED', False)
    env_atm = _env_int('G6_METRICS_CARD_ATM_WINDOW', 0)
    env_rate = _env_int('G6_METRICS_CARD_RATE_LIMIT_PER_SEC', 0)
    env_thr = _env_float('G6_METRICS_CARD_CHANGE_THRESHOLD', 0.0)
    if _SINGLETON is None:
        _SINGLETON = CardinalityManager(CardinalityConfig(
            enabled=env_enabled, atm_window=env_atm, rate_limit_per_sec=env_rate, change_threshold=env_thr
        ))
    else:
        # Refresh config if any env changed (supports tests toggling flags mid-process)
        cfg = _SINGLETON.cfg
        if (cfg.enabled != env_enabled or cfg.atm_window != env_atm or
                cfg.rate_limit_per_sec != env_rate or cfg.change_threshold != env_thr):
            _SINGLETON.cfg = CardinalityConfig(
                enabled=env_enabled, atm_window=env_atm, rate_limit_per_sec=env_rate, change_threshold=env_thr
            )
    return _SINGLETON


__all__ = [
    'CardinalityManager',
    'CardinalityConfig',
    'get_cardinality_manager',
]
