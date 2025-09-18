import os
from scripts.summary.app import compute_cadence_defaults


def test_default_15s(monkeypatch):
    monkeypatch.delenv("G6_SUMMARY_REFRESH_SEC", raising=False)
    monkeypatch.delenv("G6_SUMMARY_META_REFRESH_SEC", raising=False)
    monkeypatch.delenv("G6_SUMMARY_RES_REFRESH_SEC", raising=False)
    cad = compute_cadence_defaults()
    assert cad["meta"] == 15.0
    assert cad["res"] == 15.0


def test_unified_overrides_both(monkeypatch):
    monkeypatch.setenv("G6_SUMMARY_REFRESH_SEC", "5")
    monkeypatch.delenv("G6_SUMMARY_META_REFRESH_SEC", raising=False)
    monkeypatch.delenv("G6_SUMMARY_RES_REFRESH_SEC", raising=False)
    cad = compute_cadence_defaults()
    assert cad["meta"] == 5.0
    assert cad["res"] == 5.0


def test_per_knob_override(monkeypatch):
    monkeypatch.setenv("G6_SUMMARY_REFRESH_SEC", "10")
    monkeypatch.setenv("G6_SUMMARY_META_REFRESH_SEC", "7")
    monkeypatch.setenv("G6_SUMMARY_RES_REFRESH_SEC", "12")
    cad = compute_cadence_defaults()
    assert cad["meta"] == 7.0
    assert cad["res"] == 12.0


def test_invalid_unified_uses_default(monkeypatch):
    monkeypatch.setenv("G6_SUMMARY_REFRESH_SEC", "not-a-number")
    monkeypatch.delenv("G6_SUMMARY_META_REFRESH_SEC", raising=False)
    monkeypatch.delenv("G6_SUMMARY_RES_REFRESH_SEC", raising=False)
    cad = compute_cadence_defaults()
    assert cad["meta"] == 15.0
    assert cad["res"] == 15.0
