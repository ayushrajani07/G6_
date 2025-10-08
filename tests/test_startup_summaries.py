#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for provider and metrics one-shot startup summaries."""
import logging
from io import StringIO
import os

def test_kite_provider_summary_once(monkeypatch):
    monkeypatch.setenv('G6_PROVIDER_SUMMARY_HUMAN','1')
    # Reset sentinel
    import src.broker.kite_provider as kp
    try:
        from src.broker.kite.startup_summary import _reset_provider_summary_state  # type: ignore
        _reset_provider_summary_state()
    except Exception:
        if '_KITE_PROVIDER_SUMMARY_EMITTED' in kp.__dict__:
            del kp.__dict__['_KITE_PROVIDER_SUMMARY_EMITTED']
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger('src.broker.kite_provider')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    kp.KiteProvider(api_key=None, access_token=None)
    kp.KiteProvider(api_key=None, access_token=None)  # second should not emit summary
    handler.flush()
    out = stream.getvalue()
    assert 'provider.kite.summary' in out
    assert out.count('provider.kite.summary') == 1
    assert 'KITE PROVIDER SUMMARY' in out.upper()
    logger.removeHandler(handler)


def test_metrics_registry_summary_once(monkeypatch):
    monkeypatch.setenv('G6_METRICS_SUMMARY_HUMAN','1')
    # Reset sentinel
    # Use facade + helper instead of deprecated deep import
    from src.metrics import MetricsRegistry, _reset_metrics_summary_state  # type: ignore
    _reset_metrics_summary_state()
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger('src.metrics.metrics')  # underlying module logger still targeted
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    MetricsRegistry()
    MetricsRegistry()  # second instantiation
    handler.flush()
    out = stream.getvalue()
    assert 'metrics.registry.summary' in out
    assert out.count('metrics.registry.summary') == 1
    assert 'METRICS REGISTRY SUMMARY' in out.upper()
    logger.removeHandler(handler)
