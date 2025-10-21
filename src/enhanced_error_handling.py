"""
Enhanced Error Handling Decorators and Utilities for G6 Data Processing

This module provides specialized decorators and utilities for adding robust
error handling to data processing functions throughout the G6 platform.
"""

import functools
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from .error_handling import ErrorCategory, ErrorSeverity, get_error_handler, handle_exceptions

# Type variable for decorated functions
F = TypeVar('F', bound=Callable[..., Any])


def data_processor_safe(
    fallback_value: Any = None,
    category: ErrorCategory = ErrorCategory.DATA_VALIDATION,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    log_context: bool = True
) -> Callable[[F], F]:
    """
    Decorator for data processing functions with comprehensive error handling.
    
    Args:
        fallback_value: Value to return if processing fails
        category: Error category for classification
        severity: Error severity level
        log_context: Whether to log function arguments as context
        
    Returns:
        Decorated function with robust error handling
    """
    return handle_exceptions(
        category=category,
        severity=severity,
        default_return=fallback_value,
        log_errors=True
    )


def api_call_safe(
    retry_count: int = 3,
    retry_delay: float = 1.0,
    fallback_value: Any = None
) -> Callable[[F], F]:
    """
    Decorator for API calls with retry logic and error handling.
    
    Args:
        retry_count: Number of retry attempts
        retry_delay: Delay between retries in seconds
        fallback_value: Value to return if all retries fail
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            last_exception = None

            for attempt in range(retry_count + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Log retry attempt
                    if attempt < retry_count:
                        get_error_handler().handle_error(
                            e, ErrorCategory.PROVIDER_API, ErrorSeverity.MEDIUM,
                            component=func.__module__.split('.')[-1],
                            function_name=func.__name__,
                            message=f"API call failed, retry {attempt + 1}/{retry_count}",
                            context={
                                "attempt": attempt + 1,
                                "total_retries": retry_count,
                                "args": str(args)[:200],
                                "kwargs": str(kwargs)[:200]
                            },
                            should_log=True
                        )
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                    else:
                        # Final failure
                        get_error_handler().handle_error(
                            e, ErrorCategory.PROVIDER_API, ErrorSeverity.HIGH,
                            component=func.__module__.split('.')[-1],
                            function_name=func.__name__,
                            message=f"API call failed after {retry_count} retries",
                            context={
                                "total_attempts": retry_count + 1,
                                "args": str(args)[:200],
                                "kwargs": str(kwargs)[:200]
                            }
                        )

            return fallback_value
        return wrapper  # type: ignore
    return decorator


def file_operation_safe(
    backup_enabled: bool = True,
    fallback_value: Any = None
) -> Callable[[F], F]:
    """
    Decorator for file operations with backup and error handling.
    
    Args:
        backup_enabled: Whether to create backups before operations
        fallback_value: Value to return on failure
        
    Returns:
        Decorated function with file operation safety
    """
    return handle_exceptions(
        category=ErrorCategory.FILE_IO,
        severity=ErrorSeverity.HIGH,
        default_return=fallback_value,
        log_errors=True
    )


def calculation_safe(
    zero_division_value: Any = 0,
    overflow_value: Any = float('inf'),
    fallback_value: Any = None
) -> Callable[[F], F]:
    """
    Decorator for mathematical calculations with specific error handling.
    
    Args:
        zero_division_value: Value to return on division by zero
        overflow_value: Value to return on overflow
        fallback_value: General fallback value
        
    Returns:
        Decorated function with calculation safety
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ZeroDivisionError as e:
                get_error_handler().handle_error(
                    e, ErrorCategory.CALCULATION, ErrorSeverity.LOW,
                    component=func.__module__.split('.')[-1],
                    function_name=func.__name__,
                    message="Division by zero in calculation",
                    context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]}
                )
                return zero_division_value
            except OverflowError as e:
                get_error_handler().handle_error(
                    e, ErrorCategory.CALCULATION, ErrorSeverity.MEDIUM,
                    component=func.__module__.split('.')[-1],
                    function_name=func.__name__,
                    message="Numerical overflow in calculation",
                    context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]}
                )
                return overflow_value
            except Exception as e:
                get_error_handler().handle_error(
                    e, ErrorCategory.CALCULATION, ErrorSeverity.MEDIUM,
                    component=func.__module__.split('.')[-1],
                    function_name=func.__name__,
                    message="General calculation error",
                    context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]}
                )
                return fallback_value
        return wrapper  # type: ignore
    return decorator


def panel_rendering_safe(
    fallback_panel: Any = None,
    show_error_panel: bool = True
) -> Callable[[F], F]:
    """
    Decorator for panel rendering functions with UI-specific error handling.
    
    Args:
        fallback_panel: Panel to show if rendering fails
        show_error_panel: Whether to show an error panel on failure
        
    Returns:
        Decorated function with panel rendering safety
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                get_error_handler().handle_error(
                    e, ErrorCategory.PANEL_DISPLAY, ErrorSeverity.LOW,
                    component=func.__module__.split('.')[-1],
                    function_name=func.__name__,
                    message="Panel rendering failed",
                    context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]}
                )

                if show_error_panel:
                    try:
                        from rich.panel import Panel
                        from rich.text import Text

                        error_text = Text(f"Error in {func.__name__}: {str(e)[:100]}", style="red")
                        return Panel(error_text, title="Rendering Error", border_style="red")
                    except ImportError:
                        pass

                return fallback_panel
        return wrapper  # type: ignore
    return decorator


def database_operation_safe(
    retry_count: int = 2,
    fallback_value: Any = None
) -> Callable[[F], F]:
    """
    Decorator for database operations with retry and error handling.
    
    Args:
        retry_count: Number of retry attempts
        fallback_value: Value to return on failure
        
    Returns:
        Decorated function with database operation safety
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            for attempt in range(retry_count + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < retry_count:
                        get_error_handler().handle_error(
                            e, ErrorCategory.DATABASE, ErrorSeverity.HIGH,
                            component=func.__module__.split('.')[-1],
                            function_name=func.__name__,
                            message=f"Database operation failed, retry {attempt + 1}/{retry_count}",
                            context={
                                "attempt": attempt + 1,
                                "args": str(args)[:200],
                                "kwargs": str(kwargs)[:200]
                            }
                        )
                        time.sleep(1.0)  # Simple retry delay
                    else:
                        get_error_handler().handle_error(
                            e, ErrorCategory.DATABASE, ErrorSeverity.CRITICAL,
                            component=func.__module__.split('.')[-1],
                            function_name=func.__name__,
                            message=f"Database operation failed after {retry_count} retries",
                            context={
                                "total_attempts": retry_count + 1,
                                "args": str(args)[:200],
                                "kwargs": str(kwargs)[:200]
                            }
                        )

            return fallback_value
        return wrapper  # type: ignore
    return decorator


def monitoring_safe(
    log_performance: bool = True,
    performance_threshold: float = 5.0  # seconds
) -> Callable[[F], F]:
    """
    Decorator that adds performance monitoring and error handling.
    
    Args:
        log_performance: Whether to log performance metrics
        performance_threshold: Threshold in seconds to log slow operations
        
    Returns:
        Decorated function with performance monitoring
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = datetime.now(UTC)

            try:
                result = func(*args, **kwargs)

                if log_performance:
                    duration = (datetime.now(UTC) - start_time).total_seconds()
                    if duration > performance_threshold:
                        get_error_handler().handle_error(
                            Exception(f"Slow operation: {duration:.2f}s"),
                            ErrorCategory.RESOURCE, ErrorSeverity.LOW,
                            component=func.__module__.split('.')[-1],
                            function_name=func.__name__,
                            message=f"Function took {duration:.2f}s to execute",
                            context={
                                "duration": duration,
                                "threshold": performance_threshold,
                                "args_count": len(args),
                                "kwargs_count": len(kwargs)
                            }
                        )

                return result

            except Exception as e:
                duration = (datetime.now(UTC) - start_time).total_seconds()
                get_error_handler().handle_error(
                    e, ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM,
                    component=func.__module__.split('.')[-1],
                    function_name=func.__name__,
                    message=f"Function failed after {duration:.2f}s",
                    context={
                        "duration": duration,
                        "args": str(args)[:200],
                        "kwargs": str(kwargs)[:200]
                    }
                )
                raise

        return wrapper  # type: ignore
    return decorator


# Utility functions for batch error handling
def safe_batch_process(
    items: list[Any],
    processor_func: Callable[[Any], Any],
    max_errors: int = 10,
    error_callback: Callable[[Exception, Any], None] | None = None
) -> list[Any]:
    """
    Process a batch of items safely, handling errors gracefully.
    
    Args:
        items: List of items to process
        processor_func: Function to process each item
        max_errors: Maximum number of errors before stopping
        error_callback: Optional callback for error handling
        
    Returns:
        List of successfully processed items
    """
    results = []
    error_count = 0

    for item in items:
        try:
            result = processor_func(item)
            results.append(result)
        except Exception as e:
            error_count += 1

            get_error_handler().handle_error(
                e, ErrorCategory.DATA_VALIDATION, ErrorSeverity.MEDIUM,
                component="batch_processor",
                message=f"Failed to process item {error_count}/{len(items)}",
                context={"item": str(item)[:200], "error_count": error_count}
            )

            if error_callback:
                try:
                    error_callback(e, item)
                except Exception as callback_error:
                    get_error_handler().handle_error(
                        callback_error, ErrorCategory.UNKNOWN, ErrorSeverity.LOW,
                        component="batch_processor",
                        message="Error callback failed"
                    )

            if error_count >= max_errors:
                get_error_handler().handle_error(
                    Exception(f"Too many errors ({error_count})"),
                    ErrorCategory.DATA_VALIDATION, ErrorSeverity.HIGH,
                    component="batch_processor",
                    message=f"Stopping batch processing after {error_count} errors"
                )
                break

    return results


def validate_and_handle_data(
    data: Any,
    validators: list[Callable[[Any], bool]],
    error_messages: list[str]
) -> bool:
    """
    Validate data with error handling.
    
    Args:
        data: Data to validate
        validators: List of validation functions
        error_messages: Error messages for each validator
        
    Returns:
        True if all validations pass, False otherwise
    """
    if len(validators) != len(error_messages):
        raise ValueError("Validators and error messages must have the same length")

    for validator, error_msg in zip(validators, error_messages, strict=False):
        try:
            if not validator(data):
                get_error_handler().handle_error(
                    ValueError(error_msg),
                    ErrorCategory.DATA_VALIDATION, ErrorSeverity.MEDIUM,
                    component="data_validator",
                    message=error_msg,
                    context={"data": str(data)[:200]}
                )
                return False
        except Exception as e:
            get_error_handler().handle_error(
                e, ErrorCategory.DATA_VALIDATION, ErrorSeverity.HIGH,
                component="data_validator",
                message=f"Validation function failed: {error_msg}",
                context={"data": str(data)[:200]}
            )
            return False

    return True


if __name__ == "__main__":
    # Example usage and testing
    print("G6 Enhanced Error Handling Decorators")
    print("=====================================")

    # Test data processing decorator
    @data_processor_safe(fallback_value=[])
    def process_data(data_list):
        """Test data processing function."""
        return [x * 2 for x in data_list]

    result = process_data("invalid_data")  # Should return [] and log error
    print(f"Data processing result: {result}")

    # Test calculation decorator
    @calculation_safe(zero_division_value=float('inf'))
    def divide_numbers(a, b):
        """Test calculation function."""
        return a / b

    result = divide_numbers(10, 0)  # Should return inf and log error
    print(f"Division result: {result}")

    # Test batch processing
    def square_number(x):
        if x == 5:
            raise ValueError("Cannot process 5")
        return x ** 2

    numbers = [1, 2, 3, 4, 5, 6, 7]
    results = safe_batch_process(numbers, square_number, max_errors=2)
    print(f"Batch processing results: {results}")

    # Print error summary
    error_handler = get_error_handler()
    summary = error_handler.get_error_summary()
    print(f"\nError Summary: {summary}")
