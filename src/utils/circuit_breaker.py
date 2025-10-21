#!/usr/bin/env python3
"""
Circuit breaker pattern implementation for G6 Platform.
"""

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)
try:
    # Late import to avoid heavy deps and circulars in early boot
    from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler  # type: ignore
except Exception:  # pragma: no cover - fallback when error system unavailable
    get_error_handler = None  # type: ignore
    ErrorCategory = None  # type: ignore
    ErrorSeverity = None  # type: ignore

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = 0  # Normal operation, calls allowed
    OPEN = 1    # Circuit is open, calls not allowed
    HALF_OPEN = 2  # Testing if service is back online


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents repeated calls to failing services and allows
    time for recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: int = 60,
        half_open_limit: int = 1
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Circuit breaker name for logging
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Seconds before testing service again
            half_open_limit: Number of test calls allowed when half-open
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_limit = half_open_limit

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.half_open_calls = 0

        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)

    def __call__(self, func):
        """
        Decorate a function with circuit breaker protection.
        
        Args:
            func: Function to protect
            
        Returns:
            Decorated function
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Call a function with circuit breaker protection.
        
        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function return value
            
        Raises:
            Exception: If circuit is open or call fails
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.reset_timeout:
                    self.logger.info(f"Circuit {self.name} half-opening after timeout")
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is open")

            if self.state == CircuitState.HALF_OPEN and self.half_open_calls >= self.half_open_limit:
                raise CircuitOpenError(f"Circuit {self.name} is half-open and at call limit")

            if self.state == CircuitState.HALF_OPEN:
                self.half_open_calls += 1

        try:
            result = func(*args, **kwargs)

            # Call succeeded, close circuit if it was half-open
            with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.logger.info(f"Circuit {self.name} closing after successful half-open call")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.half_open_calls = 0
                elif self.state == CircuitState.CLOSED and self.failure_count > 0:
                    # Reduce failure count on success in closed state
                    self.failure_count = max(0, self.failure_count - 1)

            return result

        except Exception as e:
            with self._lock:
                self.last_failure_time = time.time()

                if self.state == CircuitState.HALF_OPEN:
                    self.logger.warning(f"Circuit {self.name} reopening after failed half-open call: {e}")
                    try:
                        if get_error_handler and ErrorCategory and ErrorSeverity:
                            get_error_handler().handle_error(
                                exception=e,
                                category=ErrorCategory.RESOURCE,
                                severity=ErrorSeverity.MEDIUM,
                                component="utils.circuit_breaker",
                                function_name="call",
                                message="Half-open probe failed; reopening circuit",
                                context={"circuit": self.name, "state": self.state.name},
                                should_log=False,
                                should_reraise=False,
                            )
                    except Exception:
                        pass
                    self.state = CircuitState.OPEN
                elif self.state == CircuitState.CLOSED:
                    self.failure_count += 1
                    if self.failure_count >= self.failure_threshold:
                        self.logger.warning(f"Circuit {self.name} opening after {self.failure_count} failures")
                        try:
                            if get_error_handler and ErrorCategory and ErrorSeverity:
                                get_error_handler().handle_error(
                                    exception=e,
                                    category=ErrorCategory.RESOURCE,
                                    severity=ErrorSeverity.MEDIUM,
                                    component="utils.circuit_breaker",
                                    function_name="call",
                                    message="Circuit opening after consecutive failures",
                                    context={"circuit": self.name, "failures": self.failure_count},
                                    should_log=False,
                                    should_reraise=False,
                                )
                        except Exception:
                            pass
                        self.state = CircuitState.OPEN

            raise


class CircuitOpenError(Exception):
    """Exception raised when circuit is open."""
    pass


# Example usage
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Create a circuit breaker
    breaker = CircuitBreaker("example", failure_threshold=3, reset_timeout=5)

    # Example function to protect
    @breaker
    def api_call(should_fail=False):
        if should_fail:
            raise ValueError("API call failed")
        return "API call succeeded"

    # Test circuit breaker
    try:
        for i in range(5):
            try:
                result = api_call(should_fail=True)
                print(f"Call {i}: {result}")
            except Exception as e:
                print(f"Call {i} failed: {e}")

        print("Waiting for circuit to half-open...")
        time.sleep(6)

        try:
            result = api_call(should_fail=False)
            print(f"After wait: {result}")
        except Exception as e:
            print(f"After wait failed: {e}")

    except KeyboardInterrupt:
        pass
