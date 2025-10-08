import os, threading, time
from types import SimpleNamespace
from collections import Counter

# Enable batching for the test
os.environ['G6_KITE_QUOTE_BATCH'] = '1'
os.environ['G6_KITE_QUOTE_BATCH_WINDOW_MS'] = '20'

from src.broker.kite import quotes  # after env flags

class DummyKite:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
    def quote(self, symbols):
        with self.lock:
            self.calls.append(list(symbols))
        # Return simple dict with last_price for each symbol
        return {s: {"last_price": idx+100} for idx, s in enumerate(symbols)}

class Settings: kite_timeout_sec = 2.0

class Provider(SimpleNamespace):
    pass

def _worker(provider, syms, out_list):
    res = quotes.get_quote(provider, syms)
    out_list.append(res)


def test_quote_batching_collapses_calls():
    provider = Provider(kite=DummyKite(), _settings=Settings(), _auth_failed=False, _api_rl=None,
                        _rl_fallback=None, _rl_quote_fallback=None, _synthetic_quotes_used=0, _last_quotes_synthetic=False)
    outputs = []
    threads = []
    # Launch several threads nearly simultaneously with overlapping symbols
    symbol_sets = [
        ["NSE:ABC", "NSE:XYZ"],
        ["NSE:XYZ", "NSE:PQR"],
        ["NSE:LMN"],
        ["NSE:ABC", "NSE:PQR"],
    ]
    for s in symbol_sets:
        t = threading.Thread(target=_worker, args=(provider, s, outputs))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    # Expect only one underlying kite.quote call due to batching (allow 2 if race, but assert strong collapse)
    call_count = len(provider.kite.calls)
    assert call_count <= 2, f"Expected 1 or 2 batched calls, got {call_count} ({provider.kite.calls})"
    # Validate each output contains exactly requested symbols
    # Sort outputs alignment because batching may alter thread completion order.
    # Build a multiset of requested symbol sets vs result symbol sets to ensure 1:1 coverage.
    requested_sets = [frozenset(s) for s in symbol_sets]
    result_sets = [frozenset(r.keys()) for r in outputs]
    assert Counter(requested_sets) == Counter(result_sets), (
        f"Mismatch requested vs result sets: {requested_sets} vs {result_sets}"
    )
    # Validate each requested set has a corresponding output payload with all symbols present
    unmatched = result_sets.copy()
    for req in requested_sets:
        try:
            idx = next(i for i, rs in enumerate(unmatched) if rs == req)
        except StopIteration:
            raise AssertionError(f"No result payload for requested set {req}; outputs={unmatched}")
        payload = outputs[result_sets.index(req)]  # first occurrence mapping
        for sym in req:
            assert sym in payload and 'last_price' in payload[sym]
        unmatched.pop(idx)
