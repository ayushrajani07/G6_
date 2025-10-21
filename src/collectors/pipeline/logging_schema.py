#!/usr/bin/env python3
"""Structured logging support for expiry pipeline phases.

Event naming grammar:
  expiry.<phase>.(ok|fail|warn|skip)

All events include a minimal structured key set; optional keys allowed but
should not drop the required ones.

Required keys:
  phase        : phase name string
  dt_ms        : phase wall time milliseconds (float, 2 decimal precision suggested)
  index        : index symbol
  rule         : rule / strategy identifier (if available)
  outcome      : ok|fail|warn|skip

Helper exposes context manager `phase_log(phase, meta_provider)` used like:

  with phase_logger.phase_log('fetch', ctx=index_ctx) as pl:
      ... work ...
      pl.add_meta(strike_count=len(strikes))
      # on failure: pl.fail(reason="network")

Outcome defaults to 'ok' unless fail()/warn()/skip() called.

A lightweight dedup mechanism prevents identical consecutive WARN/FAIL lines
with the same (phase,index,rule,outcome,reason) signature.

Environment flags:
  G6_PIPELINE_LOG_LEVEL_BASE=INFO (default) -> base log level
  G6_PIPELINE_LOG_DEDUP_DISABLE=1 -> disable dedup
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger('src.collectors.pipeline')

_BASE_LEVEL = getattr(logging, os.getenv('G6_PIPELINE_LOG_LEVEL_BASE','INFO').upper(), logging.INFO)
_DEDUP_DISABLED = os.getenv('G6_PIPELINE_LOG_DEDUP_DISABLE') in ('1','true','on','yes')
_PHASE_METRICS = os.getenv('G6_PIPELINE_PHASE_METRICS') in ('1','true','on','yes')

_phase_duration_observer: Any | None = None
if _PHASE_METRICS:
    try:
        # Lazy import: expect a metrics facade exposing histogram observe
        import importlib
        _m = importlib.import_module('src.metrics')
        get_histogram = getattr(_m, 'get_histogram', None)
        if callable(get_histogram):
            _phase_duration_observer = get_histogram('pipeline_phase_duration_seconds', 'Pipeline phase durations', ['phase'])
        else:
            _phase_duration_observer = None
    except Exception:  # pragma: no cover
        _phase_duration_observer = None

_dedup_lock = threading.Lock()
_last_sig: tuple | None = None

@dataclass
class _PhaseRecord:
    phase: str
    index: str
    rule: str
    started: float
    outcome: str = 'ok'
    reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def add_meta(self, **kw: Any) -> None:
        self.meta.update({k: v for k,v in kw.items() if v is not None})

    def fail(self, reason: str | None = None) -> None:
        self.outcome = 'fail'
        self.reason = reason
    def warn(self, reason: str | None = None) -> None:
        self.outcome = 'warn'
        self.reason = reason
    def skip(self, reason: str | None = None) -> None:
        self.outcome = 'skip'
        self.reason = reason

@contextmanager
def phase_log(phase: str, ctx: Any = None, rule: str = '', index: str = '') -> Iterator[_PhaseRecord]:
    from src.collectors.pipeline.errors import PhaseFatalError, PhaseRecoverableError
    rec = _PhaseRecord(phase=phase, index=index, rule=rule, started=time.time())
    try:
        yield rec
    except PhaseRecoverableError as e:
        rec.fail(reason=str(e))
        logger.log(_BASE_LEVEL, f"phase={rec.phase} index={rec.index} rule={rec.rule} outcome=fail reason={rec.reason} meta={rec.meta}")
        raise
    except PhaseFatalError as e:
        rec.fail(reason=f"FATAL: {e}")
        logger.log(_BASE_LEVEL, f"phase={rec.phase} index={rec.index} rule={rec.rule} outcome=fatal reason={rec.reason} meta={rec.meta}")
        raise
    else:
        # If outcome not set, mark as ok or log appropriate outcome
        if rec.outcome == 'ok':
            logger.log(_BASE_LEVEL, f"phase={rec.phase} index={rec.index} rule={rec.rule} outcome=ok meta={rec.meta}")
        else:
            logger.log(_BASE_LEVEL, f"phase={rec.phase} index={rec.index} rule={rec.rule} outcome={rec.outcome} reason={rec.reason} meta={rec.meta}")
    finally:
        if _PHASE_METRICS and _phase_duration_observer is not None:
            try:
                dt = (time.time() - rec.started)
                if hasattr(_phase_duration_observer, 'labels'):
                    _phase_duration_observer.labels(phase=rec.phase).observe(dt)
            except Exception:  # pragma: no cover
                pass

class PhaseLogger:
    REQUIRED_KEYS = ('phase','dt_ms','index','rule','outcome')

    def __init__(self, base_logger: logging.Logger | None = None) -> None:
        self._logger = base_logger or logger

    @contextmanager
    def phase_log(self, phase: str, index: str, rule: str, extra_meta_provider: Callable[[], dict[str, Any]] | None = None) -> Iterator[_PhaseRecord]:
        rec = _PhaseRecord(phase=phase, index=index, rule=rule, started=time.perf_counter())
        error: Exception | None = None
        try:
            yield rec
        except Exception as e:  # escalate as failure but re-raise
            rec.fail(reason=str(e.__class__.__name__))
            error = e
        finally:
            dt_ms = (time.perf_counter() - rec.started) * 1000.0
            payload: dict[str, Any] = {
                'phase': rec.phase,
                'dt_ms': round(dt_ms, 2),
                'index': rec.index,
                'rule': rec.rule,
                'outcome': rec.outcome,
            }
            if rec.reason:
                payload['reason'] = rec.reason
            if extra_meta_provider:
                try:
                    rec.add_meta(**(extra_meta_provider() or {}))
                except Exception:
                    pass
            # Merge meta (later keys won't overwrite required ones)
            for k,v in rec.meta.items():
                if k in payload:
                    continue
                payload[k] = v
            self._emit(payload)
            if error is not None:
                raise error

    def _emit(self, payload: dict[str, Any]) -> None:
        # Dedup signature
        global _last_sig
        sig = (
            payload.get('phase'), payload.get('index'), payload.get('rule'),
            payload.get('outcome'), payload.get('reason')
        )
        if not _DEDUP_DISABLED:
            with _dedup_lock:
                if sig == _last_sig and payload.get('outcome') in ('warn','fail'):
                    return
                _last_sig = sig
        level = _BASE_LEVEL
        outcome = payload.get('outcome')
        if outcome == 'fail':
            level = logging.ERROR
        elif outcome == 'warn':
            level = logging.WARNING
        elif outcome == 'skip':
            level = logging.INFO
        # Flatten into key=value string
        parts = [f"expiry.{payload['phase']}.{payload['outcome']}"]
        for k,v in payload.items():
            if k in ('phase','outcome'):
                continue
            parts.append(f"{k}={v}")
        line = ' '.join(parts)
        try:
            self._logger.log(level, line)
        except Exception:
            # Never allow logging failures to break pipeline
            pass

# Singleton style accessor (cheap)
_phase_logger = PhaseLogger()

def get_phase_logger() -> PhaseLogger:
    return _phase_logger
