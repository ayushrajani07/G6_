#!/usr/bin/env python3
import importlib
import logging
import sys


def test_auto_dump_suppressed(monkeypatch, caplog):
    # Force dump flags that would normally trigger dumps
    monkeypatch.setenv('G6_METRICS_INTROSPECTION_DUMP', 'stdout')
    monkeypatch.setenv('G6_METRICS_INIT_TRACE_DUMP', 'stdout')
    # Suppress auto dumps
    monkeypatch.setenv('G6_METRICS_SUPPRESS_AUTO_DUMPS', '1')
    # Import metrics fresh
    caplog.set_level('INFO')
    # Ensure a fresh metrics module (in case prior tests initialized singleton)
    if 'src.metrics.metrics' in sys.modules:
        importlib.reload(importlib.import_module('src.metrics.metrics'))
    m = importlib.import_module('src.metrics')
    # Bootstrap metrics singleton to trigger init
    reg = m.get_metrics_singleton()
    assert reg is not None
    # Ensure suppression log emitted and no pretty JSON markers present
    logs = "\n".join(f"{r.name}::{r.message}" for r in caplog.records)
    # Match either message or event name presence
    assert 'metrics.dumps.suppressed' in logs
    # The pretty markers would appear if dumps executed
    assert 'METRICS_INTROSPECTION:' not in logs
    assert 'METRICS_INIT_TRACE:' not in logs


def test_auto_dump_not_suppressed(monkeypatch, caplog):
    monkeypatch.delenv('G6_METRICS_SUPPRESS_AUTO_DUMPS', raising=False)
    monkeypatch.setenv('G6_METRICS_INTROSPECTION_DUMP', 'stdout')
    monkeypatch.setenv('G6_METRICS_INIT_TRACE_DUMP', 'stdout')
    # Reload metrics to force re-init path
    if 'src.metrics.metrics' in sys.modules:
        importlib.reload(importlib.import_module('src.metrics.metrics'))
    caplog.set_level('INFO')
    m = importlib.import_module('src.metrics')
    reg = m.get_metrics_singleton()
    assert reg is not None
    logs = "\n".join(r.message for r in caplog.records)
    assert 'METRICS_INTROSPECTION:' in logs or 'METRICS_INIT_TRACE:' in logs
