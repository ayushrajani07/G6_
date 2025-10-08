#!/usr/bin/env python3
"""Deprecation hygiene guard.

Fails (or xfails) if unexpected DeprecationWarnings are emitted during a
minimal representative import & light usage sequence. This keeps the
baseline test run quiet while allowing explicitly whitelisted/intentional
paths (e.g., pipeline flag deprecation) to remain tested elsewhere.

Set G6_DEPRECATION_HYGIENE_VERBOSE=1 for a detailed list of captured warnings.
"""
from __future__ import annotations
import os, warnings, importlib
import pytest

# Whitelisted substrings for messages we intentionally allow HERE (ideally 0)
ALLOWED_SUBSTRINGS: tuple[str, ...] = (
    # (Leave empty; allow explicit per-test whitelisting if needed)
)

@pytest.mark.metrics_no_reset  # avoid costly full metrics reset if such a mark exists
def test_no_unexpected_deprecations(monkeypatch):
    # Force silence of register shim + deep metrics import (handled in other targeted tests)
    monkeypatch.setenv('G6_SUPPRESS_LEGACY_WARNINGS', '1')
    monkeypatch.delenv('G6_PIPELINE_COLLECTOR', raising=False)

    seen: list[warnings.WarningMessage] = []
    def _capture(message, category, filename, lineno, file=None, line=None):  # noqa: ANN001
        if category is DeprecationWarning:
            seen.append(warnings.WarningMessage(message, category, filename, lineno, file, line))
        return _orig_showwarning(message, category, filename, lineno, file=file, line=line)

    _orig_showwarning = warnings.showwarning  # type: ignore
    try:
        warnings.showwarning = _capture  # type: ignore
        # Representative imports / light usage
        import src.metrics  # facade
        from src.metrics import get_metrics_singleton  # noqa: F401
        # Trigger orchestrator mode selection WITHOUT deprecated flag present
        from src.orchestrator import facade as _facade  # noqa: F401
        # Collector settings load (common side effects)
        from src.collector.settings import get_collector_settings  # type: ignore
        get_collector_settings(force_reload=True)
    finally:
        warnings.showwarning = _orig_showwarning  # type: ignore

    unexpected: list[str] = []
    for w in seen:
        msg = str(w.message)
        if any(allow in msg for allow in ALLOWED_SUBSTRINGS):
            continue
        unexpected.append(msg)

    if os.getenv('G6_DEPRECATION_HYGIENE_VERBOSE'):
        print(f"[depr-hygiene] captured={len(seen)} unexpected={len(unexpected)}", flush=True)
        for m in unexpected:
            print(f"[depr-hygiene] unexpected: {m}", flush=True)

    assert not unexpected, f"Unexpected DeprecationWarnings: {unexpected}"  # keep suite green
