"""Adaptive degrade exit controller (Phase 9).

Manages transitions of the event bus degraded mode using backlog & latency signals.

States:
  NORMAL       : Not degraded.
  DEGRADED     : Degraded mode active (diffs minimized).
  EXIT_PENDING : Candidate for exit; exit conditions met but hysteresis window not yet elapsed.

Inputs (per publish cycle):
  backlog: current backlog length
  capacity: configured max backlog
  serialize_latency_s: optional latest serialization latency sample

Environment Variables:
  G6_ADAPT_EXIT_BACKLOG_RATIO (float, default 0.4)
  G6_ADAPT_EXIT_WINDOW_SECONDS (float, default 5.0)
  G6_ADAPT_LAT_BUDGET_MS (float, default 50.0)  # average or p95 target
  G6_ADAPT_REENTRY_COOLDOWN_SECONDS (float, default 10.0)
  G6_ADAPT_MIN_SAMPLES (int, default 10)  # minimum samples before evaluating exit

Return values from update():
  None                -> no transition
  'enter_degraded'    -> caller should enter degraded immediately
  'exit_degraded'     -> caller should exit degraded mode

Notes:
  The controller itself does not decide when to enter degraded mode initially; that
  still occurs via existing static thresholds. Once in degraded mode it seeks the
  earliest safe exit that satisfies backlog + latency stability with hysteresis &
  cooldown to prevent thrashing.
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto


class AdaptiveState(Enum):
    NORMAL = auto()
    DEGRADED = auto()
    EXIT_PENDING = auto()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


@dataclass
class AdaptiveConfig:
    exit_backlog_ratio: float = field(default_factory=lambda: _env_float('G6_ADAPT_EXIT_BACKLOG_RATIO', 0.4))
    exit_window_seconds: float = field(default_factory=lambda: _env_float('G6_ADAPT_EXIT_WINDOW_SECONDS', 5.0))
    latency_budget_ms: float = field(default_factory=lambda: _env_float('G6_ADAPT_LAT_BUDGET_MS', 50.0))
    reentry_cooldown_seconds: float = field(default_factory=lambda: _env_float('G6_ADAPT_REENTRY_COOLDOWN_SECONDS', 10.0))
    min_samples: int = field(default_factory=lambda: _env_int('G6_ADAPT_MIN_SAMPLES', 10))


@dataclass
class AdaptiveController:
    config: AdaptiveConfig = field(default_factory=AdaptiveConfig)
    state: AdaptiveState = AdaptiveState.NORMAL
    _backlog_samples: deque[tuple[float, float]] = field(default_factory=lambda: deque())  # (ts, ratio)
    _latency_samples: deque[tuple[float, float]] = field(default_factory=lambda: deque())  # (ts, seconds)
    _last_state_change: float = field(default_factory=time.time)
    _last_exit_ts: float = 0.0
    _last_enter_ts: float = 0.0

    def reset(self) -> None:
        self._backlog_samples.clear()
        self._latency_samples.clear()
        self.state = AdaptiveState.NORMAL
        self._last_state_change = time.time()

    # Public API ------------------------------------------------------
    def notify_enter_degraded(self) -> None:
        now = time.time()
        self.state = AdaptiveState.DEGRADED
        self._last_state_change = now
        self._last_enter_ts = now

    def notify_manual_exit(self) -> None:
        now = time.time()
        self.state = AdaptiveState.NORMAL
        self._last_state_change = now
        self._last_exit_ts = now

    def update(self, backlog: int, capacity: int, serialize_latency_s: float | None) -> str | None:
        """Feed latest metrics; return transition directive or None.

        Caller supplies current backlog and capacity; ratio = backlog / capacity (clamped 0-1).
        Latency sample optional; omitted samples simply do not contribute to latency window.
        """
        now = time.time()
        if capacity <= 0:
            return None
        ratio = max(0.0, min(1.0, backlog / capacity))
        self._backlog_samples.append((now, ratio))
        if serialize_latency_s is not None and serialize_latency_s >= 0:
            self._latency_samples.append((now, serialize_latency_s))
        # Trim windows
        win = self.config.exit_window_seconds
        cutoff = now - win
        while self._backlog_samples and self._backlog_samples[0][0] < cutoff:
            self._backlog_samples.popleft()
        while self._latency_samples and self._latency_samples[0][0] < cutoff:
            self._latency_samples.popleft()

        # If not degraded, we only look for possible false re-entries (cooldown) but don't transition automatically.
        if self.state == AdaptiveState.NORMAL:
            return None

        # Compute stability signals
        if len(self._backlog_samples) < self.config.min_samples:
            return None
        avg_ratio = sum(r for _, r in self._backlog_samples) / len(self._backlog_samples)
        latency_ok = True
        latency_ms = None
        if self._latency_samples:
            # Use p95 approximate via sorted list; small window so OK.
            vals = [s for _, s in self._latency_samples]
            vals.sort()
            idx = int(len(vals) * 0.95) - 1
            if idx < 0:
                idx = 0
            p95 = vals[idx]
            latency_ms = p95 * 1000.0
            latency_ok = latency_ms <= self.config.latency_budget_ms

        # Transition logic
        if self.state == AdaptiveState.DEGRADED:
            # Check if backlog & latency both stabilizing -> move to EXIT_PENDING
            if avg_ratio <= self.config.exit_backlog_ratio and latency_ok:
                self.state = AdaptiveState.EXIT_PENDING
                self._last_state_change = now
            return None
        if self.state == AdaptiveState.EXIT_PENDING:
            # Abort exit if ratio rebounds or latency worsens
            if avg_ratio > self.config.exit_backlog_ratio or not latency_ok:
                self.state = AdaptiveState.DEGRADED
                self._last_state_change = now
                return None
            # Exit if window fully satisfied
            if (now - self._last_state_change) >= self.config.exit_window_seconds:
                # Cooldown: prevent immediate re-entry thrash by recording exit timestamp
                self.state = AdaptiveState.NORMAL
                self._last_state_change = now
                self._last_exit_ts = now
                return 'exit_degraded'
            return None
        return None


__all__ = ["AdaptiveController", "AdaptiveConfig", "AdaptiveState"]
