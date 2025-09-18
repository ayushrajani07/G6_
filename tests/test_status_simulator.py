from __future__ import annotations

import json
from pathlib import Path

import scripts.status_simulator as sim


def test_simulator_writes_expected_shape(tmp_path: Path):
    out = tmp_path / "runtime_status.json"
    # Run two quick cycles
    rc = sim.main([
        "--status-file", str(out),
        "--indices", "NIFTY,BANKNIFTY",
        "--interval", "60",
        "--refresh", "0",
        "--cycles", "2",
        "--open-market",
        "--with-analytics",
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    # Top-level keys
    for key in [
        "app", "market", "loop", "indices", "indices_detail", "provider",
        "health", "sinks", "resources", "config", "links",
    ]:
        assert key in data, f"missing key: {key}"
        assert isinstance(data[key], dict), f"key {key} not a dict"

    # Indices present
    assert "NIFTY" in data["indices"], "NIFTY missing"
    assert "BANKNIFTY" in data["indices_detail"], "BANKNIFTY detail missing"
    assert isinstance(data["indices_detail"]["NIFTY"].get("ltp"), (int, float))
    # Loop fields
    assert isinstance(data["loop"].get("cycle"), int)
    assert isinstance(data["loop"].get("next_run_in_sec", 0), (int, float))
    # Analytics present when requested
    assert "analytics" in data
