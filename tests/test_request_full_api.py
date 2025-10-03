from scripts.summary.sse_state import PanelStateStore


def test_request_full_reasons_accumulate_and_dedupe():
    store = PanelStateStore()
    # initial: need_full True by default but no reasons list
    assert store.pop_need_full_reasons() == []
    store.request_full('generation_mismatch')
    store.request_full('generation_mismatch')  # dedupe sequential
    store.request_full('network_reconnect')
    reasons = store.pop_need_full_reasons()
    assert reasons == ['generation_mismatch', 'network_reconnect']
    # replace reasons list
    store.request_full('manual_override', append=False)
    assert store.pop_need_full_reasons() == ['manual_override']
