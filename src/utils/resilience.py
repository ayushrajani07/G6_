#!/usr/bin/env python3
"""
Resilience utilities for G6 Platform.
"""

import functools
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[BaseException], ...] | type[BaseException] = (Exception,)
):
    """
    Retry decorator for handling transient errors.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff_factor: Factor to increase delay by after each attempt
        jitter: Whether to add random jitter to delay
        exceptions: Exceptions to catch and retry on
        
    Returns:
        Decorated function that will retry on specified exceptions
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:  # type: ignore[misc]
                    last_exception = e

                    if attempt < max_attempts - 1:
                        # Calculate delay with optional jitter
                        if jitter:
                            sleep_time = current_delay * (0.5 + random.random())
                        else:
                            sleep_time = current_delay

                        logger.warning(
                            f"Retry {attempt+1}/{max_attempts} for {func.__name__} "
                            f"in {sleep_time:.2f}s: {str(e)}"
                        )

                        time.sleep(sleep_time)
                        current_delay *= backoff_factor
                    else:
                        logger.error(
                            f"Failed after {max_attempts} attempts for {func.__name__}: {str(e)}"
                        )

            # Re-raise the last exception after all retries failed
            if last_exception:
                raise last_exception
            raise RuntimeError("retry: exhausted attempts but no exception captured")

        return wrapper
    return decorator


def fallback(default_value: Any, exceptions: tuple[type[BaseException], ...] | type[BaseException] = (Exception,)):
    """
    Fallback decorator to provide default values on failure.
    
    Args:
        default_value: Value to return if function fails
        exceptions: Exceptions to catch and use default value for
        
    Returns:
        Decorated function that will return default value on specified exceptions
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:  # type: ignore[misc]
                logger.warning(f"Fallback triggered for {func.__name__}: {str(e)}")

                # If default_value is callable, call it with the exception
                if callable(default_value):
                    return default_value(e)

                return default_value

        return wrapper
    return decorator


def timeout(seconds: float):
    """
    Timeout decorator to prevent functions from taking too long.
    
    Note: Uses threading.Timer, not suitable for CPU-bound operations.
    
    Args:
        seconds: Maximum time function is allowed to run
        
    Returns:
        Decorated function that will raise TimeoutError if it takes too long
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import threading

            result = None
            exception = None
            finished = False

            def target():
                nonlocal result, exception, finished
                try:
                    result = func(*args, **kwargs)
                except Exception as e:
                    exception = e
                finally:
                    finished = True

            timer = threading.Timer(seconds, lambda: None)
            thread = threading.Thread(target=target)

            try:
                timer.start()
                thread.start()
                thread.join(seconds + 0.1)  # Small buffer

                if not finished:
                    raise TimeoutError(f"Function {func.__name__} timed out after {seconds} seconds")

                if exception:
                    raise exception

                return result

            finally:
                timer.cancel()

        return wrapper
    return decorator


class HealthCheck:
    """Health check utilities for system components.

    NOTE: Parameter names avoid clashing with decorator function names. Previously the
    parameter `timeout` shadowed the decorator `timeout`, leading to '@timeout(timeout)'
    attempting to call an int and producing 'int object is not callable'.
    """

    @staticmethod
    def check_provider(provider, method_name='get_ltp', args=None, kwargs=None, timeout_seconds=5):
        """
        Check if a provider is responsive.
        
        Args:
            provider: Provider instance to check
            method_name: Method name to call for health check
            args: Arguments to pass to method
            kwargs: Keyword arguments to pass to method
            timeout: Maximum time to wait for response
            
        Returns:
            Dict with health status information
        """
        args = args or []
        kwargs = kwargs or {}

        try:
            if not hasattr(provider, method_name):
                return {
                    'status': 'unhealthy',
                    'message': f"Provider missing method {method_name}"
                }

            method = getattr(provider, method_name)

            # Apply timeout to the call
            @timeout(timeout_seconds)
            def call_method():
                return method(*args, **kwargs)

            result = call_method()

            return {
                'status': 'healthy',
                'message': 'Provider responsive',
                'data': {'result': result}
            }

        except TimeoutError:
            return {
                'status': 'unhealthy',
                'message': f"Provider health check timed out after {timeout_seconds}s"
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f"Provider health check failed: {str(e)}"
            }

    @staticmethod
    def check_storage(storage, method_name='check_health', timeout_seconds=5):
        """
        Check if a storage component is working.
        
        Args:
            storage: Storage instance to check
            method_name: Method name to call for health check
            timeout: Maximum time to wait for response
            
        Returns:
            Dict with health status information
        """
        try:
            if hasattr(storage, method_name):
                # Apply timeout to the call
                @timeout(timeout_seconds)
                def call_method():
                    return getattr(storage, method_name)()

                result = call_method()
                if isinstance(result, dict):
                    return result
                return {
                    'status': 'healthy' if result else 'unhealthy',
                    'message': 'Storage check succeeded' if result else 'Storage check failed'
                }

            # Try basic read/write operation
            test_data = {'test': 'data', 'timestamp': time.time()}

            if hasattr(storage, 'write') and hasattr(storage, 'read'):
                storage.write('healthcheck', test_data)
                read_data = storage.read('healthcheck')

                if read_data and 'test' in read_data and read_data['test'] == 'data':
                    return {
                        'status': 'healthy',
                        'message': 'Storage read/write succeeded'
                    }

            return {
                'status': 'unknown',
                'message': 'No suitable health check method found for storage'
            }

        except TimeoutError:
            return {
                'status': 'unhealthy',
                'message': f"Storage health check timed out after {timeout_seconds}s"
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f"Storage health check failed: {str(e)}"
            }
