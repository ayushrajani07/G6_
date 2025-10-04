import types
import pytest

from scripts.summary import app as summary_app

class DummyLoop:
    def __init__(self, *a, **kw):
        pass
    def run(self, cycles=None):  # noqa: D401
        raise RuntimeError("boom")


def test_run_returns_nonzero_on_loop_failure(monkeypatch):
    # Patch UnifiedLoop inside app to our dummy
    monkeypatch.setattr(summary_app, 'UnifiedLoop', DummyLoop, raising=True)
    # Provide minimal argv; --cycles 1 to avoid long loops if logic changes
    rc = summary_app.run(["--cycles", "1", "--no-rich"])  # plain mode path
    assert rc == 1
