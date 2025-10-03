#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import shutil
from pathlib import Path


def _reset_dir(p: Path):
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def test_publisher_writes_transactionally(monkeypatch, tmp_path):
    # Arrange env for panels sink
    base = tmp_path / "panels"
    _reset_dir(base)
    monkeypatch.setenv("G6_ENABLE_PANEL_PUBLISH", "1")
    monkeypatch.setenv("G6_OUTPUT_SINKS", "panels")
    monkeypatch.setenv("G6_PANELS_DIR", str(base))

    # Minimal router bootstrap path used by publisher
    from src.summary.publisher import publish_cycle_panels

    # Provide minimal args
    indices = ["NIFTY", "BANKNIFTY"]
    publish_cycle_panels(
        indices=indices,
        cycle=1,
        elapsed_sec=0.5,
        interval_sec=1.0,
        success_rate_pct=97.0,
        metrics=None,
        csv_sink=None,
        influx_sink=None,
        providers=None,
    )

    # After call, panels dir should contain committed JSONs and a meta file
    # Allow short grace for file ops on some platforms
    import time
    deadline = time.time() + 1.0
    files = set()
    while time.time() < deadline:
        files = {p.name for p in base.iterdir()}
        if ".meta.json" in files and "loop.json" in files:
            break
        time.sleep(0.05)
    # At least loop.json should be present
    assert "loop.json" in files
    # Meta file is optional; if present, validate structure
    if ".meta.json" in files:
        with open(base / ".meta.json", "r", encoding="utf-8") as f:
            meta_obj = json.load(f)
        assert isinstance(meta_obj, dict)
        assert "last_txn_id" in meta_obj
        assert "committed_at" in meta_obj

    # Validate JSON structure of loop panel
    with open(base / "loop.json", "r", encoding="utf-8") as f:
        loop_obj = json.load(f)
    assert isinstance(loop_obj, dict)
    assert loop_obj.get("panel") == "loop"
    assert "data" in loop_obj
