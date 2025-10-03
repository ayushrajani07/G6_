#!/usr/bin/env python3
"""Tests for metric group enable/disable environment variable precedence.

Scenarios covered:
 A. Disable only: group listed in G6_DISABLE_METRIC_GROUPS is not registered.
 B. Enable only: only groups listed in G6_ENABLE_METRIC_GROUPS are registered (others absent).
 C. Both with overlap: group present in both enable and disable -> disabled (not registered).
 D. Enable excludes default: enabling a non-existent group yields empty (no failure) and excludes others.

We rely on known metric attributes introduced in tagging: e.g., panel diff group uses 'panel_diff_total' metric attr
and overlay quality group uses 'overlay_quality_rows_total' (adapt to actual attr names present in registry).
To reduce brittleness we probe via registry._metric_groups mapping rather than hardcoding all attr names.
"""
from __future__ import annotations

import importlib, os, sys, subprocess, json, textwrap
import pytest

# Groups intended to be governed by enable/disable gating.
CONTROLLED_GROUPS = {
    'analytics_vol_surface',
    'analytics_risk_agg',
    'panel_diff',
    'parallel',
    'sla_health',
    'overlay_quality',  # future-proof: include if present
    'storage',  # newly gated storage metrics group
}


def run_isolated(env: dict) -> set:
    """Execute a small snippet in a fresh subprocess to build a registry and return groups.

    Using subprocess avoids global default CollectorRegistry collisions across tests.
    """
    code = textwrap.dedent(
        """
        import os, json, sys
        for k,v in %(env)s.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k]=v
        # Import metrics registry lazily after env setup; rely on singleton get_metrics
        if 'src.metrics.metrics' in sys.modules:
            # Ensure fresh import path not polluted (remove then import)
            del sys.modules['src.metrics.metrics']
        # Force a new registry instance for isolation to avoid duplicate registration errors
        os.environ['G6_FORCE_NEW_REGISTRY'] = '1'
        from src.metrics import get_metrics  # facade import
        reg = get_metrics()
        groups = set(getattr(reg, '_metric_groups', {}).values())
        print(json.dumps(sorted(groups)))
        """
    ) % {"env": repr(env)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return set(json.loads(result.stdout.strip() or '[]'))


def test_disable_only(monkeypatch):
    groups = run_isolated({'G6_DISABLE_METRIC_GROUPS': 'analytics_vol_surface'})
    # Disabled controlled group should be absent
    assert 'analytics_vol_surface' not in groups
    # At least one other controlled group (if any exist) should remain
    assert any(g in groups for g in (CONTROLLED_GROUPS - {'analytics_vol_surface'}))


def test_enable_only(monkeypatch):
    enabled = {'panel_diff', 'sla_health'}
    groups = run_isolated({'G6_ENABLE_METRIC_GROUPS': ','.join(enabled)})
    # Intersection with controlled must be subset of enabled set
    controlled_present = {g for g in groups if g in CONTROLLED_GROUPS}
    assert controlled_present.issubset(enabled)
    assert controlled_present  # at least one controlled group registered


def test_overlap_disable_wins(monkeypatch):
    groups = run_isolated({'G6_ENABLE_METRIC_GROUPS':'panel_diff','G6_DISABLE_METRIC_GROUPS':'panel_diff'})
    assert 'panel_diff' not in groups  # disable precedence


def test_enable_nonexistent_excludes_all(monkeypatch):
    groups = run_isolated({'G6_ENABLE_METRIC_GROUPS':'__nonexistent_group__'})
    # No controlled groups should appear since none are enabled
    assert not any(g in CONTROLLED_GROUPS for g in groups)

