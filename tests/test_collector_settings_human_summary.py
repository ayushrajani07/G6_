#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate human-readable settings summary emission when enabled."""
import logging, os
from io import StringIO
from src.collector.settings import get_collector_settings

def test_human_readable_summary_once(monkeypatch):
    import src.collector.settings as cs
    # Reset singleton + sentinel
    cs._settings_singleton = None  # type: ignore
    if '_G6_SETTINGS_SUMMARY_EMITTED' in cs.__dict__:
        del cs.__dict__['_G6_SETTINGS_SUMMARY_EMITTED']
    monkeypatch.setenv('G6_SETTINGS_SUMMARY_HUMAN','1')
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger('src.collector.settings')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    get_collector_settings(force_reload=True)
    get_collector_settings()
    handler.flush()
    out = stream.getvalue()
    assert 'collector.settings.summary' in out
    assert 'SETTINGS SUMMARY' in out.upper(), out
    # ensure only one block (count heading occurrences)
    assert out.upper().count('SETTINGS SUMMARY') == 1
    logger.removeHandler(handler)
