import os
import types

from src.orchestrator.context import RuntimeContext
from src.orchestrator.cycle import run_cycle


class DummyProviders:
    def __init__(self):
        self.calls = []

    def get_index_data(self, index):
        self.calls.append(("get_index_data", index))
        return 100, {"o":100,"h":101,"l":99,"c":100}

    def get_atm_strike(self, index):
        return 100

    def resolve_expiry(self, index, rule):
        self.calls.append(("resolve_expiry", index, rule))
        return "2025-12-31"

    def get_option_instruments(self, index, expiry, strikes):
        self.calls.append(("get_option_instruments", index, len(strikes)))
        return [f"{index}_{s}" for s in strikes[:3]]

    def enrich_with_quotes(self, instruments):
        self.calls.append(("enrich_with_quotes", len(instruments)))
        return {inst: {"last_price": 1.0} for inst in instruments}

    def get_expiry_dates(self, index):  # used for allowed_expiry_dates
        return ["2025-12-31"]


class DummyMetrics:
    def __init__(self):
        class _Gauge:
            def set(self, v):
                pass
            def labels(self, **_):
                return self
        class _Counter(_Gauge):
            def inc(self, *_a, **_k):
                pass
        self.parallel_index_workers = _Gauge()
        self.parallel_index_failures = _Counter()
        self.index_price = _Gauge()
        self.index_atm = _Gauge()
        def mark_api_call(**_):
            pass
        self.mark_api_call = mark_api_call


def test_parallel_cycle_execution(monkeypatch):
    os.environ["G6_PARALLEL_INDICES"] = "1"
    os.environ["G6_PARALLEL_INDEX_WORKERS"] = "2"
    # Force market open so unified_collectors does not early-exit (which would prevent provider calls)
    os.environ["G6_FORCE_MARKET_OPEN"] = "1"
    ctx = RuntimeContext(config={"greeks": {"enabled": False}}, providers=DummyProviders(), csv_sink=None, influx_sink=None, metrics=DummyMetrics())
    ctx.index_params = {
        "NIFTY": {"enable": True, "strikes_itm": 2, "strikes_otm": 2, "expiries": ["this_week"]},
        "BANKNIFTY": {"enable": True, "strikes_itm": 2, "strikes_otm": 2, "expiries": ["this_week"]},
    }
    elapsed = run_cycle(ctx)  # type: ignore[arg-type]
    assert elapsed >= 0
    # Ensure both indices were touched by provider
    ops = [c for c in ctx.providers.calls if c[0] == "get_index_data"]  # type: ignore[attr-defined]
    assert {c[1] for c in ops} == {"NIFTY", "BANKNIFTY"}