"""Pytest configuration & plugin hooks for G6.

Responsibilities:
1. Ensure project root on sys.path.
2. Marker gatekeeping via environment variables:
   - optional tests require G6_ENABLE_OPTIONAL_TESTS=1
   - slow tests require G6_ENABLE_SLOW_TESTS=1
3. Provide fixtures for mock provider runs.
"""
from __future__ import annotations
import os
import sys
import json
import time
from pathlib import Path
from typing import Iterator, Callable
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def pytest_collection_modifyitems(config, items):  # pragma: no cover (collection phase)
    enable_optional = os.environ.get('G6_ENABLE_OPTIONAL_TESTS','') in ('1','true','yes','on')
    enable_slow = os.environ.get('G6_ENABLE_SLOW_TESTS','') in ('1','true','yes','on')
    skip_optional = pytest.mark.skip(reason="Set G6_ENABLE_OPTIONAL_TESTS=1 to run optional tests")
    skip_slow = pytest.mark.skip(reason="Set G6_ENABLE_SLOW_TESTS=1 to run slow tests")
    for item in items:
        if 'optional' in item.keywords and not enable_optional:
            item.add_marker(skip_optional)
        if 'slow' in item.keywords and not enable_slow:
            item.add_marker(skip_slow)

@pytest.fixture(scope='session')
def mock_status_file(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp('mock_status') / 'status.json'
    return p

@pytest.fixture
def run_mock_cycle(monkeypatch, mock_status_file) -> Callable[[int, int], dict]:
    """Run unified_main for up to N cycles in mock mode returning final status JSON.

    Uses environment variable `G6_MAX_CYCLES` to let unified_main loop internally,
    avoiding repeated process-level run-once resets so cycle counter progresses.
    """
    from src.unified_main import main as unified_main  # import here after path setup
    def _runner(cycles: int = 1, interval: int = 3) -> dict:
        """Invoke unified_main in mock mode for a bounded number of cycles.

        Parameters:
            cycles: Maximum cycles to allow unified_main to run.
            interval: Sleep interval (seconds) between cycles.
        Returns:
            Parsed runtime status JSON (empty dict if file absent).
        """
        monkeypatch.setenv('G6_USE_MOCK_PROVIDER','1')
        monkeypatch.setenv('G6_FORCE_UNICODE','1')
        monkeypatch.setenv('G6_FANCY_CONSOLE','1')
        monkeypatch.setenv('G6_MAX_CYCLES', str(cycles))
        # Skip provider readiness probe to reduce startup latency in tests
        monkeypatch.setenv('G6_SKIP_PROVIDER_READINESS','1')
        argv = [
            'unified_main',
            '--config','config/g6_config.json',
            '--mock-data',
            '--interval', str(interval),
            '--runtime-status-file', str(mock_status_file),
            '--metrics-custom-registry',
            '--metrics-reset',
        ]
        old = sys.argv
        try:
            sys.argv = argv
            rc = unified_main()
            assert rc in (0, None)
        finally:
            sys.argv = old
        data = json.loads(mock_status_file.read_text()) if mock_status_file.exists() else {}
        return data
    return _runner

@pytest.fixture
def metrics_isolated():
    """Isolate Prometheus global registry during a test.

    Provides a safety net for any test that directly initializes metrics
    without passing --metrics-custom-registry/--metrics-reset flags on CLI.
    Not yet wired into existing tests (they already reset), but available
    for future granular metrics unit tests.
    """
    from src.metrics.metrics import isolated_metrics_registry
    with isolated_metrics_registry():
        yield