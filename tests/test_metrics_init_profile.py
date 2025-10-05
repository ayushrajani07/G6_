from __future__ import annotations
import os
from src.metrics.testing import force_new_metrics_registry

def test_metrics_init_profile_segments_present():
    os.environ['G6_METRICS_PROFILE_INIT'] = '1'
    os.environ['G6_METRICS_SKIP_PROVIDER_MODE_SEED'] = '1'  # deterministic skip of seeding segment
    reg = force_new_metrics_registry(enable_resource_sampler=False)
    profile = getattr(reg, '_init_profile', None)
    assert profile, 'Expected _init_profile to be populated'
    phases = profile.get('phases_ms', {})
    assert 'group_gating' in phases, phases
    assert 'spec_registration' in phases, phases
    # provider_mode_seed intentionally skipped; aliases present
    assert 'aliases_canonicalize' in phases, phases
    total = profile.get('total_ms', 0.0)
    # Sanity: each recorded phase should be <= total (allow floating rounding)
    assert all(v <= total + 1e-3 for v in phases.values()), (phases, total)
    # Clean up env to avoid leakage for other tests
    os.environ.pop('G6_METRICS_PROFILE_INIT', None)
