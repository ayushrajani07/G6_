"""Fault budget tracking for cycle SLA breaches.

Transforms raw `g6_cycle_sla_breach_total` counter into rolling-window SLO signal.

Environment Flags
-----------------
G6_FAULT_BUDGET_ENABLE            : Activate tracking when truthy.
G6_FAULT_BUDGET_WINDOW_SEC        : Rolling window size in seconds (default 3600).
G6_FAULT_BUDGET_ALLOWED_BREACHES  : Allowed breaches within window (default 60).
G6_FAULT_BUDGET_STRICT            : If truthy, emit ERROR log when exhausted (else WARNING at first exhaustion).
G6_FAULT_BUDGET_LOG_DEBUG         : If truthy, per-update debug log emitted.

Metrics (all gauges; created only when enabled):
- g6_cycle_fault_budget_remaining            Remaining breach units (0..allowed).
- g6_cycle_fault_budget_breaches_window      Current breach count within window.
- g6_cycle_fault_budget_window_seconds       Effective window size (static value gauge).
- g6_cycle_fault_budget_consumed_percent     Percent of budget consumed (0..100).

Registry Attachment:
- registry._fault_budget_tracker holds tracker instance (for tests/introspection).

Update Hook:
- Intended to be invoked opportunistically after cycle metrics update. We expose
  `on_cycle(registry)` which will:
    * Read current cumulative counter value.
    * Detect delta since last observation (delta times => new breach events).
    * Append timestamps, prune stale entries, recompute gauges.

Resilience:
- All failures swallowed (governance feature must not destabilize core metrics).
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field

try:
    from prometheus_client import Gauge  # type: ignore
except Exception:  # pragma: no cover
    Gauge = None  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["init_fault_budget", "FaultBudgetTracker"]


def _parse_bool(val: str | None) -> bool:
    return bool(val and val.strip().lower() in {"1","true","yes","on"})


def _now() -> float:  # pragma: no cover - simple wrapper
    return time.time()


@dataclass
class FaultBudgetTracker:
    window_sec: float
    allowed: int
    strict: bool
    debug: bool
    last_total: float = 0.0
    breaches: deque[float] = field(default_factory=deque)
    exhausted: bool = False  # state machine edge detection
    g_remaining: object | None = None
    g_window: object | None = None
    g_breaches: object | None = None
    g_consumed: object | None = None

    def on_cycle(self, registry) -> None:
        """Observe current breach counter and update rolling metrics."""
        try:
            counter = getattr(registry, 'cycle_sla_breach', None)
            if counter is None:
                return
            # Attempt to derive cumulative value; prometheus_client counters have _value.get() or _value
            total = None
            # Prometheus client counters often expose samples via collect(); fallback to internal _value or _value.get()
            # 1. Try direct _value.get()
            try:
                val = getattr(counter, '_value', None)
                if val is not None:
                    try:
                        gv = getattr(val, 'get', None)
                        if callable(gv):
                            v = gv()
                        else:
                            v = val
                        if isinstance(v, (int, float)):
                            total = float(v)
                    except Exception:
                        pass
            except Exception:
                pass
            # 2. Fallback: collect first sample value
            if total is None:
                try:
                    fams = list(counter.collect())  # type: ignore[attr-defined]
                    if fams and fams[0].samples:
                        total = float(fams[0].samples[0].value)
                except Exception:
                    pass
            # 3. Last resort: attributes count/get
            if total is None:
                for attr in ('count','get'):
                    try:
                        obj = getattr(counter, attr)
                        if callable(obj):
                            v = obj()
                            if isinstance(v, (int,float)):
                                total = float(v); break
                    except Exception:
                        continue
            if total is None:
                return
            if total < self.last_total:
                # Counter reset (process restart); reset state
                self.last_total = total
                self.breaches.clear()
            if total > self.last_total:
                delta = int(total - self.last_total)
                now = _now()
                for _ in range(delta):
                    self.breaches.append(now)
                self.last_total = total
            # Prune stale
            cutoff = _now() - self.window_sec
            while self.breaches and self.breaches[0] < cutoff:
                self.breaches.popleft()
            within = len(self.breaches)
            remaining = max(self.allowed - within, 0)
            consumed_pct = 0.0
            if self.allowed > 0:
                consumed_pct = min(100.0, (within / self.allowed) * 100.0)
            # Gauge updates
            if self.g_remaining is not None:
                try: self.g_remaining.set(remaining)  # type: ignore[attr-defined]
                except Exception: pass
            if self.g_breaches is not None:
                try: self.g_breaches.set(within)  # type: ignore[attr-defined]
                except Exception: pass
            if self.g_consumed is not None:
                try: self.g_consumed.set(round(consumed_pct,2))  # type: ignore[attr-defined]
                except Exception: pass
            # Edge detection logs
            if remaining == 0 and not self.exhausted:
                self.exhausted = True
                level = logging.ERROR if self.strict else logging.WARNING
                try:
                    logger.log(level, 'metrics.fault_budget.exhausted allowed=%d window_sec=%.0f within=%d', self.allowed, self.window_sec, within, extra={
                        'event': 'metrics.fault_budget.exhausted',
                        'allowed': self.allowed,
                        'window_sec': self.window_sec,
                        'within': within,
                    })
                except Exception: pass
            elif remaining > 0 and self.exhausted:
                self.exhausted = False
                try:
                    logger.info('metrics.fault_budget.recovered remaining=%d within=%d', remaining, within, extra={
                        'event': 'metrics.fault_budget.recovered',
                        'remaining': remaining,
                        'within': within,
                    })
                except Exception: pass
            elif self.debug:
                try:
                    logger.debug('metrics.fault_budget.update remaining=%d within=%d consumed=%.2f%%', remaining, within, consumed_pct, extra={
                        'event': 'metrics.fault_budget.update',
                        'remaining': remaining,
                        'within': within,
                        'consumed_percent': consumed_pct,
                    })
                except Exception: pass
        except Exception:
            # Governance feature must never raise
            pass


def init_fault_budget(registry) -> None:
    """Initialize fault budget tracking if enabled and counter present."""
    try:
        if not _parse_bool(os.getenv('G6_FAULT_BUDGET_ENABLE')):
            return
        if not hasattr(registry, 'cycle_sla_breach'):
            return
        if getattr(registry, '_fault_budget_tracker', None) is not None:
            return  # already installed
        window_sec = float(os.getenv('G6_FAULT_BUDGET_WINDOW_SEC','3600') or '3600')
        allowed = int(os.getenv('G6_FAULT_BUDGET_ALLOWED_BREACHES','60') or '60')
        strict = _parse_bool(os.getenv('G6_FAULT_BUDGET_STRICT'))
        debug = _parse_bool(os.getenv('G6_FAULT_BUDGET_LOG_DEBUG'))
        if allowed < 0:
            allowed = 0
        if window_sec <= 0:
            window_sec = 1
        if Gauge is None:
            return
        g_remaining = Gauge('g6_cycle_fault_budget_remaining', 'Remaining cycle SLA breach budget in current rolling window')
        g_breaches = Gauge('g6_cycle_fault_budget_breaches_window', 'Cycle SLA breaches observed within rolling window')
        g_window = Gauge('g6_cycle_fault_budget_window_seconds', 'Configured cycle fault budget rolling window size (seconds)')
        g_consumed = Gauge('g6_cycle_fault_budget_consumed_percent', 'Percent of cycle SLA breach budget consumed in window (0-100)')
        # Expose as attributes for tests and introspection (best-effort)
        try: registry.cycle_fault_budget_remaining = g_remaining  # type: ignore[attr-defined]
        except Exception: pass
        try: registry.cycle_fault_budget_breaches_window = g_breaches  # type: ignore[attr-defined]
        except Exception: pass
        try: registry.cycle_fault_budget_window_seconds = g_window  # type: ignore[attr-defined]
        except Exception: pass
        try: registry.cycle_fault_budget_consumed_percent = g_consumed  # type: ignore[attr-defined]
        except Exception: pass
        try:
            g_window.set(window_sec)
        except Exception:
            pass
        tracker = FaultBudgetTracker(window_sec=window_sec, allowed=allowed, strict=strict, debug=debug,
                                     g_remaining=g_remaining, g_breaches=g_breaches, g_window=g_window, g_consumed=g_consumed)
        registry._fault_budget_tracker = tracker  # type: ignore[attr-defined]
    except Exception:
        pass


def fault_budget_on_cycle(registry) -> None:  # convenience bridging call
    try:
        tracker = getattr(registry, '_fault_budget_tracker', None)
        if tracker is not None:
            tracker.on_cycle(registry)
    except Exception:
        pass

__all__.append('fault_budget_on_cycle')  # type: ignore
