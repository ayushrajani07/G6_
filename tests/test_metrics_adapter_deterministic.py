#!/usr/bin/env python3
from __future__ import annotations

import types


class DummyPerf:
    def __init__(self) -> None:
        self.memory_usage_mb = 123.4
        self.cpu_usage_percent = 56.7
        self.api_success_rate = 98.5
        self.api_response_time = 250.0
        self.collection_success_rate = 95.0
        self.options_processed_total = 4321
        self.options_per_minute = 78.9


class DummyIdx:
    def __init__(self, legs: int) -> None:
        self.current_cycle_legs = legs


class DummyPlatform:
    def __init__(self) -> None:
        self.performance = DummyPerf()
        self.indices = {"NIFTY": DummyIdx(10), "BANKNIFTY": DummyIdx(20)}
        self.collection_cycle = 42


def test_metrics_adapter_getters_with_stub(monkeypatch):
    # Stub get_metrics_processor() to return object with required methods
    from src.utils import metrics_adapter as ma_mod

    class DummyProcessor:
        def get_all_metrics(self):
            return DummyPlatform()

        def get_performance_metrics(self):
            return DummyPerf()

        def get_index_metrics(self, index=None):
            return {"NIFTY": DummyIdx(10), "BANKNIFTY": DummyIdx(20)}

    def fake_get_metrics_processor(*args, **kwargs):
        return DummyProcessor()

    # Patch symbol that adapter imports and reset singleton so stub is used
    monkeypatch.setattr(ma_mod, "get_metrics_processor", fake_get_metrics_processor, raising=True)
    # Also patch underlying metrics_processor module, in case anything resolves via it
    import src.summary.metrics_processor as mp_mod
    monkeypatch.setattr(mp_mod, "get_metrics_processor", fake_get_metrics_processor, raising=True)
    # Reset both singletons
    monkeypatch.setattr(ma_mod, "_adapter_singleton", None, raising=True)
    if hasattr(mp_mod, "_metrics_processor"):
        monkeypatch.setattr(mp_mod, "_metrics_processor", None, raising=True)

    # Construct adapter directly to avoid any caching ambiguity
    adapter = ma_mod.MetricsAdapter(prometheus_url="stub://ignored")

    assert adapter.get_cpu_percent() == 56.7
    assert adapter.get_memory_usage_mb() == 123.4
    assert adapter.get_api_success_rate_percent() == 98.5
    assert adapter.get_api_latency_ms() == 250.0
    assert adapter.get_collection_success_rate_percent() == 95.0
    assert adapter.get_options_processed_total() == 4321
    assert adapter.get_options_per_minute() == 78.9
    # 10 + 20
    assert adapter.get_last_cycle_options_sum() == 30
