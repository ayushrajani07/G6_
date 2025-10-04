from __future__ import annotations

import os

from src.utils import serialization_cache as sc


def test_serialization_cache_hits():
    sc._reset_for_tests()  # reset global cache
    os.environ['G6_SERIALIZATION_CACHE_MAX'] = '10'
    cache = sc.get_serialization_cache()
    before_hits = cache.hits
    data1 = sc.serialize_event('x', {'a': 1})
    data2 = sc.serialize_event('x', {'a': 1})
    assert data1 == data2
    assert cache.hits == before_hits + 1  # second call is a hit
    assert cache.misses == 1
