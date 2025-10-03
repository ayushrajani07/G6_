import os
import re
from contextlib import contextmanager

from prometheus_client import Counter


class _MiniReg:
    """Minimal stand-in registry exposing only attributes needed by duplicate_guard.

    We avoid importing the full MetricsRegistry to keep background spec/alias duplicates
    from polluting the detection set. The duplicate guard only relies on attribute
    enumeration and underlying collector objects, so this suffices.
    """
    pass


def test_duplicate_metric_detection_basic():
    # Ensure no fail-fast during test
    os.environ.pop('G6_DUPLICATES_FAIL_ON_DETECT', None)
    reg = _MiniReg()
    # Create counter and assign two attribute names referencing same object
    c1 = Counter('g6_test_dup_counter', 'Test counter')
    reg.test_dup_counter = c1  # type: ignore[attr-defined]
    reg.test_dup_counter_alias = c1  # type: ignore[attr-defined]
    from src.metrics.duplicate_guard import check_duplicates
    summary = check_duplicates(reg)
    assert summary is not None, 'Expected duplicate summary'
    assert summary['duplicate_group_count'] == 1
    offenders = summary['duplicates']
    assert len(offenders) == 1
    assert set(offenders[0]['names']) == {'test_dup_counter', 'test_dup_counter_alias'}


def test_duplicate_metric_detection_fail_flag():
    # Activate fail flag and confirm RuntimeError when duplicates present
    os.environ['G6_DUPLICATES_FAIL_ON_DETECT'] = '1'
    try:
        reg = _MiniReg()
        c1 = Counter('g6_test_dup_counter2', 'Test counter2')
        reg.test_dup_counter2 = c1  # type: ignore[attr-defined]
        reg.test_dup_counter2_alias = c1  # type: ignore[attr-defined]
        from src.metrics.duplicate_guard import check_duplicates
        raised = False
        try:
            check_duplicates(reg)
        except RuntimeError:
            raised = True
        assert raised, 'Expected RuntimeError with fail flag set'
    finally:
        os.environ.pop('G6_DUPLICATES_FAIL_ON_DETECT', None)
