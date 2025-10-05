"""Smoke tests that key optional modules still import and expose expected symbols.

Previously these were pure dynamic import probes (flagged as orphans: no asserts/marks).
Added minimal attribute assertions so failures surface meaningfully and orphan
heuristic no longer flags them.
"""
import importlib


def test_import_plot_weekday_overlays():
    mod = importlib.import_module('scripts.plot_weekday_overlays')
    # Main entrypoint should exist for CLI usage
    assert hasattr(mod, 'main'), "plot_weekday_overlays.main missing"


def test_import_redis_cache():
    mod = importlib.import_module('src.analytics.redis_cache')
    # RedisCache class should be present even if redis optional dependency missing
    assert hasattr(mod, 'RedisCache'), "RedisCache symbol missing"

