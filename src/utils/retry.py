"""Retry utilities built on tenacity.

Provides a small API:
- retryable decorator for functions/methods
- call_with_retry helper for ad-hoc calls

Environment knobs:
  G6_RETRY_MAX_ATTEMPTS: default 3
  G6_RETRY_MAX_SECONDS:  overall cap in seconds (default 8)
  G6_RETRY_BACKOFF:      base backoff seconds (default 0.2)
  G6_RETRY_JITTER:       add random jitter (default on)
  G6_RETRY_WHITELIST:    comma-separated exception class names to retry (default: TimeoutError, ConnectionError)
  G6_RETRY_BLACKLIST:    comma-separated exception class names to NOT retry
"""
from __future__ import annotations

import importlib
import logging
import os

try:
    from src.collectors.env_adapter import get_bool as _env_get_bool
    from src.collectors.env_adapter import get_str as _env_get_str  # type: ignore
except Exception:  # pragma: no cover
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default
    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = os.getenv(name)
            if v is None:
                return default
            return str(v).strip().lower() in {"1","true","yes","on","y"}
        except Exception:
            return default
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast, overload

from tenacity import (
    Retrying,
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_random,
)

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

from .exceptions import RetryError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _parse_exception_list(csv: str | None) -> list[type[BaseException]]:
    if not csv:
        return []
    out: list[type[BaseException]] = []
    for name in (x.strip() for x in csv.split(',') if x.strip()):
        try:
            # support builtins like TimeoutError and fully qualified names
            if '.' not in name:
                exc = getattr(__import__('builtins'), name)
            else:
                mod_name, cls_name = name.rsplit('.', 1)
                mod = importlib.import_module(mod_name)
                exc = getattr(mod, cls_name)
            if isinstance(exc, type) and issubclass(exc, BaseException):
                out.append(exc)
        except Exception as e:
            # Route to central handler but keep behavior: just skip unknown names
            get_error_handler().handle_error(
                exception=e,
                category=ErrorCategory.CONFIGURATION,
                severity=ErrorSeverity.LOW,
                component="utils.retry",
                function_name="_parse_exception_list",
                message=f"Unknown exception type in retry list: {name}",
                context={"token": name},
                should_log=False,
                should_reraise=False,
            )
    return out


def build_retry_predicate() -> Callable[[BaseException], bool]:
    wl = _parse_exception_list(_env_get_str('G6_RETRY_WHITELIST', '') or None)
    bl = _parse_exception_list(_env_get_str('G6_RETRY_BLACKLIST', '') or None)
    def _predicate(e: BaseException) -> bool:
        # If blacklisted, do not retry
        if any(isinstance(e, t) for t in bl):
            return False
        # If whitelist provided, only retry those
        if wl:
            return any(isinstance(e, t) for t in wl)
        # Default: typical transient network errors
        default_retryables = (TimeoutError, ConnectionError)
        return isinstance(e, default_retryables)
    return _predicate


def build_wait_strategy() -> Any:
    try:
        base = float(_env_get_str('G6_RETRY_BACKOFF', '0.2') or '0.2')
    except Exception:
        base = 0.2
    # Default jitter to True if env missing (legacy behavior)
    jitter = _env_get_bool('G6_RETRY_JITTER', True)
    exp = wait_exponential(multiplier=base, min=base, max=2.5)
    if jitter:
        return exp + wait_random(0, base)
    return exp


def build_stop_strategy() -> Any:
    try:
        attempts = int(_env_get_str('G6_RETRY_MAX_ATTEMPTS', '3') or '3')
    except Exception:
        attempts = 3
    try:
        max_seconds = float(_env_get_str('G6_RETRY_MAX_SECONDS', '8') or '8')
    except Exception:
        max_seconds = 8.0
    # Use both limits: whichever comes first
    return stop_after_attempt(attempts) | stop_after_delay(max_seconds)


@overload
def retryable(func: None = None, *, reraise: bool = True) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

@overload
def retryable(func: Callable[P, R], *, reraise: bool = True) -> Callable[P, R]: ...

def retryable(func: Callable[P, R] | None = None, *, reraise: bool = True) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """Decorator to apply retry with default env-configured strategies.

    Example:
        @retryable
        def fetch():
            ...
    """
    predicate = build_retry_predicate()
    wait = build_wait_strategy()
    stop = build_stop_strategy()
    def _safe_reason(rs: object) -> object | None:
        try:
            outcome = getattr(rs, 'outcome', None)
            if outcome and getattr(outcome, 'failed', False):
                exc = getattr(outcome, 'exception', None)
                if callable(exc):
                    # exc() can be Any; cast to object to satisfy the return type
                    try:
                        v = exc()
                    except Exception:
                        return None
                    return cast(object, v)
                return None
        except Exception:
            return None
        return None

    def _decorator(f: Callable[P, R]) -> Callable[P, R]:
        wrapped = retry(
            retry=retry_if_exception(predicate),
            wait=wait,
            stop=stop,
            reraise=reraise,
            before_sleep=lambda rs: logger.debug(
                "retrying %s after %s due to %s",
                f.__name__, getattr(rs, 'idle_for', None), _safe_reason(rs)),
        )(f)
        return cast(Callable[P, R], wrapped)
    if func is not None:
        return _decorator(func)
    return _decorator


def call_with_retry(fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Call a function with retry using env-configured strategies.

    Raises RetryError if operation ultimately fails.
    """
    predicate = build_retry_predicate()
    wait = build_wait_strategy()
    stop = build_stop_strategy()
    try:
        for attempt in Retrying(
            retry=retry_if_exception(lambda e: predicate(e)),
            wait=wait,
            stop=stop,
            reraise=True,
        ):
            with attempt:
                return fn(*args, **kwargs)
    except Exception as e:  # underlying exception
        raise RetryError(str(e)) from e
    # Should be unreachable: Retrying either returns or raises
    raise RetryError("Operation did not execute")


__all__ = ["retryable", "call_with_retry", "build_retry_predicate", "build_wait_strategy", "build_stop_strategy"]
