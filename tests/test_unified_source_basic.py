from __future__ import annotations

from typing import Any, Dict

import pytest

from src.data_access.unified_source import UnifiedDataSource, DataSourceConfig, data_source


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch):
    # reset env flags that could affect order
    monkeypatch.delenv("G6_FORCE_DATA_SOURCE", raising=False)
    monkeypatch.delenv("G6_DISABLE_METRICS_SOURCE", raising=False)
    # Ensure cache is clean between tests
    data_source.invalidate_cache()
    yield
    data_source.invalidate_cache()


def test_indices_normalization_from_metrics_list(monkeypatch: pytest.MonkeyPatch):
    # Mock metrics to return list-form indices
    def _mock_read_metrics(self: UnifiedDataSource) -> Dict[str, Any]:
        return {
            "indices": [
                {"index": "NIFTY", "legs": 10},
                {"idx": "BANKNIFTY", "legs": 20},
                {"legs": 5},  # ignored (missing key)
            ]
        }

    monkeypatch.setattr(UnifiedDataSource, "_read_metrics", _mock_read_metrics, raising=True)
    # Force metrics to be preferred
    monkeypatch.setenv("G6_FORCE_DATA_SOURCE", "metrics")
    cfg = DataSourceConfig()
    data_source.reconfigure(cfg)

    out = data_source.get_indices_data()
    assert set(out.keys()) == {"NIFTY", "BANKNIFTY"}
    assert out["NIFTY"]["legs"] == 10


def test_indices_passthrough_from_metrics_dict(monkeypatch: pytest.MonkeyPatch):
    def _mock_read_metrics(self: UnifiedDataSource) -> Dict[str, Any]:
        return {"indices": {"FINNIFTY": {"legs": 7}}}

    monkeypatch.setattr(UnifiedDataSource, "_read_metrics", _mock_read_metrics, raising=True)
    monkeypatch.setenv("G6_FORCE_DATA_SOURCE", "metrics")
    cfg = DataSourceConfig()
    data_source.reconfigure(cfg)

    out = data_source.get_indices_data()
    assert out == {"FINNIFTY": {"legs": 7}}


def test_force_and_disable_flags(monkeypatch: pytest.MonkeyPatch):
    # Disable metrics; force runtime_status
    monkeypatch.setenv("G6_DISABLE_METRICS_SOURCE", "1")
    monkeypatch.setenv("G6_FORCE_DATA_SOURCE", "runtime_status")
    cfg = DataSourceConfig()
    order = list(cfg.source_order)
    assert order[0] == "runtime_status"
    assert "metrics" not in order


def test_cache_invalidation_runtime_status(monkeypatch: pytest.MonkeyPatch):
    # Provide two different status payloads to observe invalidation
    payloads = [
        {"loop": {"cycle": 1}},
        {"loop": {"cycle": 2}},
    ]
    state = {"i": 0}

    def _mock_read_status(self: UnifiedDataSource) -> Dict[str, Any]:
        return payloads[state["i"]]

    monkeypatch.setattr(UnifiedDataSource, "_read_status", _mock_read_status, raising=True)
    # Reset config to default; ensure short TTL is not relied upon (use explicit invalidation)
    data_source.reconfigure(DataSourceConfig())

    first = data_source.get_runtime_status()
    assert first.get("loop", {}).get("cycle") == 1

    # Change underlying payload, but cache still holds previous value
    state["i"] = 1
    cached = data_source.get_runtime_status()
    assert cached.get("loop", {}).get("cycle") == 1

    # Invalidate and re-read
    data_source.invalidate_cache("runtime_status")
    updated = data_source.get_runtime_status()
    assert updated.get("loop", {}).get("cycle") == 2
