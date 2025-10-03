import os
import types
import pytest

from src.collectors.modules.memory_adjust import apply_memory_and_adaptive_scaling

class DummyCtx:
    def __init__(self, adaptive_scale_factor=1.0):
        # Mimic ctx.flags used in production path
        self.flags = {'adaptive_scale_factor': adaptive_scale_factor}

@pytest.mark.parametrize(
    "itm,otm,scale,expected_itm,expected_otm",
    [
        (10, 12, 1.0, 10, 12),
        (10, 12, 0.5, 5, 6),  # scaled down
        (1, 1, 0.1, 2, 2),    # clamp minimum 2
        (2, 2, 2.5, 5, 5),    # scale up
    ],
)
def test_depth_scale(itm, otm, scale, expected_itm, expected_otm, monkeypatch):
    mem_flags = {"depth_scale": scale}
    res = apply_memory_and_adaptive_scaling(itm, otm, mem_flags, DummyCtx(), compute_greeks=True, estimate_iv=True)
    adj_itm, adj_otm, allow, cg, ev, passthrough = res
    assert adj_itm == expected_itm
    assert adj_otm == expected_otm
    assert allow is True
    assert cg is True and ev is True
    assert passthrough is None

@pytest.mark.parametrize("flag", ["skip_greeks", "drop_per_option_metrics", "both"])    
def test_flag_effects(flag):
    mem_flags = {"depth_scale": 1.0}
    if flag in ("skip_greeks", "both"):
        mem_flags["skip_greeks"] = True
    if flag in ("drop_per_option_metrics", "both"):
        mem_flags["drop_per_option_metrics"] = True
    adj_itm, adj_otm, allow, cg, ev, passthrough = apply_memory_and_adaptive_scaling(6, 6, mem_flags, DummyCtx(), compute_greeks=True, estimate_iv=True)
    if flag in ("drop_per_option_metrics", "both"):
        assert allow is False
    else:
        assert allow is True
    if flag in ("skip_greeks", "both"):
        assert cg is False and ev is False
    else:
        assert cg is True and ev is True
    assert passthrough is None


def test_adaptive_passthrough(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_SCALE_PASSTHROUGH", "1")
    ctx = DummyCtx(adaptive_scale_factor=1.75)
    mem_flags = {"depth_scale": 1.0}
    adj_itm, adj_otm, allow, cg, ev, passthrough = apply_memory_and_adaptive_scaling(8, 10, mem_flags, ctx, compute_greeks=False, estimate_iv=True)
    # depth unchanged (scale 1.0) but passthrough factor propagated
    assert adj_itm == 8 and adj_otm == 10
    assert passthrough == pytest.approx(1.75)
    assert cg is False  # compute_greeks passed False
    assert ev is True   # estimate_iv True remains True unless skip_greeks


def test_invalid_depth_scale_graceful(monkeypatch):
    # Non-numeric depth_scale should fall back to try/except path (no raise, original counts, min clamp not triggered here)
    mem_flags = {"depth_scale": "abc"}
    adj_itm, adj_otm, allow, cg, ev, passthrough = apply_memory_and_adaptive_scaling(5, 7, mem_flags, DummyCtx(), compute_greeks=True, estimate_iv=True)
    # Since conversion fails, values remain original (>=2 so unaffected)
    assert (adj_itm, adj_otm) == (5, 7)
    assert allow is True and cg is True and ev is True and passthrough is None


def test_min_clamp_applied():
    mem_flags = {"depth_scale": 0.01}
    adj_itm, adj_otm, *_ = apply_memory_and_adaptive_scaling(3, 3, mem_flags, DummyCtx(), compute_greeks=True, estimate_iv=True)
    assert adj_itm >= 2 and adj_otm >= 2
