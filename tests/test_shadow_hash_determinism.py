import importlib

# Import the helper
shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')


def test_parity_hash_deterministic_under_strike_order():
    snap_a = {
        'expiry_date': '2025-10-09',
        'strike_count': 5,
        'instrument_count': 5,
        'enriched_keys': 5,
        'strikes': [100,105,110,115,120],
    }
    snap_b = {
        # Same data but strikes permuted; head (first 5) still same set but different order
        'expiry_date': '2025-10-09',
        'strike_count': 5,
        'instrument_count': 5,
        'enriched_keys': 5,
        'strikes': [110,100,115,105,120],
    }
    meta = {
        'coverage': {'strike': 1.0, 'field': 1.0},
        'persist_sim': {'option_count': 5, 'pcr': 0.0},
    }
    h1 = shadow_mod._compute_parity_hash(snap_a, meta)
    h2 = shadow_mod._compute_parity_hash(snap_b, meta)
    # NOTE: Current implementation slices first 5 strikes in list order, so order variance will change hash.
    # This test expresses desired property; mark xfail until canonicalization (sorted head) is added.
    # With canonicalization (sorted head) the hash should be invariant under strike order permutations.
    assert h1 == h2


def test_parity_hash_meta_noise_ignored():
    snap = {
        'expiry_date': '2025-10-09',
        'strike_count': 2,
        'instrument_count': 2,
        'enriched_keys': 2,
        'strikes': [100,105],
    }
    meta1 = {'coverage': {'strike': 1.0, 'field': 0.5}, 'persist_sim': {'option_count': 2, 'pcr': 0.1}}
    meta2 = dict(meta1)
    meta2['unrelated_key'] = {'a': 1}
    h1 = shadow_mod._compute_parity_hash(snap, meta1)
    h2 = shadow_mod._compute_parity_hash(snap, meta2)
    # Unrelated meta keys not referenced should not affect hash
    assert h1 == h2
