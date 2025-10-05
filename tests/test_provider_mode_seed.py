from __future__ import annotations
import os, time
from prometheus_client import REGISTRY  # type: ignore

from src.metrics.testing import force_new_metrics_registry


def test_provider_mode_seed_fast_and_one_hot():
    # Force seeding to run even under pytest auto-skip heuristic
    os.environ['G6_METRICS_SKIP_PROVIDER_MODE_SEED'] = ''
    os.environ['G6_METRICS_FORCE_PROVIDER_MODE_SEED'] = '1'
    os.environ['G6_METRICS_INIT_SIMPLE_TRACE'] = '1'
    os.environ['G6_PROVIDER_MODE_SEED_TIMEOUT'] = '0.10'
    start = time.perf_counter()
    reg = force_new_metrics_registry(enable_resource_sampler=False)
    elapsed = time.perf_counter() - start
    # Must be under generous 0.5s (allows CI variability) and under configured timeout * 5 for slack
    assert elapsed < 0.5, f"provider mode seeding too slow: {elapsed:.3f}s"
    pm = getattr(reg, 'provider_mode', None)
    assert pm is not None and hasattr(pm, 'collect')
    fams = list(pm.collect())
    # Expect at least one sample with value 1 and label mode=primary
    assert fams and any(sample.value == 1 and sample.labels.get('mode') == 'primary' for sample in fams[0].samples), fams
    # Ensure zero or one samples have value 1 (one-hot property)
    active = [s for s in fams[0].samples if s.value == 1]
    assert len(active) == 1, f"Expected one active provider mode, found {len(active)}"
