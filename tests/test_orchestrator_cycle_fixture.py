import pytest


def test_real_orchestrator_single_cycle(run_orchestrator_cycle):
    data = run_orchestrator_cycle(cycles=1, interval=1)
    # Basic required keys
    for k in ("timestamp","cycle","elapsed","interval","sleep_sec","indices","indices_info"):
        assert k in data, f"missing key {k} in status: {data.keys()}"
    assert isinstance(data["indices_info"], dict) and data["indices_info"], "indices_info empty"
    # Cycle should be 0 for single cycle (zero-based final cycle)
    assert data["cycle"] in (0,1)  # allow 1 if underlying run_cycle assigns 1-based


def test_real_orchestrator_multi_cycle_progress(run_orchestrator_cycle):
    data = run_orchestrator_cycle(cycles=3, interval=1)
    # Expect final cycle >=2 (zero-based) or >=3 (one-based) depending on implementation
    assert data.get("cycle") >= 2, f"unexpected final cycle: {data}"
