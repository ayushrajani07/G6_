from __future__ import annotations

"""Regression tests for duplicate metric suppression logic.

Ensures benign alias families (legacy_*, *_total, *_alias, *_total_total) are
suppressed while true accidental duplicates are still detected.
"""
import os

from src.metrics.testing import force_new_metrics_registry
from src.metrics.duplicate_guard import check_duplicates


def _fresh_registry():
    os.environ['G6_METRICS_SKIP_PROVIDER_MODE_SEED'] = '1'
    return force_new_metrics_registry(enable_resource_sampler=False)


def test_duplicate_guard_suppresses_alias_families():
    reg = _fresh_registry()
    names = [n for n in dir(reg) if 'panel_diff_bytes' in n]
    assert names  # basic sanity that family exists in this environment
    summary = check_duplicates(reg)
    assert summary is None, f"Expected no duplicate groups, got: {summary}"


def test_duplicate_guard_detects_real_duplicates():
    reg = _fresh_registry()
    from prometheus_client import Counter  # type: ignore
    # Create a unique counter and bind under two unrelated attribute names that are NOT part of suppression patterns
    c = Counter('g6_test_duplicate_counter_xyz', 'Synthetic duplicate counter for test')
    reg.test_duplicate_counter_primary = c  # type: ignore[attr-defined]
    reg.test_duplicate_counter_shadow = c  # type: ignore[attr-defined]
    summary = check_duplicates(reg)
    assert summary is not None, "Expected duplicate summary for synthetic collision"
    namesets = [set(d['names']) for d in summary['duplicates']]
    assert any({'test_duplicate_counter_primary', 'test_duplicate_counter_shadow'} <= s for s in namesets), summary


if __name__ == '__main__':  # pragma: no cover
    r = _fresh_registry()
    print('Manual suppress summary ->', check_duplicates(r))
    r2 = _fresh_registry()
    from prometheus_client import Counter  # type: ignore
    dup = Counter('g6_test_duplicate_counter2_xyz', 'Doc')
    r2.alpha = dup  # type: ignore[attr-defined]
    r2.beta = dup   # type: ignore[attr-defined]
    print('Manual real dup summary ->', check_duplicates(r2))
