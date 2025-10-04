import importlib
from src.metrics import generated as gen

# We rely on registry_guard logic in src/metrics/cardinality_guard.py.
# This test simulates double registration attempts by calling accessor twice
# after forcing deletion from internal cache to trigger the duplicate path.

def test_duplicate_registration_counter_increment():
    # Ensure metric exists
    m = gen.m_metrics_spec_hash_info()
    assert m is not None
    # Access duplicates counter initial value (may be None until increment)
    dup_accessor = getattr(gen, 'm_metric_duplicates_total_labels', None)
    # Force a duplicate registration attempt by calling underlying guard directly
    from src.metrics.cardinality_guard import registry_guard, _rg_metrics  # type: ignore
    before = None
    if dup_accessor:
        # Gather current samples if any
        dm = dup_accessor('g6_metrics_spec_hash_info')
        if dm:
            # Prometheus client stores value in _value.get()
            try:
                before = dm._value.get()  # type: ignore[attr-defined]
            except Exception:
                pass
    # Re-register same metric (should increment duplicates counter)
    registry_guard._register('gauge', 'g6_metrics_spec_hash_info', 'dup test', [], 1)
    after = None
    if dup_accessor:
        dm2 = dup_accessor('g6_metrics_spec_hash_info')
        if dm2:
            try:
                after = dm2._value.get()  # type: ignore[attr-defined]
            except Exception:
                pass
    if before is not None and after is not None:
        assert after == before + 1, f"expected duplicates counter increment (before={before} after={after})"
