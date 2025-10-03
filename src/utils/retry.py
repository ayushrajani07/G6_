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
from typing import Any, Callable, Iterable, Optional, Sequence, Type

from tenacity import (
    retry, Retrying, stop_after_attempt, stop_after_delay,
    wait_exponential, wait_chain, wait_fixed, wait_random,
    retry_if_exception, retry_if_exception_type,
)

from .exceptions import RetryError
from src.error_handling import get_error_handler, ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)


def _parse_exception_list(csv: str | None) -> list[Type[BaseException]]:
    if not csv:
        return []
    out: list[Type[BaseException]] = []
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
    wl = _parse_exception_list(os.environ.get('G6_RETRY_WHITELIST'))
    bl = _parse_exception_list(os.environ.get('G6_RETRY_BLACKLIST'))
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
    base = float(os.environ.get('G6_RETRY_BACKOFF', '0.2') or '0.2')
    jitter = os.environ.get('G6_RETRY_JITTER', '1').lower() in ('1','true','yes','on')
    exp = wait_exponential(multiplier=base, min=base, max=2.5)
    if jitter:
        return exp + wait_random(0, base)
    return exp


def build_stop_strategy() -> Any:
    attempts = int(os.environ.get('G6_RETRY_MAX_ATTEMPTS', '3') or '3')
    max_seconds = float(os.environ.get('G6_RETRY_MAX_SECONDS', '8') or '8')
    # Use both limits: whichever comes first
    return stop_after_attempt(attempts) | stop_after_delay(max_seconds)


def retryable(func: Optional[Callable[..., Any]] = None, *, reraise: bool = True):
    """Decorator to apply retry with default env-configured strategies.

    Example:
        @retryable
        def fetch():
            ...
    """
    predicate = build_retry_predicate()
    wait = build_wait_strategy()
    stop = build_stop_strategy()
    def _safe_reason(rs: Any) -> Any:
        try:
            outcome = getattr(rs, 'outcome', None)
            if outcome and getattr(outcome, 'failed', False):
                return outcome.exception()
        except Exception:
            return None
        return None

    def _decorator(f: Callable[..., Any]):
        return retry(
            retry=retry_if_exception(predicate),
            wait=wait,
            stop=stop,
            reraise=reraise,
            before_sleep=lambda rs: logger.debug(
                "retrying %s after %s due to %s",
                f.__name__, getattr(rs, 'idle_for', None), _safe_reason(rs)),
        )(f)
    if func is not None:
        return _decorator(func)
    return _decorator


def call_with_retry(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
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


__all__ = ["retryable", "call_with_retry", "build_retry_predicate", "build_wait_strategy", "build_stop_strategy"]
