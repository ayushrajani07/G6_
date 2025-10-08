#!/usr/bin/env python3
"""Tombstoned (synthetic disable flag removed).

Retained temporarily to preserve ordering and provide a minimal sanity
check that the settings singleton remains stable across reload calls.
Remove after 2025-11-01 if no new immutability coverage introduced.
"""
from src.collector.settings import get_collector_settings

def test_settings_singleton_reload_stable():
    s1 = get_collector_settings(force_reload=True)
    s2 = get_collector_settings()
    # The object should be the same instance (singleton behavior)
    assert s1 is s2
