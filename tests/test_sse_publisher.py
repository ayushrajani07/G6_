"""Tests for SSEPublisher heartbeat and diff behavior.

Validates:
1. Initial cycle emits 'hello' then 'full_snapshot'.
2. Unchanged panels for N cycles (>= heartbeat interval) emit a 'heartbeat'.
3. Changing a panel triggers a 'panel_update' (non-structured mode) with expected keys.

Environment: Sets short heartbeat (G6_SSE_HEARTBEAT_CYCLES=2) for deterministic test. Publisher always enabled.
"""
from __future__ import annotations
import os
from typing import Dict, Any

import pytest

from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.plugins.base import SummarySnapshot


def make_snapshot(cycle: int, status: Dict[str, Any]) -> SummarySnapshot:
    # Provide required dataclass fields; minimal empty mappings for those SSEPublisher ignores.
    return SummarySnapshot(
        status=status,
        derived={},
        panels={},
        ts_read=0.0,
        ts_built=0.0,
        cycle=cycle,
        errors=(),
        model=None,
        domain=None,
        panel_hashes=None,  # force publisher to compute hashes
    )


@pytest.fixture(autouse=True)
def _sse_env(monkeypatch):
    monkeypatch.setenv("G6_SSE_HEARTBEAT_CYCLES", "2")  # small for test
    yield


def test_initial_full_and_heartbeat_then_update(monkeypatch):
    pub = SSEPublisher(diff=True)
    # Baseline status with minimal keys referenced by panel rendering logic.
    status = {"indices": ["NIFTY", "BANKNIFTY"], "alerts": {"total": 0}, "app": {"version": "1.2.3"}}

    # Cycle 0 -> expect hello + full_snapshot
    snap0 = make_snapshot(0, status.copy())
    pub.process(snap0)
    evts = pub.events
    assert len(evts) == 2, f"expected 2 initial events, got {len(evts)}: {[e['event'] for e in evts]}"
    assert evts[0]["event"] == "hello"
    assert evts[1]["event"] == "full_snapshot"
    full_payload = evts[1]["data"]["panels"]
    assert "indices" in full_payload and "alerts" in full_payload

    # Next two unchanged cycles: no diff events until heartbeat threshold reached
    snap1 = make_snapshot(1, status.copy())
    pub.process(snap1)
    snap2 = make_snapshot(2, status.copy())
    pub.process(snap2)
    # Heartbeat should have been appended at cycle2 since no changes for 2 cycles (threshold=2)
    evt_types = [e["event"] for e in pub.events]
    assert "heartbeat" in evt_types, f"heartbeat not emitted; events={evt_types}"
    hb_events = [e for e in pub.events if e["event"] == "heartbeat"]
    assert hb_events[-1]["data"].get("unchanged") is True

    # Introduce a change (alerts total increment)
    status_changed = {"indices": ["NIFTY", "BANKNIFTY"], "alerts": {"total": 1}, "app": {"version": "1.2.3"}}
    snap3 = make_snapshot(3, status_changed)
    pub.process(snap3)
    last_evt = pub.events[-1]
    assert last_evt["event"] in ("panel_update", "panel_diff"), f"Unexpected last event type {last_evt['event']}"
    # In non-structured mode default we expect panel_update
    if last_evt["event"] == "panel_update":
        ups = last_evt["data"].get("updates") or []
        changed_keys = {u.get("key") for u in ups}
        assert "alerts" in changed_keys, f"alerts panel not in updates: {changed_keys}"
    else:  # structured diff path
        panels_map = last_evt["data"].get("panels") or {}
        assert "alerts" in panels_map
