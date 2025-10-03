from __future__ import annotations

import pytest
from typing import Dict, Any

from scripts.summary.sse_state import PanelStateStore


def test_panel_state_full_then_diff_applies():
    store = PanelStateStore()
    baseline = {"a": 1, "nested": {"x": 10, "y": 20}}
    store.apply_panel_full(baseline, server_generation=5)
    status, srv_gen, ui_gen, need_full, counters, sev_counts, sev_state, followups = store.snapshot()
    assert srv_gen == 5
    assert ui_gen == 1
    assert need_full is False
    assert counters['panel_full'] == 1
    # Apply diff modifying nested.x and removing y, adding z
    diff = {"nested": {"x": 11, "y": None, "z": 99}}
    applied = store.apply_panel_diff(diff, server_generation=5)
    assert applied is True
    status2, srv_gen2, ui_gen2, need_full2, counters2, _sc2, _ss2, _fu2 = store.snapshot()
    assert srv_gen2 == 5
    assert ui_gen2 == 2
    assert need_full2 is False
    assert counters2['panel_diff_applied'] == 1
    assert status2 is not None and isinstance(status2, dict)
    nested = status2.get('nested')
    assert isinstance(nested, dict)
    assert nested['x'] == 11
    assert 'y' not in nested
    assert nested['z'] == 99


def test_panel_state_diff_before_full_dropped():
    store = PanelStateStore()
    diff = {"k": 1}
    applied = store.apply_panel_diff(diff, server_generation=1)
    assert applied is False
    status, srv_gen, ui_gen, need_full, counters, _sc, _ss, _fu = store.snapshot()
    assert counters['panel_diff_dropped'] == 1
    assert need_full is True
    assert status is None


def test_panel_state_generation_mismatch_drops():
    store = PanelStateStore()
    store.apply_panel_full({"k": 1}, server_generation=2)
    # Apply diff with mismatched generation (3)
    diff = {"k": 2}
    applied = store.apply_panel_diff(diff, server_generation=3)
    assert applied is False
    status, srv_gen, ui_gen, need_full, counters, _sc, _ss, _fu = store.snapshot()
    # Should still have old state and mark need_full True
    assert status is not None and status['k'] == 1
    assert need_full is True
    assert counters['panel_diff_dropped'] == 1


def test_panel_state_server_generation_increment_fallback():
    store = PanelStateStore()
    # Provide no server_generation -> fallback increments local
    store.apply_panel_full({"k": 1}, server_generation=None)
    status, srv_gen, ui_gen, need_full, counters, _sc, _ss, _fu = store.snapshot()
    assert isinstance(srv_gen, int)
    assert ui_gen == 1
    # Apply diff also without generation -> allowed (no mismatch check)
    applied = store.apply_panel_diff({"k": 2}, server_generation=None)
    assert applied is True
    status2, srv_gen2, ui_gen2, need_full2, counters2, _sc2, _ss2, _fu2 = store.snapshot()
    assert status2 is not None and status2['k'] == 2
    assert ui_gen2 == 2
    assert need_full2 is False

if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
