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
    # Suppression log must be present
    assert 'metrics.dumps.suppressed' in logs
    # We now emit zero-value marker lines even when suppressed; ensure they reflect zero
    if 'METRICS_INTROSPECTION:' in logs:
        for line in logs.splitlines():
            if 'METRICS_INTROSPECTION:' in line:
                assert line.rstrip().endswith('0'), f"Expected zero introspection count on suppression, got: {line}"
    if 'METRICS_INIT_TRACE:' in logs:
        for line in logs.splitlines():
            if 'METRICS_INIT_TRACE:' in line:
                assert '0 steps' in line, f"Expected zero init trace steps on suppression, got: {line}"


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
