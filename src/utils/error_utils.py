from __future__ import annotations

"""Generic helpers for standardized try/except blocks using central handler."""
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

T = TypeVar("T")


def try_with_central_handler(
    func: Callable[[], T],
    default: T,
    *,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    component: str = "",
    context: dict[str, Any] | None = None,
    message: str = "",
    log_message: str | None = None,
    reraise: bool = False,
) -> T:
    """Execute a function and route errors to central handler consistently.

    Args mirror the central handler; returns default on failure unless reraise.
    """
    try:
        return func()
    except Exception as e:  # noqa: BLE001
        handler = get_error_handler()
        err = handler.handle_error(
            exception=e,
            category=category,
            severity=severity,
            component=component,
            message=message or str(e),
            context=context or {},
            should_log=True,
            should_reraise=False,
        )
        if log_message:
            logging.error("%s [Error ID: %s]: %s", log_message, getattr(err, "error_id", "?"), e)
        if reraise:
            raise
        return default
