import os
import importlib
import pytest

from src.utils.circuit_registry import circuit_protected, get_breaker, _REGISTRY
from src.utils.adaptive_circuit_breaker import CircuitState, CircuitOpenError
from src.utils.retry import retryable


class FailingStub:
    def __init__(self, fail_times_before_success: int | None = None):
        self.fail_times_before_success = fail_times_before_success
        self.calls = 0

    def get_quote(self, instruments):
        self.calls += 1
        # Always fail when None
        if self.fail_times_before_success is None:
            raise TimeoutError("simulated transient failure")
        # Fail N times, then succeed
        if self.calls <= self.fail_times_before_success:
            raise TimeoutError(f"simulated failure #{self.calls}")
        return {i: {"ltp": 123.45} for i in instruments}


@pytest.fixture(autouse=True)
def _isolate_env_and_registry(monkeypatch):
    # Ensure health updates don't crash tests even if enabled
    monkeypatch.setenv("G6_HEALTH_COMPONENTS", "on")
    # Start with a clean breaker registry per test
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def _compose_wrapped(method, name: str):
    # Compose retries inside breaker, like unified_main.apply_circuit_breakers
    inner = retryable(method)
    wrapped = circuit_protected(name)(inner)
    return wrapped


def test_cb_retry_success_avoids_trip(monkeypatch):
    # Configure retries to allow recovery within a single call
    monkeypatch.setenv("G6_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("G6_RETRY_MAX_SECONDS", "2")
    # Keep breaker threshold high so it doesn't trip on transient attempt failures
    monkeypatch.setenv("G6_CB_FAILURES", "5")

    name = "test.provider.q.success"
    stub = FailingStub(fail_times_before_success=2)
    wrapped = _compose_wrapped(stub.get_quote, name)

    res = wrapped(["X1", "X2"])  # should succeed after internal retries
    assert isinstance(res, dict) and "X1" in res

    br = get_breaker(name)
    assert br.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


def test_cb_opens_on_persistent_failure(monkeypatch):
    # Trip breaker quickly: one failed call increments failures by 1
    monkeypatch.setenv("G6_CB_FAILURES", "2")
    monkeypatch.setenv("G6_CB_MIN_RESET", "1")
    monkeypatch.setenv("G6_CB_MAX_RESET", "2")

    # Keep retries minimal so each wrapped call reports one failure to breaker
    monkeypatch.setenv("G6_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("G6_RETRY_MAX_SECONDS", "1")

    name = "test.provider.q.fail"
    stub = FailingStub(fail_times_before_success=None)  # always fail
    wrapped = _compose_wrapped(stub.get_quote, name)

    # First call fails (breaker failures=1)
    with pytest.raises(TimeoutError):
        wrapped(["A"])  # inner has 0 retries beyond the initial attempt

    # Second call fails and should trip the breaker (failures=2 -> OPEN)
    with pytest.raises(TimeoutError):
        wrapped(["B"])  # still allowed, but records another failure and opens

    br = get_breaker(name)
    assert br.state == CircuitState.OPEN

    # Third call should be blocked immediately by the breaker
    with pytest.raises(CircuitOpenError):
        wrapped(["C"])  # blocked by OPEN circuit
