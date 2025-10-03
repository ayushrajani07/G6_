import pytest, os
from src.metrics import setup_metrics_server  # facade import
from src.metrics.cardinality_manager import get_cardinality_manager


def _force_mode(metrics, mode:int):
    setattr(metrics, '_adaptive_current_mode', mode)


def test_detail_mode_aggregate_blocks_all(monkeypatch):
    monkeypatch.setenv('G6_METRICS_CARD_ENABLED','1')
    metrics,_ = setup_metrics_server(reset=True)
    mgr = get_cardinality_manager()
    mgr.set_metrics(metrics)
    _force_mode(metrics, 2)  # aggregate mode
    # Should reject regardless of strike proximity
    assert mgr.should_emit('NIFTY','2025-09-30',19500,'CE',atm_strike=19500,value=10) is False
    assert mgr.should_emit('NIFTY','2025-09-30',19525,'CE',atm_strike=19500,value=11) is False


def test_detail_mode_band_window(monkeypatch):
    monkeypatch.setenv('G6_METRICS_CARD_ENABLED','1')
    monkeypatch.setenv('G6_DETAIL_MODE_BAND_ATM_WINDOW','2')
    metrics,_ = setup_metrics_server(reset=True)
    mgr = get_cardinality_manager()
    mgr.set_metrics(metrics)
    _force_mode(metrics, 1)  # band mode
    # Within +/-2 allowed
    assert mgr.should_emit('NIFTY','2025-09-30',19500,'CE',atm_strike=19500,value=10) is True
    assert mgr.should_emit('NIFTY','2025-09-30',19501,'CE',atm_strike=19500,value=10.5) is True
    # Outside window (diff 3)
    assert mgr.should_emit('NIFTY','2025-09-30',19503,'CE',atm_strike=19500,value=11) is False


def test_detail_mode_full_no_extra_gating(monkeypatch):
    monkeypatch.setenv('G6_METRICS_CARD_ENABLED','1')
    monkeypatch.setenv('G6_DETAIL_MODE_BAND_ATM_WINDOW','2')
    metrics,_ = setup_metrics_server(reset=True)
    mgr = get_cardinality_manager()
    mgr.set_metrics(metrics)
    _force_mode(metrics, 0)  # full mode
    # All pass (manager internal atm_window default 0; no band gating in full mode)
    assert mgr.should_emit('NIFTY','2025-09-30',19490,'CE',atm_strike=19500,value=9) is True
    assert mgr.should_emit('NIFTY','2025-09-30',19510,'CE',atm_strike=19500,value=9.5) is True
