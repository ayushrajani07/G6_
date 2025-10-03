import os
import pytest

from src.metrics import MetricsRegistry  # import via facade


def make_registry():
    return MetricsRegistry()


def test_governance_summary_basic(monkeypatch):
    # Ensure env flags for guards are off to test None paths (fault budget disabled by default)
    for k in list(os.environ.keys()):
        if k.startswith('G6_FAULT_BUDGET_'):
            monkeypatch.delenv(k, raising=False)
        if k.startswith('G6_DUPLICATES_'):
            monkeypatch.delenv(k, raising=False)
        if k.startswith('G6_CARDINALITY_'):
            monkeypatch.delenv(k, raising=False)
    reg = make_registry()
    summary = reg.governance_summary()
    assert set(summary.keys()) == {"duplicates","cardinality","fault_budget"}
    assert summary['fault_budget'] is None  # disabled
    # If duplicates summary present, validate minimal keys
    if summary['duplicates'] is not None:
        assert 'duplicate_group_count' in summary['duplicates']
    if summary['cardinality'] is not None:
        # Cardinality guard summary shapes vary; ensure at least one expected key
        card_keys = summary['cardinality'].keys()
        assert any(k in card_keys for k in ('baseline','current','growth','estimated_series','action'))


def test_governance_summary_fault_budget_enabled(monkeypatch):
    monkeypatch.setenv('G6_FAULT_BUDGET_ENABLE','1')
    monkeypatch.setenv('G6_FAULT_BUDGET_ALLOWED_BREACHES','5')
    monkeypatch.setenv('G6_FAULT_BUDGET_WINDOW_SEC','30')
    reg = make_registry()
    # Simulate some breaches by manipulating counter if present and invoking mark_cycle
    breach_counter = getattr(reg, 'cycle_sla_breach', None)
    if breach_counter is not None:
        try:
            breach_counter.inc()  # type: ignore[attr-defined]
        except Exception:
            pass
    reg.mark_cycle(success=True, cycle_seconds=0.01, options_processed=0, option_processing_seconds=0.0)
    summary = reg.governance_summary()
    fb = summary['fault_budget']
    assert fb is not None
    assert fb['allowed'] == 5
    assert float(fb['window_sec']) == 30.0
    assert 0 <= fb['consumed_percent'] <= 100
    assert fb['within'] >= 0

