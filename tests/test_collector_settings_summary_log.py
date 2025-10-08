#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test that settings summary log is emitted only once per process."""
import logging
from io import StringIO
from src.collector.settings import get_collector_settings

def test_settings_summary_one_shot(monkeypatch):
    # Reset singleton & guard globals
    import src.collector.settings as cs
    cs._settings_singleton = None  # type: ignore
    if '_G6_SETTINGS_SUMMARY_EMITTED' in cs.__dict__:
        del cs.__dict__['_G6_SETTINGS_SUMMARY_EMITTED']
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger('src.collector.settings')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # First load should emit summary
    get_collector_settings(force_reload=True)
    # Second load should not emit
    get_collector_settings()
    handler.flush()
    output = stream.getvalue().splitlines()
    summary_lines = [l for l in output if 'collector.settings.summary' in l]
    assert len(summary_lines) == 1, f"Expected 1 summary line, got {len(summary_lines)}: {output}"
    logger.removeHandler(handler)
