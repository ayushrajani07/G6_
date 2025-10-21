#!/usr/bin/env python3
import importlib

from prometheus_client import REGISTRY

# Force import via facade (legacy path retained for historical comparison tests elsewhere)
m = importlib.import_module('src.metrics')
try:
    if hasattr(m, 'get_metrics_singleton'):
        m.get_metrics_singleton()
except Exception as e:
    print('Singleton init error:', e)

names = sorted({fam.name for fam in REGISTRY.collect() if fam.name.startswith('g6_')})
TARGETS = [
    'g6_iv_estimation_failure_total',
    'g6_iv_estimation_success_total',
    'g6_panels_integrity_mismatches_total',
    'g6_root_cache_hits_total',
    'g6_root_cache_misses_total',
]
missing = [t for t in TARGETS if t not in names]
print('TOTAL_METRICS', len(names))
print('MISSING_TARGETS', missing)
print('PRESENT_TARGETS', [t for t in TARGETS if t in names])
print('\nNearby (iv/panels/root_cache) subset:')
for n in names:
    if any(k in n for k in ('iv_estimation','panels_integrity','root_cache')):
        print(n)
