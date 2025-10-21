"""
Centralized Error Handling System for G6 Platform

This module provides comprehensive error handling, logging, and routing
capabilities for the entire G6 platform ecosystem.
"""

import functools
import json
import logging
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast, runtime_checkable


class ErrorCategory(Enum):
    """Categorization of errors for better tracking and handling."""

    # Data Collection Errors (routed to Indices Panel)
    COLLECTOR = "collector"
    PROVIDER_API = "provider_api"
    NETWORK = "network"
    DATA_VALIDATION = "data_validation"
    DATA_PARSING = "data_parsing"
    DATA_COLLECTION = "data_collection"

    # Processing Errors
    CALCULATION = "calculation"
    TRANSFORMATION = "transformation"
    ANALYTICS = "analytics"

    # Storage Errors
    FILE_IO = "file_io"
    DATABASE = "database"
    CSV_WRITE = "csv_write"
    BACKUP = "backup"

    # System Errors
    CONFIGURATION = "configuration"
    INITIALIZATION = "initialization"
    RESOURCE = "resource"
    MEMORY = "memory"

    # UI/Display Errors
    RENDERING = "rendering"
    PANEL_DISPLAY = "panel_display"
    RICH_MARKUP = "rich_markup"

    # General/Unknown Errors
    UNKNOWN = "unknown"
    CRITICAL = "critical"


class ErrorDestination(Enum):
    """Defines where errors should be routed for display."""
    INDICES_PANEL = "indices_panel"  # Collector errors go here
    ALERTS_PANEL = "alerts_panel"    # All other errors go here
    BOTH_PANELS = "both_panels"      # Critical errors that need wide visibility

    # General/Unknown
    UNKNOWN = "unknown"
    CRITICAL = "critical"


class ErrorSeverity(Enum):
    """Error severity levels for prioritization."""

    LOW = "low"          # Non-critical, cosmetic issues
    MEDIUM = "medium"    # Affects functionality but not critical
    HIGH = "high"        # Important functionality affected
    CRITICAL = "critical" # System stability threatened


@dataclass
class ErrorInfo:
    """Comprehensive error information structure with routing."""

    # Core error details
    exception: Exception
    category: ErrorCategory
    severity: ErrorSeverity

    # Context information
    component: str = ""
    function_name: str = ""
    message: str = ""

    # Technical details
    traceback_str: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    thread_id: str = ""

    # Additional context
    context: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    # Error routing information
    destination: ErrorDestination = field(init=False)

    def __post_init__(self):
        """Determine error destination based on category."""
        # Collector errors go to indices panel (live stream description)
        collector_categories = {
            ErrorCategory.COLLECTOR,
            ErrorCategory.PROVIDER_API,
            ErrorCategory.NETWORK,
            ErrorCategory.DATA_VALIDATION,
            ErrorCategory.DATA_PARSING,
            ErrorCategory.DATA_COLLECTION
        }

        if self.category in collector_categories:
            self.destination = ErrorDestination.INDICES_PANEL
        elif self.severity == ErrorSeverity.CRITICAL:
            # Critical errors go to both panels for maximum visibility
            self.destination = ErrorDestination.BOTH_PANELS
        else:
            # All other errors go to alerts panel
            self.destination = ErrorDestination.ALERTS_PANEL

    def to_dict(self) -> dict[str, Any]:
        """Convert ErrorInfo to dictionary for serialization."""
        return {
            "exception_type": type(self.exception).__name__,
            "exception_message": str(self.exception),
            "category": self.category.value,
            "severity": self.severity.value,
            "component": self.component,
            "function_name": self.function_name,
            "message": self.message,
            "traceback": self.traceback_str,
            "timestamp": self.timestamp.isoformat(),
            "thread_id": self.thread_id,
            "context": self.context,
            "retry_count": self.retry_count
        }


class G6ErrorHandler:
    """Centralized error handling and logging system."""

    def __init__(self, log_file: str | None = None, max_errors: int = 1000):
        """
        Initialize the error handler.
        
        Args:
            log_file: Optional file path for error logging
            max_errors: Maximum number of errors to keep in memory
        """
        self.logger = logging.getLogger("G6ErrorHandler")
        self.errors: list[ErrorInfo] = []
        self.max_errors = max_errors
        self._lock = threading.Lock()

        # Setup file logging if specified
        if log_file:
            self._setup_file_logging(log_file)

        # Error statistics
        self.error_counts: dict[str, int] = {}
        self.category_counts: dict[ErrorCategory, int] = {}
        self.severity_counts: dict[ErrorSeverity, int] = {}

    def _setup_file_logging(self, log_file: str) -> None:
        """Setup file logging for errors."""
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.ERROR)
        except Exception as e:
            print(f"Failed to setup error log file {log_file}: {e}")

    def handle_error(
        self,
        exception: Exception,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        component: str = "",
        function_name: str = "",
        message: str = "",
        context: dict[str, Any] | None = None,
        should_log: bool = True,
        should_reraise: bool = False
    ) -> ErrorInfo:
        """
        Handle an error with comprehensive logging and tracking.
        
        Args:
            exception: The exception that occurred
            category: Error category for classification
            severity: Error severity level
            component: Component where error occurred
            function_name: Function name where error occurred
            message: Additional context message
            context: Additional context data
            should_log: Whether to log the error
            should_reraise: Whether to re-raise the exception
            
        Returns:
            ErrorInfo object with complete error details
        """
        # Create comprehensive error info
        error_info = ErrorInfo(
            exception=exception,
            category=category,
            severity=severity,
            component=component,
            function_name=function_name,
            message=message or str(exception),
            traceback_str=traceback.format_exc(),
            thread_id=str(threading.current_thread().ident),
            context=context or {}
        )

        # Store error with thread safety
        with self._lock:
            self.errors.append(error_info)
            if len(self.errors) > self.max_errors:
                self.errors.pop(0)  # Remove oldest error

            # Update statistics
            exc_type = type(exception).__name__
            self.error_counts[exc_type] = self.error_counts.get(exc_type, 0) + 1
            self.category_counts[category] = self.category_counts.get(category, 0) + 1
            self.severity_counts[severity] = self.severity_counts.get(severity, 0) + 1

        # Opportunistically emit labeled metrics (best-effort, no hard dependency)
        try:
            @runtime_checkable
            class _MetricsLike(Protocol):  # minimal protocol for static typing
                def inc_api_error(self, *, provider: Any, component: str, error_type: str) -> Any: ...
                def inc_network_error(self, *, provider: Any, component: str, error_type: str) -> Any: ...
                def inc_data_error(self, *, index: Any, component: str, error_type: str) -> Any: ...

            from src.metrics import get_metrics_singleton  # facade import
            metrics_obj = get_metrics_singleton()
            metrics = cast(_MetricsLike | None, metrics_obj)
            if metrics is not None:
                ctx = context or {}
                comp = component or error_info.component or "unknown"
                provider = ctx.get("provider")
                if not provider:
                    lc = comp.lower()
                    if "kite" in lc:
                        provider = "kite"
                error_type = (
                    ctx.get("error_type")
                    or ctx.get("data_type")
                    or type(exception).__name__
                    or category.value
                )
                if category == ErrorCategory.PROVIDER_API:
                    try:
                        metrics.inc_api_error(provider=provider, component=comp, error_type=str(error_type))
                    except Exception:
                        pass
                elif category == ErrorCategory.NETWORK:
                    try:
                        metrics.inc_network_error(provider=provider, component=comp, error_type=str(error_type))
                    except Exception:
                        pass
                elif category in (ErrorCategory.DATA_VALIDATION, ErrorCategory.DATA_PARSING, ErrorCategory.DATA_COLLECTION, ErrorCategory.COLLECTOR):
                    try:
                        index = ctx.get("index")
                        metrics.inc_data_error(index=index, component=comp, error_type=str(error_type))
                    except Exception:
                        pass
        except Exception:
            pass

        # Log the error
        if should_log:
            self._log_error(error_info)

        # Re-raise if requested
        if should_reraise:
            raise exception

        return error_info

    def _log_error(self, error_info: ErrorInfo) -> None:
        """Log error information at appropriate level."""
        log_msg = (
            f"[{error_info.category.value.upper()}] "
            f"{error_info.component}.{error_info.function_name}: "
            f"{error_info.message}"
        )

        if error_info.context:
            log_msg += f" | Context: {error_info.context}"

        # Log at appropriate level based on severity
        if error_info.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(log_msg, exc_info=error_info.exception)
        elif error_info.severity == ErrorSeverity.HIGH:
            self.logger.error(log_msg, exc_info=error_info.exception)
        elif error_info.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)

    def get_recent_errors(self, count: int = 50) -> list[ErrorInfo]:
        """Get recent errors for monitoring."""
        with self._lock:
            return self.errors[-count:] if self.errors else []

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary statistics."""
        with self._lock:
            return {
                "total_errors": len(self.errors),
                "by_type": dict(self.error_counts),
                "by_category": {cat.value: count for cat, count in self.category_counts.items()},
                "by_severity": {sev.value: count for sev, count in self.severity_counts.items()},
                "recent_error_count": len([e for e in self.errors[-100:]
                                         if (datetime.now(UTC) - e.timestamp).seconds < 300])  # Last 5 minutes
            }

    def clear_errors(self) -> None:
        """Clear all stored errors (useful for testing)."""
        with self._lock:
            self.errors.clear()
            self.error_counts.clear()
            self.category_counts.clear()
            self.severity_counts.clear()

    def export_errors(self, file_path: str, count: int | None = None) -> None:
        """Export errors to JSON file for analysis."""
        try:
            errors_to_export = self.get_recent_errors(count or len(self.errors))
            export_data = {
                "timestamp": datetime.now(UTC).isoformat(),
                "summary": self.get_error_summary(),
                "errors": [error.to_dict() for error in errors_to_export]
            }

            with open(file_path, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)

        except Exception as e:
            # Route through central handler instead of logging-only
            self.handle_error(
                exception=e,
                category=ErrorCategory.CONFIGURATION,
                severity=ErrorSeverity.MEDIUM,
                component="error_handling",
                function_name="export_errors",
                message="Failed to export errors",
                context={"file_path": file_path},
                should_log=True,
                should_reraise=False,
            )

    def get_errors_for_indices_panel(self, count: int = 20) -> list[dict[str, Any]]:
        """Get collector errors formatted for indices panel live stream."""
        with self._lock:
            indices_errors = [
                error for error in self.errors
                if error.destination in (ErrorDestination.INDICES_PANEL, ErrorDestination.BOTH_PANELS)
            ]

            # Format for indices panel consumption
            formatted_errors = []
            for error in indices_errors[-count:]:
                formatted_errors.append({
                    "time": error.timestamp.isoformat(),
                    "index": error.context.get("index", "UNKNOWN"),
                    "status": "ERROR" if error.severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL) else "WARN",
                    "description": f"{error.category.value}: {error.message or str(error.exception)}"[:100],  # Truncate for display
                    "component": error.component,
                    "severity": error.severity.value,
                    "cycle": error.context.get("cycle")
                })

            return formatted_errors

    def get_errors_for_alerts_panel(self, count: int = 50) -> list[dict[str, Any]]:
        """Get non-collector errors formatted for alerts panel."""
        with self._lock:
            alert_errors = [
                error for error in self.errors
                if error.destination in (ErrorDestination.ALERTS_PANEL, ErrorDestination.BOTH_PANELS)
            ]

            # Format for alerts panel consumption
            formatted_errors = []
            for error in alert_errors[-count:]:
                level = "CRITICAL" if error.severity == ErrorSeverity.CRITICAL else (
                    "ERROR" if error.severity == ErrorSeverity.HIGH else (
                        "WARNING" if error.severity == ErrorSeverity.MEDIUM else "INFO"
                    )
                )

                formatted_errors.append({
                    "time": error.timestamp.isoformat(),
                    "level": level,
                    "component": error.component or error.category.value.title(),
                    "message": error.message or str(error.exception),
                    "context": error.context
                })

            return formatted_errors


# Global error handler instance
_global_error_handler: G6ErrorHandler | None = None


def get_error_handler() -> G6ErrorHandler:
    """Get or create the global error handler instance."""
    global _global_error_handler
    if _global_error_handler is None:
        log_file = "logs/g6_errors.log"
        _global_error_handler = G6ErrorHandler(log_file=log_file)
    return _global_error_handler


def initialize_error_handler(log_file: str | None = None, max_errors: int = 1000) -> G6ErrorHandler:
    """Initialize the global error handler with specific configuration."""
    global _global_error_handler
    _global_error_handler = G6ErrorHandler(log_file=log_file, max_errors=max_errors)
    return _global_error_handler


# Type variable for function return types
F = TypeVar('F', bound=Callable[..., Any])


def handle_exceptions(
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    component: str = "",
    message: str = "",
    reraise: bool = False,
    default_return: Any = None,
    log_errors: bool = True
) -> Callable[[F], F]:
    """
    Decorator for automatic exception handling.
    
    Args:
        category: Error category
        severity: Error severity
        component: Component name (auto-detected if not provided)
        message: Custom error message
        reraise: Whether to re-raise exceptions
        default_return: Default return value on error
        log_errors: Whether to log errors
        
    Returns:
        Decorated function with error handling
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def _wrapped(*args: Any, **kwargs: Any):  # returns func result or default
            try:
                return func(*args, **kwargs)
            except Exception as e:  # pragma: no cover - defensive path
                error_handler = get_error_handler()
                comp_name = component or getattr(func, "__module__", "unknown").split('.')[-1]
                func_name = getattr(func, "__name__", "unknown")
                error_handler.handle_error(
                    exception=e,
                    category=category,
                    severity=severity,
                    component=comp_name,
                    function_name=func_name,
                    message=message,
                    context={
                        "args": str(args)[:200],
                        "kwargs": str(kwargs)[:200],
                    },
                    should_log=log_errors,
                    should_reraise=reraise,
                )
                if reraise:
                    raise
                return default_return
        return cast(F, _wrapped)
    return decorator


def safe_execute(
    func: Callable[..., Any],
    *args,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    component: str = "",
    default_return: Any = None,
    **kwargs
) -> Any:
    """
    Execute a function safely with automatic error handling.
    
    Args:
        func: Function to execute
        *args: Function arguments
        category: Error category
        severity: Error severity
        component: Component name
        default_return: Default return value on error
        **kwargs: Function keyword arguments
        
    Returns:
        Function result or default_return on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_handler = get_error_handler()

        comp = component or func.__module__.split('.')[-1] if hasattr(func, '__module__') else "unknown"
        func_name = func.__name__ if hasattr(func, '__name__') else "unknown"

        error_handler.handle_error(
            exception=e,
            category=category,
            severity=severity,
            component=comp,
            function_name=func_name,
            context={
                "args": str(args)[:200],
                "kwargs": str(kwargs)[:200]
            }
        )

        return default_return


# Convenience functions for common error categories
def handle_data_error(e: Exception, component: str = "", context: dict[str, Any] | None = None) -> ErrorInfo:
    """Handle data-related errors."""
    return get_error_handler().handle_error(
        e, ErrorCategory.DATA_VALIDATION, ErrorSeverity.MEDIUM,
        component=component, context=context or {}
    )


def handle_api_error(e: Exception, component: str = "", context: dict[str, Any] | None = None) -> ErrorInfo:
    """Handle general API-related errors (non-collector)."""
    return get_error_handler().handle_error(
        e, ErrorCategory.CONFIGURATION, ErrorSeverity.HIGH,  # Use CONFIGURATION for non-collector API errors
        component=component, context=context or {}
    )


def handle_critical_error(e: Exception, component: str = "", context: dict[str, Any] | None = None) -> ErrorInfo:
    """Handle critical system errors."""
    return get_error_handler().handle_error(
        e, ErrorCategory.CRITICAL, ErrorSeverity.CRITICAL,
        component=component, context=context or {}, should_reraise=False
    )


def handle_ui_error(e: Exception, component: str = "", context: dict[str, Any] | None = None) -> ErrorInfo:
    """Handle UI/rendering errors."""
    return get_error_handler().handle_error(
        e, ErrorCategory.RENDERING, ErrorSeverity.LOW,
        component=component, context=context or {}
    )


def handle_collector_error(
    e: Exception,
    component: str = "",
    index_name: str = "",
    cycle: int | None = None,
    context: dict[str, Any] | None = None
) -> ErrorInfo:
    """Handle collector errors (routed to indices panel)."""
    collector_context = context or {}
    if index_name:
        collector_context["index"] = index_name
    if cycle is not None:
        collector_context["cycle"] = cycle

    return get_error_handler().handle_error(
        e, ErrorCategory.COLLECTOR, ErrorSeverity.HIGH,
        component=component, context=collector_context
    )


def handle_provider_error(
    e: Exception,
    component: str = "",
    index_name: str = "",
    context: dict[str, Any] | None = None
) -> ErrorInfo:
    """Handle provider API errors (routed to indices panel)."""
    provider_context = context or {}
    if index_name:
        provider_context["index"] = index_name

    return get_error_handler().handle_error(
        e, ErrorCategory.PROVIDER_API, ErrorSeverity.HIGH,
        component=component, context=provider_context
    )


def handle_data_collection_error(
    e: Exception,
    component: str = "",
    index_name: str = "",
    data_type: str = "",
    context: dict[str, Any] | None = None
) -> ErrorInfo:
    """Handle data collection errors (routed to indices panel)."""
    collection_context = context or {}
    if index_name:
        collection_context["index"] = index_name
    if data_type:
        collection_context["data_type"] = data_type

    return get_error_handler().handle_error(
        e, ErrorCategory.DATA_COLLECTION, ErrorSeverity.MEDIUM,
        component=component, context=collection_context
    )


if __name__ == "__main__":
    # Example usage and testing
    print("G6 Centralized Error Handling System")
    print("====================================")

    # Initialize error handler
    handler = initialize_error_handler("logs/test_errors.log")

    # Test different error types
    try:
        raise ValueError("Test data validation error")
    except Exception as e:
        handle_data_error(e, "test_component", {"test_data": "sample"})

    try:
        raise ConnectionError("Test API connection error")
    except Exception as e:
        handle_api_error(e, "api_test", {"endpoint": "/test"})

    # Test decorator
    @handle_exceptions(
        category=ErrorCategory.CALCULATION,
        severity=ErrorSeverity.MEDIUM,
        default_return=0
    )
    def test_calculation(x, y):
        return x / y

    result = test_calculation(10, 0)  # Division by zero
    print(f"Safe calculation result: {result}")

    # Print error summary
    summary = handler.get_error_summary()
    print(f"\nError Summary: {summary}")
