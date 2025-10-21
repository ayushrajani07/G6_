from prometheus_client import REGISTRY

from src.metrics import get_metrics

m = get_metrics()
attrs_present = [a for a in ['root_cache_hits','root_cache_misses','root_cache_hit_ratio','panels_integrity_ok','panels_integrity_mismatches'] if hasattr(m,a)]
print('attrs_present', attrs_present)
names = sorted(getattr(REGISTRY,'_names_to_collectors',{}).keys())
print('registry_subset', [n for n in names if 'root_cache' in n or 'panels_integrity' in n])
