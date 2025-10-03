#!/usr/bin/env python3
import pytest

from src.metrics import get_metrics  # facade import


def test_expiry_remediation_metrics_registered():
    m = get_metrics()
    # Access attributes; if missing AttributeError will fail test
    assert hasattr(m, 'expiry_quarantined_total')
    assert hasattr(m, 'expiry_rewritten_total')
    assert hasattr(m, 'expiry_rejected_total')
    assert hasattr(m, 'expiry_quarantine_pending')

    # Ensure label sets can be created without raising
    try:
        m.expiry_quarantined_total.labels(index='NIFTY', expiry_code='2025-09-26')  # type: ignore[attr-defined]
        m.expiry_rewritten_total.labels(index='NIFTY', from_code='2025-09-26W', to_code='2025-09-26')  # type: ignore[attr-defined]
        m.expiry_rejected_total.labels(index='NIFTY', expiry_code='2025-09-26')  # type: ignore[attr-defined]
        m.expiry_quarantine_pending.labels(date='2025-09-26').set(0)  # type: ignore[attr-defined]
    except Exception as e:  # pragma: no cover - fail explicitly for visibility
        pytest.fail(f"Failed to use remediation metrics: {e}")
