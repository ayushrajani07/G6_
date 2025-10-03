import logging
import os
from io import StringIO


def _capture_logs(func):
    """Utility to capture WARNING logs for the duration of func."""
    logger = logging.getLogger('src.broker.kite.tracing')
    prev_level = logger.level
    logger.setLevel(logging.WARNING)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        func()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
    return stream.getvalue()


def test_tracing_disabled_by_default(monkeypatch):
    # Ensure env vars not set
    monkeypatch.delenv('G6_TRACE_COLLECTOR', raising=False)
    monkeypatch.delenv('G6_QUIET_MODE', raising=False)
    monkeypatch.delenv('G6_QUIET_ALLOW_TRACE', raising=False)
    from importlib import reload
    import src.broker.kite.tracing as tracing
    reload(tracing)  # re-read env

    def _emit():
        tracing.trace('unit_test_event', foo=1)

    out = _capture_logs(_emit)
    assert 'TRACE unit_test_event' not in out


def test_tracing_enabled(monkeypatch):
    monkeypatch.setenv('G6_TRACE_COLLECTOR', '1')
    from importlib import reload
    import src.broker.kite.tracing as tracing
    reload(tracing)

    def _emit():
        tracing.trace('unit_test_event', bar=2)

    out = _capture_logs(_emit)
    assert 'TRACE unit_test_event' in out
    assert 'bar' in out


def test_tracing_quiet_mode_block(monkeypatch):
    monkeypatch.setenv('G6_TRACE_COLLECTOR', '1')
    monkeypatch.setenv('G6_QUIET_MODE', '1')
    monkeypatch.delenv('G6_QUIET_ALLOW_TRACE', raising=False)
    from importlib import reload
    import src.broker.kite.tracing as tracing
    reload(tracing)

    def _emit():
        tracing.trace('unit_test_event', baz=3)

    out = _capture_logs(_emit)
    assert 'TRACE unit_test_event' not in out


def test_tracing_quiet_allow_override(monkeypatch):
    monkeypatch.setenv('G6_TRACE_COLLECTOR', '1')
    monkeypatch.setenv('G6_QUIET_MODE', '1')
    monkeypatch.setenv('G6_QUIET_ALLOW_TRACE', '1')
    from importlib import reload
    import src.broker.kite.tracing as tracing
    reload(tracing)

    def _emit():
        tracing.trace('unit_test_event', qux=4)

    out = _capture_logs(_emit)
    assert 'TRACE unit_test_event' in out
    assert 'qux' in out


def test_tracing_runtime_disable(monkeypatch):
    monkeypatch.setenv('G6_TRACE_COLLECTOR', '1')
    from importlib import reload
    import src.broker.kite.tracing as tracing
    reload(tracing)
    tracing.set_enabled(False)

    def _emit():
        tracing.trace('unit_test_event', off=5)

    out = _capture_logs(_emit)
    assert 'TRACE unit_test_event' not in out
