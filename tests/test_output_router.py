import os
import io
import json
from typing import Any

import pytest

from src.utils.output import OutputRouter, StdoutSink, MemorySink, JsonlSink, get_output


def test_memory_sink_collects_events():
    mem = MemorySink()
    r = OutputRouter([mem], min_level="debug")
    r.info("hello", scope="unit", tags=["t1"], data={"a": 1})
    assert len(mem.events) == 1
    evt = mem.events[0]
    assert evt.level == "info" and evt.message == "hello"
    assert evt.scope == "unit"
    assert evt.data == {"a": 1}


def test_level_filtering_blocks_lower_levels():
    mem = MemorySink()
    r = OutputRouter([mem], min_level="warning")
    r.info("nope")
    r.warning("yep")
    assert [e.level for e in mem.events] == ["warning"]


def test_stdout_sink_writes_stream(monkeypatch):
    buf = io.StringIO()
    sink = StdoutSink(stream=buf)
    r = OutputRouter([sink])
    r.success("good", data={"ok": True})
    out = buf.getvalue()
    assert "SUCCESS" in out or "[SUCCESS]" in out
    assert "ok" in out


def test_jsonl_sink_appends(tmp_path):
    p = tmp_path / "out.jsonl"
    sink = JsonlSink(str(p))
    mem = MemorySink()
    r = OutputRouter([sink, mem], min_level="debug")
    r.debug("dbg", data=[1, 2, 3])
    text = p.read_text("utf-8").strip()
    line = json.loads(text)
    assert line["level"] == "debug"
    assert line["data"] == [1, 2, 3]
    assert len(mem.events) == 1


def test_get_output_from_env_defaults(monkeypatch):
    monkeypatch.delenv("G6_OUTPUT_SINKS", raising=False)
    monkeypatch.delenv("G6_OUTPUT_LEVEL", raising=False)
    r = get_output(reset=True)
    # Should have at least one sink and min level info
    assert r is get_output()
    r.info("ping")


def test_get_output_with_memory_sink(monkeypatch):
    monkeypatch.setenv("G6_OUTPUT_SINKS", "memory")
    r = get_output(reset=True)
    # Not directly accessible, so route an event and check no exceptions
    r.info("ok")
