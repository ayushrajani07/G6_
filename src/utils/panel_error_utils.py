from __future__ import annotations

"""
Centralized panel error handling utilities.

Use these from panel modules to report errors via the central handler and return
user-friendly fallbacks without duplicating try/except logic everywhere.
"""
import importlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.error_handling import handle_ui_error

# Runtime Panel class (or None if rich unavailable)
RichPanel: Any
try:  # pragma: no cover
    RichPanel = importlib.import_module("rich.panel").Panel
except Exception:  # pragma: no cover
    RichPanel = None

if TYPE_CHECKING:  # pragma: no cover
    from rich.panel import Panel as _Panel  # noqa: F401


def centralized_panel_error_handler(component: str = "panel") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for panel functions that integrates with central error system.

    Args:
        component: Component name prefix for error tracking (e.g., "indices_panel")
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                panel_name = func.__name__
                if panel_name.endswith('_panel'):
                    panel_name = panel_name[:-6]
                # Report centrally
                err = handle_ui_error(
                    e,
                    component=f"{component}.{panel_name}",
                    context={
                        "panel": panel_name,
                        "args": str(args)[:200],
                        "kwargs": str(kwargs)[:200],
                    },
                )
                logging.error(
                    "Panel error in %s [Error ID: %s]: %s", func.__name__, getattr(err, 'error_id', '?'), e
                )
                # Return a generic fallback panel if rich is present
                if RichPanel is not None:
                    msg = f"[red]Error loading {panel_name} panel[/]"
                    return RichPanel(msg, title="Error", border_style="red")
                return None
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = getattr(func, "__doc__", None)
        return wrapper
    return decorator


def safe_panel_execute(
    func: Callable[..., Any],
    *args,
    component: str = "panel",
    panel_name: str | None = None,
    default_return: Any = None,
    error_msg: str = "Panel operation failed",
    **kwargs,
) -> Any:
    """Execute a panel helper safely and report errors centrally.

    Returns default_return when failing. If rich is available and default_return
    is None, a small error panel is returned.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        pname = panel_name or getattr(func, "__name__", "panel")
        handle_ui_error(
            e,
            component=f"{component}.{pname}",
            context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]},
        )
        logging.error("%s in %s: %s", error_msg, pname, e, exc_info=True)
        if default_return is None and RichPanel is not None:
            return RichPanel(f"[red]{error_msg}[/]", title="Error", border_style="red", expand=True)
        return default_return
