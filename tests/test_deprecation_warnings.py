import os, runpy, sys
from pathlib import Path

# We validate that deprecation warnings/messages reference DEPRECATIONS.md
# and that removed legacy modules emit proper migration guidance (run_live removed).
# (unless suppressed env flags are set).

def test_removed_unified_main_import(monkeypatch):
    # Import should raise RuntimeError now
    try:
        import src.unified_main  # type: ignore  # noqa: F401
    except RuntimeError as e:
        assert 'removed' in str(e).lower() and 'orchestrator' in str(e).lower()
    else:  # pragma: no cover
        raise AssertionError('Importing src.unified_main should raise after removal')


def test_run_live_removed(monkeypatch):
    assert not (Path('scripts') / 'run_live.py').exists(), 'run_live.py should be removed'
