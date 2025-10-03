from __future__ import annotations
import pytest

from src.summary.unified.sse import merge_panel_diff
from src.summary.unified.sse_client import PanelStateStore


def test_merge_panel_diff_simple_add_remove():
    base = {"a": 1, "b": 2}
    delta = {"b": None, "c": 3}
    merged = merge_panel_diff(base, delta)
    assert merged == {"a": 1, "c": 3}


def test_merge_panel_diff_nested():
    base = {"a": {"x": 1, "y": 2}, "b": 5}
    delta = {"a": {"y": None, "z": 3}}
    merged = merge_panel_diff(base, delta)
    assert merged["a"] == {"x": 1, "z": 3}
    assert merged["b"] == 5


def test_merge_panel_diff_list_replace():
    base = {"items": [1,2,3]}
    delta = {"items": [4,5]}
    merged = merge_panel_diff(base, delta)
    assert merged["items"] == [4,5]


def test_panel_state_store_generation_and_snapshot():
    store = PanelStateStore()
    store.apply_full("indices", {"n": 1})
    g1 = store.generation()
    store.apply_diff("indices", {"n": 2, "x": 3})
    g2 = store.generation()
    assert g2 == g1 + 1
    snap = store.snapshot()
    assert snap["indices"]["n"] == 2 and snap["indices"]["x"] == 3
    assert "__generation__" in snap


def test_panel_state_store_diff_merge():
    store = PanelStateStore()
    store.apply_full("provider", {"name": "A", "auth": {"valid": True}})
    store.apply_diff("provider", {"auth": {"valid": False}})
    snap = store.snapshot()
    assert snap["provider"]["auth"]["valid"] is False
