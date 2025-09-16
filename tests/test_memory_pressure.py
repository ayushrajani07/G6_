import time
import math
from types import SimpleNamespace
from src.utils.memory_pressure import MemoryPressureManager, PressureTier

class DummyProcess:
    def __init__(self, rss_sequence):
        self._seq = rss_sequence
        self._i = 0
    def memory_info(self):
        # Return in bytes (rss)
        val = self._seq[min(self._i, len(self._seq)-1)]
        self._i += 1
        return SimpleNamespace(rss=val)

# Helper to build manager with injected process and controlled total mem

def build_manager(rss_sequence, tiers=None, recovery_seconds=1, rollback_cooldown=1, alpha=0.5):
    m = MemoryPressureManager(metrics=None, total_physical_mb=1000, tiers=tiers, sample_interval=1, smoothing_alpha=alpha)
    # Inject dummy process (type: ignore to bypass strict typing)
    m.process = DummyProcess([int(x*1024*1024) for x in rss_sequence])  # type: ignore[attr-defined]
    m.recovery_seconds = int(recovery_seconds)
    m.rollback_cooldown = int(rollback_cooldown)
    return m

def test_tier_upgrades_and_hysteresis_downgrade():
    tiers = [
        PressureTier('normal',0,0,[]),
        PressureTier('elevated',1,0.5,['reduce_depth']),
        PressureTier('high',2,0.7,['reduce_depth','skip_greeks']),
        PressureTier('critical',3,0.9,['reduce_depth','skip_greeks','drop_per_option_metrics'])
    ]
    # Extended high usage tail to push EMA above critical threshold
    seq = [400,600,800,950,980,980,980,650,450,450]
    mgr = build_manager(seq, tiers=tiers, recovery_seconds=1, alpha=0.7)
    levels = []
    for _ in range(len(seq)):
        mgr.evaluate(); levels.append(mgr.current_level)
    # Ensure we eventually reached critical (3) and started at 0
    assert levels[0] == 0
    assert 3 in levels, f"Did not reach critical; levels observed={levels}"
    time.sleep(1.05)
    mgr.evaluate()
    assert mgr.current_level < 3

def test_depth_scale_progression():
    tiers = [
        PressureTier('normal',0,0,[]),
        PressureTier('elevated',1,0.5,['reduce_depth']),
        PressureTier('high',2,0.7,['reduce_depth']),
        PressureTier('critical',3,0.85,['reduce_depth'])
    ]
    seq = [300,600,750,900]
    mgr = build_manager(seq, tiers=tiers, alpha=0.8)
    expected_order = [0,1,2,3]
    seen = set()
    for i in range(len(seq)):
        mgr.evaluate()
        seen.add(mgr.current_level)
    for lvl in expected_order:
        assert lvl in seen  # all levels eventually visited
    assert mgr.depth_scale <= 0.4 + 1e-6

def test_depth_scale_extreme_ema_reduction():
    tiers = [
        PressureTier('normal',0,0,[]),
        PressureTier('critical',3,0.5,['reduce_depth'])
    ]
    mgr = MemoryPressureManager(metrics=None, total_physical_mb=1000, tiers=tiers, sample_interval=1, smoothing_alpha=1.0)
    mgr.process = DummyProcess([960*1024*1024])  # type: ignore[attr-defined]
    mgr.evaluate()
    assert math.isclose(mgr.depth_scale, 0.32, rel_tol=1e-6)

def test_feature_rollback_cooldowns():
    tiers = [
        PressureTier('normal',0,0,[]),
        PressureTier('high',2,0.7,['skip_greeks']),
    ]
    seq = [800,800,400,400,400,400]
    mgr = build_manager(seq, tiers=tiers, recovery_seconds=1, rollback_cooldown=1, alpha=0.9)
    mgr.evaluate(); mgr.evaluate(); assert mgr.current_level == 2
    assert not mgr.greeks_enabled  # Greeks disabled
    for _ in range(3):
        mgr.evaluate()
    time.sleep(1.05)
    mgr.evaluate(); assert mgr.current_level == 0
    if not mgr.greeks_enabled:
        time.sleep(1.05)
        mgr._maybe_enable_features(); assert mgr.greeks_enabled
