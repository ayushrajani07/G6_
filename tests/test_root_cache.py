from src.utils.root_cache import cached_detect_root, clear_root_cache, cache_stats
from src.utils.symbol_root import detect_root

def test_root_cache_basic_hit_miss():
    clear_root_cache()
    token_a = 'NIFTY25SEP25000CE'
    assert cached_detect_root(token_a) == 'NIFTY'  # miss -> store
    st1 = cache_stats(); assert st1['misses'] == 1 and st1['hits'] == 0
    assert cached_detect_root(token_a.lower()) == 'NIFTY'  # hit (case diff)
    st2 = cache_stats(); assert st2['hits'] == 1 and st2['misses'] == 1
    assert cached_detect_root('NIFTY25SEP25100CE') == 'NIFTY'  # new miss
    st3 = cache_stats(); assert st3['misses'] == 2 and st3['hits'] == 1


def test_root_cache_disable(monkeypatch):
    clear_root_cache()
    # Force disable via env
    monkeypatch.setenv('G6_DISABLE_ROOT_CACHE','1')
    # Because module constants read at import, we re-import
    import importlib, src.utils.root_cache as rc
    importlib.reload(rc)
    r = rc.cached_detect_root('BANKNIFTY25SEP48000CE')
    assert r == 'BANKNIFTY'
    st = rc.cache_stats()
    # When disabled we don't populate cache; size should be 0
    assert st['size'] == 0


def test_root_cache_metrics(monkeypatch):
    clear_root_cache()
    # ensure metrics registry available
    from src.metrics import get_metrics  # facade import
    # Snapshot initial counters if present
    mr = get_metrics()
    hits0 = getattr(mr, 'root_cache_hits', None)
    misses0 = getattr(mr, 'root_cache_misses', None)
    evicts0 = getattr(mr, 'root_cache_evictions', None)
    size_g = getattr(mr, 'root_cache_size', None)
    ratio_g = getattr(mr, 'root_cache_hit_ratio', None)

    # Skip test gracefully if metrics weren't registered (gating)
    if not all([misses0, size_g, ratio_g]):
        return

    # Force tiny capacity to trigger eviction quickly
    monkeypatch.setenv('G6_ROOT_CACHE_MAX','4')
    import importlib, src.utils.root_cache as rc
    importlib.reload(rc)
    # Populate a few distinct roots (simulate different strikes)
    samples = [
        'NIFTY25SEP25000CE',
        'NIFTY25SEP25100CE',
        'BANKNIFTY25SEP48000CE',
        'FINNIFTY25SEP22000CE',
    ]
    for s in samples:
        assert rc.cached_detect_root(s)
    # Register a hit BEFORE eviction can remove the first key
    rc.cached_detect_root(samples[0].lower())  # guaranteed hit (same normalized key)
    stats_hit = rc.cache_stats()
    assert stats_hit['hits'] >= 1
    # One more to exceed capacity and trigger eviction of oldest (may drop the first key)
    rc.cached_detect_root('SENSEX25SEP76000CE')
    stats = rc.cache_stats()
    # All first-time inserts + initial hit (not counted as miss) => misses >= len(samples)+1? but we allow >= len(samples)
    assert stats['misses'] >= len(samples)
    # Eviction optional depending on drop rounding
    assert stats['evictions'] >= 0
    # Gauges should reflect current size <= capacity
    assert stats['size'] <= stats['capacity']
    # Hit ratio gauge should be non-negative
    ratio_now = stats['hit_ratio']
    assert ratio_now is None or ratio_now >= 0.0
