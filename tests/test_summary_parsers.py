from __future__ import annotations

from scripts.summary.derive import (
    derive_indices,
    derive_market_summary,
    derive_cycle,
    estimate_next_run,
    derive_health,
)


def test_derive_indices_from_list_and_dict():
    assert derive_indices({"indices": ["NIFTY", "BANKNIFTY"]}) == ["NIFTY", "BANKNIFTY"]
    assert set(derive_indices({"indices": {"NIFTY": {}, "SENSEX": {}}})) == {"NIFTY", "SENSEX"}


def test_market_summary_enriched_and_legacy():
    st, _ = derive_market_summary({"market": {"status": "OPEN"}})
    assert st == "OPEN"
    st2, _ = derive_market_summary({"market_open": True})
    assert st2 == "OPEN"


def test_cycle_parsing_and_next_run():
    status = {"loop": {"cycle": 10, "last_run": "2025-09-17T10:00:00Z", "next_run_in_sec": 5}}
    cy = derive_cycle(status)
    assert cy["cycle"] == 10
    nr = estimate_next_run(status, interval=60)
    # Prefer next_run_in_sec
    assert nr == 5


def test_health_parsing_dict_and_list():
    healthy, total, items = derive_health({"health": {"collector": "ok", "sinks": {"status": "healthy"}}})
    assert healthy == 2 and total == 2 and len(items) == 2
    healthy2, total2, items2 = derive_health({"components": [{"name": "x", "status": "ready"}, {"name": "y", "status": "down"}]})
    assert healthy2 == 1 and total2 == 2 and len(items2) == 2
