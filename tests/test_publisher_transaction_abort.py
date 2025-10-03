#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import shutil
from pathlib import Path
import pytest


def _reset_dir(p: Path):
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def test_publisher_transaction_abort_cleans_staging(monkeypatch, tmp_path):
    # Arrange env for panels sink
    base = tmp_path / "panels"
    _reset_dir(base)
    monkeypatch.setenv("G6_ENABLE_PANEL_PUBLISH", "1")
    monkeypatch.setenv("G6_OUTPUT_SINKS", "panels")
    monkeypatch.setenv("G6_PANELS_DIR", str(base))

    # Monkeypatch safe_update in publisher to raise on first call to force abort
    import src.summary.publisher as publisher

    calls = {"n": 0}

    def boom(*args, **kwargs):  # type: ignore
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(publisher, "safe_update", boom, raising=True)

    # Provide minimal args
    indices = ["NIFTY", "BANKNIFTY"]

    with pytest.raises(RuntimeError):
        publisher.publish_cycle_panels(
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

    # After abort, there should be no committed panel JSONs and no meta file
    files = {p.name for p in base.iterdir()} if base.exists() else set()
    assert ".meta.json" not in files
    # No top-level .json files should exist
    assert not any(name.endswith(".json") for name in files)

    # .txn staging root should either not exist or be empty
    txn_root = base / ".txn"
    assert not txn_root.exists() or not any(txn_root.iterdir())
