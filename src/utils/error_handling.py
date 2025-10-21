"""Standardized error handling utilities (Phase 2 baseline).

Provides a unified place to categorize and handle errors with consistent
logging semantics. Adoption can be incremental—legacy try/except blocks can
be refactored to use these helpers over time.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import ParamSpec, TypeVar

__all__ = [
    "ErrorSeverity",
    "handle_error",
    "safe_operation",
]

logger = logging.getLogger(__name__)

class ErrorSeverity(Enum):
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5

P = ParamSpec("P")
T = TypeVar("T")

def handle_error(e: Exception, *, severity: ErrorSeverity = ErrorSeverity.ERROR, reraise: bool = True, context: str | None = None) -> None:
    ctx = f" [{context}]" if context else ""
    if severity is ErrorSeverity.DEBUG:
        logger.debug("Error%s: %s", ctx, e, exc_info=True)
    elif severity is ErrorSeverity.INFO:
        logger.info("Error%s: %s", ctx, e, exc_info=True)
    elif severity is ErrorSeverity.WARNING:
        logger.warning("Error%s: %s", ctx, e, exc_info=True)
    elif severity is ErrorSeverity.ERROR:
        logger.error("Error%s: %s", ctx, e, exc_info=True)
    elif severity is ErrorSeverity.CRITICAL:
        logger.critical("Error%s: %s", ctx, e, exc_info=True)
    if reraise:
        raise

def safe_operation(*, severity: ErrorSeverity = ErrorSeverity.WARNING, reraise: bool = False) -> Callable[[Callable[P, T]], Callable[P, T | None]]:
    """Decorator converting exceptions into logged events.

    Parameters
    ----------
    severity : ErrorSeverity
        Logging severity if an exception occurs.
    reraise : bool
        If True, exception is re-raised after logging.
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T | None]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                handle_error(e, severity=severity, reraise=reraise, context=func.__name__)
                return None
        return wrapper
    return decorator
