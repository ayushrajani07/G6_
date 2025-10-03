import os
import json
from pathlib import Path

from src.events.event_log import (
    dispatch,
    events_enabled,
    set_cycle_correlation,
    register_events_metrics,
    set_min_level,
    set_sampling,
    set_default_sampling,
    get_recent_events,
)


def test_event_log_writes_tmp_path(tmp_path, monkeypatch):
    log_file = tmp_path / "events.ndjson"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    dispatch("unit_test_event", level="info", index="NIFTY", context={"k": 1})
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "unit_test_event"
    assert rec["index"] == "NIFTY"
    assert rec["context"] == {"k": 1}
    assert "ts" in rec


def test_event_log_disable(monkeypatch, tmp_path):
    log_file = tmp_path / "events.log"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    monkeypatch.setenv("G6_EVENTS_DISABLE", "true")
    assert events_enabled() is False
    dispatch("should_not_write")
    assert not log_file.exists()


class DummyCounter:
    def __init__(self):
        self.counts = {}

    def labels(self, *, event: str):  # mimic prometheus client style
        self.counts.setdefault(event, 0)
        class _Inc:
            def __init__(self, outer, key):
                self._outer = outer; self._key = key
            def inc(self):
                self._outer.counts[self._key] += 1
        return _Inc(self, event)


def test_event_log_sequence_and_metrics(monkeypatch, tmp_path):
    log_file = tmp_path / "events_seq.log"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    # Reset internal sequence by reloading module via direct mutation
    import src.events.event_log as evt_mod  # type: ignore
    # Access and reset the private counter (test-only)
    if hasattr(evt_mod, "_seq"):
        evt_mod._seq = 0  # type: ignore[attr-defined]
    counter = DummyCounter()
    register_events_metrics(counter)  # attach dummy
    set_cycle_correlation("cycle-123")
    dispatch("first")
    dispatch("second", correlation_id="override")
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["seq"] == 1 and rec2["seq"] == 2
    assert rec1["correlation_id"] == "cycle-123"
    assert rec2["correlation_id"] == "override"  # explicit wins
    assert counter.counts["first"] == 1 and counter.counts["second"] == 1


def test_event_log_level_filter(monkeypatch, tmp_path):
    log_file = tmp_path / "level.log"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    import importlib, src.events.event_log as evt_mod
    importlib.reload(evt_mod)
    evt_mod.set_min_level("warn")
    evt_mod.dispatch("info_hidden", level="info")
    evt_mod.dispatch("warn_visible", level="warn")
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "warn_visible"


def test_event_log_sampling(monkeypatch, tmp_path):
    log_file = tmp_path / "sample.log"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    import importlib, src.events.event_log as evt_mod
    importlib.reload(evt_mod)
    evt_mod.set_sampling("drop_me", 0.0)
    for _ in range(5):
        evt_mod.dispatch("drop_me")
    evt_mod.dispatch("keep_me")
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "keep_me"


def test_event_log_recent_api(monkeypatch, tmp_path):
    log_file = tmp_path / "recent.log"
    monkeypatch.setenv("G6_EVENTS_LOG_PATH", str(log_file))
    import importlib, src.events.event_log as evt_mod
    importlib.reload(evt_mod)
    for i in range(10):
        evt_mod.dispatch(f"evt_{i}", context={"i": i})
    recent = evt_mod.get_recent_events(limit=5, include_context=False)
    assert len(recent) == 5
    # Newest first
    assert recent[0]["event"] == "evt_9"
    assert recent[-1]["event"] == "evt_5"
    assert all("context" not in r for r in recent)
