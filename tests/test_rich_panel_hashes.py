import copy
from scripts.summary.rich_diff import compute_panel_hashes


def _base_status():
    return {
        "app": {"version": "1.2.3"},
        "indices": ["NIFTY","BANKNIFTY"],
        "alerts": [{"id": 1, "sev": "warn"}],
        "analytics": {"vol": 12},
        "resources": {"cpu": 0.1},
        "storage": {"lag": 5},
    }


def test_hash_stability_no_change():
    s = _base_status()
    h1 = compute_panel_hashes(s)
    h2 = compute_panel_hashes(copy.deepcopy(s))
    assert h1 == h2, "Hashes should be stable across identical snapshots"


def test_hash_changes_on_indices_mutation():
    s = _base_status()
    h1 = compute_panel_hashes(s)
    s["indices"].append("FINNIFTY")
    h2 = compute_panel_hashes(s)
    assert h1["indices"] != h2["indices"], "Indices hash should change when list mutates"
    # Header also depends on indices
    assert h1["header"] != h2["header"], "Header hash should change when indices change"


def test_hash_changes_on_alerts_mutation():
    s = _base_status()
    h1 = compute_panel_hashes(s)
    s["alerts"].append({"id": 2, "sev": "crit"})
    h2 = compute_panel_hashes(s)
    assert h1["alerts"] != h2["alerts"], "Alerts hash should change when alerts mutate"


def test_unaffected_panels_remain_same():
    s = _base_status()
    h1 = compute_panel_hashes(s)
    s["resources"]["cpu"] = 0.2  # affects perfstore only
    h2 = compute_panel_hashes(s)
    assert h1["perfstore"] != h2["perfstore"]
    # Indices unchanged
    assert h1["indices"] == h2["indices"]

