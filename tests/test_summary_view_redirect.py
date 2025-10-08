"""Ensure legacy summary_view.main delegates to unified app.run.

We monkeypatch scripts.summary.app.run to capture invocation and args.
"""
from __future__ import annotations

import types


def test_summary_view_main_delegates(monkeypatch):
    called = {}
    def fake_run(argv):  # noqa: D401
        called['args'] = list(argv) if argv else []
        return 0
    import scripts.summary.app as app_mod
    monkeypatch.setattr(app_mod, 'run', fake_run)
    import pytest
    # The legacy scripts.summary_view emits a deprecation warning when imported.
    with pytest.deprecated_call():
        import scripts.summary_view as sv  # noqa: F401
        rc = sv.main(['--no-rich','--cycles','1'])
    assert rc == 0
    assert called.get('args') == ['--no-rich','--cycles','1']
